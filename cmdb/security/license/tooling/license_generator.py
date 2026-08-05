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
Dev-only license generator (license feature part P7)

Mints test license blobs the OpenCelium way - the exact inverse of the P6 public-key decrypt.
private_encrypt() PKCS#1 v1.5 type-1 pads each plaintext chunk (501 bytes for RSA-4096), raises it
with the PRIVATE key (`pow(m, d, n)`) and concatenates the 512-byte blocks; mint_license_blob() wraps an entitlement
dict (JSON -> private_encrypt -> Base64). A round-trip with decrypt_license_blob() recovers it.

This stands in for the Service Portal so we can produce signed fixtures without the real portal. It
is dev-only and never on the shipped path: it needs the PRIVATE key (which never ships) and the
backend only ever decrypts. The PKCS#1 markers are imported from rsa_decrypt so the encrypt and the
decrypt sides cannot drift
"""
import argparse
import json
from pathlib import Path
from typing import Any, Union

from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.security.license.license_constants import LicenseEntitlementKey, LicenseTier
from cmdb.security.license.transport import JSON_SEPARATORS, TEXT_ENCODING, encode_binary
from cmdb.security.license.rsa_decrypt import (
    PKCS1_BLOCK_TYPE_1,
    PKCS1_LEADING_BYTE,
    PKCS1_MIN_PADDING_LENGTH,
    PKCS1_PADDING_BYTE,
    PKCS1_SEPARATOR_BYTE,
    RSA_BYTE_ORDER,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Fixed type-1 header bytes per block: the leading 0x00, the block-type byte and the 0x00 separator
PKCS1_FIXED_HEADER_BYTES: int = 3

# Total PKCS#1 v1.5 overhead per block (fixed header + the minimum 0xFF padding run)
PKCS1_OVERHEAD_BYTES: int = PKCS1_FIXED_HEADER_BYTES + PKCS1_MIN_PADDING_LENGTH

# Default dev private-key location (written by generate_license_keys.py into the gitignored build dir)
DEFAULT_PRIVATE_KEY_PATH: str = 'target/license_keys/license_private_key.pem'

# Default output path for a minted test license blob
DEFAULT_LICENSE_OUTPUT_PATH: str = 'target/license_keys/test_license.txt'

# Default entitlement field values (mirroring OpenCelium's free sample); overridable via build_entitlement
DEFAULT_LICENSE_TYPE: str = LicenseTier.FREE.value
DEFAULT_HMAC: str = 'TEST_HMAC'
DEFAULT_START_DATE: int = 1640995200000  # epoch ms, 2022-01-01
DEFAULT_END_DATE: int = 0  # 0 = no expiry
DEFAULT_SUB_ID: str = 'dev-subscription'
DEFAULT_LICENSE_ID: str = 'dev-license'


def _pkcs1_type1_pad(chunk: bytes, block_size: int) -> bytes:
    """
    PKCS#1 v1.5 type-1 pads one plaintext chunk to a full block

    Produces `00 01 FF..FF 00 || chunk`, the padding a 0xFF run filling the block

    Args:
        chunk (bytes): The plaintext chunk (at most block_size - PKCS1_OVERHEAD_BYTES long)
        block_size (int): The RSA modulus size in bytes (the target block width)

    Returns:
        bytes: The padded block, block_size bytes long
    """
    padding_length = block_size - PKCS1_FIXED_HEADER_BYTES - len(chunk)
    padding = bytes([PKCS1_PADDING_BYTE]) * padding_length

    return bytes([PKCS1_LEADING_BYTE, PKCS1_BLOCK_TYPE_1]) + padding + bytes([PKCS1_SEPARATOR_BYTE]) + chunk


def private_encrypt(plaintext: bytes, private_key: RsaKey) -> bytes:
    """
    Private-key encrypts plaintext block by block - the inverse of rsa_decrypt.public_decrypt

    Splits the plaintext into chunks of (block_size - PKCS1_OVERHEAD_BYTES) bytes (501 for RSA-4096),
    type-1 pads each, and raises it with the private exponent

    Args:
        plaintext (bytes): The data to encrypt (e.g. the entitlement JSON)
        private_key (RsaKey): The RSA private key (license-minting key; never ships)

    Returns:
        bytes: The concatenated ciphertext (a multiple of the modulus size)
    """
    block_size = private_key.size_in_bytes()
    max_chunk = block_size - PKCS1_OVERHEAD_BYTES
    ciphertext = bytearray()

    for start in range(0, len(plaintext), max_chunk):
        padded = _pkcs1_type1_pad(plaintext[start:start + max_chunk], block_size)
        message_int = int.from_bytes(padded, RSA_BYTE_ORDER)
        cipher_int = pow(message_int, private_key.d, private_key.n)
        ciphertext += cipher_int.to_bytes(block_size, RSA_BYTE_ORDER)

    return bytes(ciphertext)


# pylint: disable=too-many-arguments, too-many-positional-arguments
def build_entitlement(
    license_type: str = DEFAULT_LICENSE_TYPE,
    hmac_value: str = DEFAULT_HMAC,
    start_date: int = DEFAULT_START_DATE,
    end_date: int = DEFAULT_END_DATE,
    sub_id: str = DEFAULT_SUB_ID,
    license_id: str = DEFAULT_LICENSE_ID,
    features: list[str] | None = None,
) -> dict[str, Any]:
    """
    Assembles a license entitlement dict keyed by the wire-format entitlement keys

    Args:
        license_type (str): The display-only tier label (a LicenseTier value)
        hmac_value (str): The machine-binding HMAC this license is bound to (must equal the
            activation request's hmac for the binding check to pass)
        start_date (int): Validity start, epoch milliseconds
        end_date (int): Validity end, epoch milliseconds (0 = no expiry)
        sub_id (str): Subscription id
        license_id (str): License id
        features (list[str] | None): The unlocked feature keys (LicenseFeature values); the sole
            source of truth for what the license grants. Defaults to none (Community/free)

    Returns:
        dict[str, Any]: The entitlement, ready for mint_license_blob
    """
    return {
        LicenseEntitlementKey.HMAC: hmac_value,
        LicenseEntitlementKey.START_DATE: start_date,
        LicenseEntitlementKey.END_DATE: end_date,
        LicenseEntitlementKey.SUB_ID: sub_id,
        LicenseEntitlementKey.LICENSE_ID: license_id,
        LicenseEntitlementKey.TYPE: license_type,
        LicenseEntitlementKey.FEATURES: list(features) if features else [],
    }


def mint_license_blob(entitlement: dict[str, Any], private_key: RsaKey) -> str:
    """
    Mints a Base64 license blob from an entitlement dict

    Serializes the entitlement to compact JSON, private-key encrypts it and Base64-encodes the
    ciphertext - the exact input decrypt_license_blob expects

    Args:
        entitlement (dict[str, Any]): The entitlement to encode (e.g. from build_entitlement)
        private_key (RsaKey): The RSA private key to sign with

    Returns:
        str: The Base64-encoded license blob
    """
    plaintext = json.dumps(entitlement, separators=JSON_SEPARATORS).encode(TEXT_ENCODING)

    return encode_binary(private_encrypt(plaintext, private_key))


def load_private_key(path: Union[str, Path]) -> RsaKey:
    """
    Loads an RSA private key from a PEM file

    Args:
        path (Union[str, Path]): Path to the PEM private key

    Returns:
        RsaKey: The imported private key
    """
    return RSA.import_key(Path(path).read_bytes())


def main() -> None:
    """
    Parses CLI args, mints a test license blob and writes it to disk
    """
    parser = argparse.ArgumentParser(description="Mint a dev/test DataGerry license blob (dev-only)")
    parser.add_argument('--private-key', default=DEFAULT_PRIVATE_KEY_PATH, help="Path to the PEM private key")
    parser.add_argument('--type', dest='license_type', default=DEFAULT_LICENSE_TYPE, help="License tier (type)")
    parser.add_argument('--hmac', default=DEFAULT_HMAC, help="Machine-binding HMAC to embed in the license")
    parser.add_argument('--features', nargs='*', default=[], metavar='FEATURE',
                        help="Feature keys to unlock (LicenseFeature values), space separated")
    parser.add_argument('--out', default=DEFAULT_LICENSE_OUTPUT_PATH, help="Output path for the license blob")
    args = parser.parse_args()

    private_key = load_private_key(args.private_key)
    entitlement = build_entitlement(license_type=args.license_type, hmac_value=args.hmac, features=args.features)
    blob = mint_license_blob(entitlement, private_key)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(blob, encoding=TEXT_ENCODING)

    print(f"Wrote a '{args.license_type}' test license blob to {out_path.resolve()}")
    print(blob)


if __name__ == '__main__':
    main()
