# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
RSA public-key decrypt primitive for the license feature (license feature part P6)

A license is minted by ENCRYPTING the entitlement JSON with the PRIVATE key (`RSA/ECB/PKCS1Padding`,
plaintext chunked to block_size - 11 bytes); the backend recovers it by DECRYPTING with the PUBLIC
key - a homemade signature scheme inherited from OpenCelium (DataGerry ships its own RSA-4096 keys,
where OpenCelium used RSA-2048). Private-key encryption produces PKCS#1 v1.5 **type-1** padding
(`00 01 FF..FF 00 || M`), so the public-key "decrypt" is a raw modular exponentiation followed by a
type-1 unpad.

Neither pycryptodome's high-level cipher nor the `cryptography` lib exposes public-key decryption,
so this module implements it directly: walk the ciphertext in modulus-sized blocks (512 bytes for
the shipped RSA-4096 key), compute `pow(c, e, n)` per block, strip the type-1 padding, and
concatenate the recovered chunks. The block size is derived from the modulus, so any RSA size works.
decrypt_license_blob() ties it to the P5 transport and JSON parsing. Any malformed input raises
LicenseDecryptionError so the verification chain can degrade to Community
"""
# from logging import Logger, getLogger
import json
from typing import Any

from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.errors.security.security_errors import LicenseDecryptionError
from cmdb.security.license.license_constants import LICENSE_PUBLIC_KEY_PEM
from cmdb.security.license.transport import decode_binary
# -------------------------------------------------------------------------------------------------------------------- #

# LOGGER: Logger = getLogger(__name__)

# Leading byte of a PKCS#1 v1.5 encoded block (always 0x00)
PKCS1_LEADING_BYTE: int = 0x00

# Block type for private-key encryption / public-key decryption (type 1)
PKCS1_BLOCK_TYPE_1: int = 0x01

# Padding filler byte for a type-1 block (0xFF repeated)
PKCS1_PADDING_BYTE: int = 0xFF

# Separator byte between the padding run and the message (0x00)
PKCS1_SEPARATOR_BYTE: int = 0x00

# Minimum number of padding bytes PKCS#1 v1.5 requires before the separator
PKCS1_MIN_PADDING_LENGTH: int = 8

# Byte order used to convert between RSA integers and their fixed-width block encoding
RSA_BYTE_ORDER: str = 'big'

# Fixed offsets of the two leading marker bytes inside an encoded block
_LEADING_BYTE_INDEX: int = 0
_BLOCK_TYPE_INDEX: int = 1
# First padding byte sits at index 2 (after the leading byte and the block type)
_PADDING_START_INDEX: int = 2


def _strip_type1_padding(encoded_block: bytes) -> bytes:
    """
    Removes PKCS#1 v1.5 type-1 padding from a decrypted block and returns the message

    A type-1 encoded block is `00 01 FF..FF 00 || M`: a leading zero, the block-type byte, at least
    eight 0xFF padding bytes, a 0x00 separator and then the message

    Args:
        encoded_block (bytes): One decrypted, still-padded modulus-sized block

    Returns:
        bytes: The message bytes following the separator

    Raises:
        LicenseDecryptionError: If the leading bytes, padding run or separator are malformed
    """
    if (encoded_block[_LEADING_BYTE_INDEX] != PKCS1_LEADING_BYTE
            or encoded_block[_BLOCK_TYPE_INDEX] != PKCS1_BLOCK_TYPE_1):
        raise LicenseDecryptionError("License block has no valid PKCS#1 type-1 header")

    index = _PADDING_START_INDEX
    while index < len(encoded_block) and encoded_block[index] == PKCS1_PADDING_BYTE:
        index += 1

    if index >= len(encoded_block) or encoded_block[index] != PKCS1_SEPARATOR_BYTE:
        raise LicenseDecryptionError("License block padding is not terminated by a separator")

    if index - _PADDING_START_INDEX < PKCS1_MIN_PADDING_LENGTH:
        raise LicenseDecryptionError("License block padding is shorter than the PKCS#1 minimum")

    return encoded_block[index + 1:]


def _decrypt_block(block: bytes, modulus: int, exponent: int, block_size: int) -> bytes:
    """
    Public-key decrypts a single ciphertext block and strips its type-1 padding

    Args:
        block (bytes): One modulus-sized ciphertext block
        modulus (int): The RSA modulus n
        exponent (int): The RSA public exponent e
        block_size (int): The modulus size in bytes (the fixed encoded-block width)

    Returns:
        bytes: The recovered message chunk for this block

    Raises:
        LicenseDecryptionError: If the recovered integer does not fit the block or padding is invalid
    """
    cipher_int = int.from_bytes(block, RSA_BYTE_ORDER)
    plain_int = pow(cipher_int, exponent, modulus)

    try:
        encoded_block = plain_int.to_bytes(block_size, RSA_BYTE_ORDER)
    except OverflowError as err:
        raise LicenseDecryptionError("Recovered license block exceeds the modulus size") from err

    return _strip_type1_padding(encoded_block)


def public_decrypt(ciphertext: bytes, public_key: RsaKey) -> bytes:
    """
    Decrypts RSA ciphertext with a public key by walking modulus-sized blocks

    Args:
        ciphertext (bytes): The raw ciphertext; its length must be a non-zero multiple of the
            modulus size (512 bytes for RSA-4096)
        public_key (RsaKey): The RSA public key whose private half produced the ciphertext

    Returns:
        bytes: The concatenated recovered plaintext

    Raises:
        LicenseDecryptionError: If the ciphertext length is not a non-zero multiple of the block size
    """
    block_size = (public_key.n.bit_length() + 7) // 8

    if not ciphertext or len(ciphertext) % block_size != 0:
        raise LicenseDecryptionError("License ciphertext length is not a multiple of the RSA block size")

    modulus = public_key.n
    exponent = public_key.e
    plaintext = bytearray()

    for start in range(0, len(ciphertext), block_size):
        plaintext += _decrypt_block(ciphertext[start:start + block_size], modulus, exponent, block_size)

    # LOGGER.debug(f"[decrypt]: {plaintext}")

    return bytes(plaintext)


def decrypt_license_blob(blob: str, public_key_pem: str = LICENSE_PUBLIC_KEY_PEM) -> dict[str, Any]:
    """
    Decrypts and parses a Base64-encoded license blob into its entitlement dict

    Decodes the Base64 transport (P5), public-key decrypts the ciphertext, and parses the recovered
    UTF-8 JSON. Every failure mode is normalised to LicenseDecryptionError so the caller has a single
    exception to catch when degrading to Community

    Args:
        blob (str): The Base64-encoded license blob
        public_key_pem (str): PEM of the public key to decrypt with; defaults to the shipped key

    Returns:
        dict[str, Any]: The decoded license entitlement

    Raises:
        LicenseDecryptionError: If the blob cannot be decoded, decrypted or parsed as a JSON object
    """
    try:
        ciphertext = decode_binary(blob)
        public_key = RSA.import_key(public_key_pem)
        plaintext = public_decrypt(ciphertext, public_key)
        entitlement = json.loads(plaintext.decode('utf-8'))
    except (ValueError, OverflowError, IndexError) as err:
        # LicenseDecryptionError is not a ValueError, so a failure raised inside public_decrypt
        # propagates unwrapped; only the transport/import/JSON failures are normalised here
        raise LicenseDecryptionError(f"License blob could not be decrypted: {err}") from err

    if not isinstance(entitlement, dict):
        raise LicenseDecryptionError("Decrypted license payload is not a JSON object")

    return entitlement
