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
Unit tests for cmdb.security.license.rsa_decrypt

Exercises the public-key decrypt primitive against ciphertext minted the OpenCelium way - private-key
encryption with PKCS#1 type-1 padding and 245-byte chunking - so a single- and a multi-block payload
both round-trip, and decrypt_license_blob recovers an entitlement end to end through the P5 transport.
The unpad logic is pinned directly with crafted blocks, and every malformed-input path is asserted to
raise LicenseDecryptionError (the verification chain's single degrade signal). Pure tests
"""
import json

import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.errors.security.security_errors import LicenseDecryptionError
from cmdb.security.license import rsa_decrypt as rd
from cmdb.security.license.transport import encode_binary
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048
RSA_BLOCK_SIZE_BYTES: int = 256

# Max plaintext chunk per block under PKCS#1 v1.5 (256-byte modulus - 11-byte overhead)
MAX_ENCRYPT_BLOCK: int = 245

# Type-1 block markers used to craft padded blocks in tests (mirroring the spec under test)
LEADING_BYTE: int = 0x00
BLOCK_TYPE_1: int = 0x01
BLOCK_TYPE_2: int = 0x02
PADDING_BYTE: int = 0xFF
SEPARATOR_BYTE: int = 0x00
MIN_PADDING: int = 8

BYTE_ORDER: str = 'big'


# -------------------------------------------------------------------------------------------------------------------- #
#                                        in-test minting helpers                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _pkcs1_pad(chunk: bytes, block_size: int, block_type: int = BLOCK_TYPE_1) -> bytes:
    """Builds one PKCS#1 v1.5 encoded block: 00 || type || padding || 00 || chunk"""
    padding_length = block_size - 3 - len(chunk)
    padding = bytes([PADDING_BYTE]) * padding_length

    return bytes([LEADING_BYTE, block_type]) + padding + bytes([SEPARATOR_BYTE]) + chunk


def _private_encrypt(plaintext: bytes, private_key: RsaKey, block_type: int = BLOCK_TYPE_1) -> bytes:
    """Mints ciphertext the OpenCelium way: private-key encrypt of type-1 padded 245-byte chunks"""
    block_size = private_key.size_in_bytes()
    blocks = bytearray()

    for start in range(0, len(plaintext), MAX_ENCRYPT_BLOCK):
        chunk = plaintext[start:start + MAX_ENCRYPT_BLOCK]
        padded = _pkcs1_pad(chunk, block_size, block_type)
        message_int = int.from_bytes(padded, BYTE_ORDER)
        cipher_int = pow(message_int, private_key.d, private_key.n)
        blocks += cipher_int.to_bytes(block_size, BYTE_ORDER)

    return bytes(blocks)


@pytest.fixture(name='rsa_keypair', scope='module')
def fixture_rsa_keypair() -> RsaKey:
    """A single RSA-2048 keypair shared across the module (key generation is slow)"""
    return RSA.generate(RSA_KEY_SIZE_BITS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          block-walk round-trips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_public_decrypt_single_block_round_trip(rsa_keypair: RsaKey) -> None:
    """A sub-chunk payload encrypts to one block and decrypts back to the original bytes"""
    plaintext = b'{"type":"free"}'
    ciphertext = _private_encrypt(plaintext, rsa_keypair)

    assert len(ciphertext) == RSA_BLOCK_SIZE_BYTES
    assert rd.public_decrypt(ciphertext, rsa_keypair.publickey()) == plaintext


def test_public_decrypt_multi_block_round_trip(rsa_keypair: RsaKey) -> None:
    """A payload longer than one chunk spans multiple blocks and is fully recovered"""
    plaintext = b'X' * (MAX_ENCRYPT_BLOCK * 2 + 10)
    ciphertext = _private_encrypt(plaintext, rsa_keypair)

    assert len(ciphertext) == RSA_BLOCK_SIZE_BYTES * 3
    assert rd.public_decrypt(ciphertext, rsa_keypair.publickey()) == plaintext


def test_decrypt_license_blob_end_to_end(rsa_keypair: RsaKey) -> None:
    """A full entitlement round-trips: mint -> Base64 -> decrypt_license_blob -> dict"""
    entitlement = {
        'hmac': 'abc',
        'startDate': 1640995200000,
        'endDate': 0,
        'subId': 's-1',
        'licenseId': 'l-1',
        'operationUsage': 25000,
        'duration': 0,
        'type': 'free',
    }
    plaintext = json.dumps(entitlement).encode('utf-8')
    blob = encode_binary(_private_encrypt(plaintext, rsa_keypair))
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')

    assert rd.decrypt_license_blob(blob, public_key_pem=public_pem) == entitlement


# -------------------------------------------------------------------------------------------------------------------- #
#                                       type-1 unpad (crafted blocks)                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_strip_type1_padding_returns_message() -> None:
    """A well-formed type-1 block yields the message after the separator"""
    block = bytes([LEADING_BYTE, BLOCK_TYPE_1]) + bytes([PADDING_BYTE]) * MIN_PADDING + bytes([SEPARATOR_BYTE]) + b'MSG'

    assert rd._strip_type1_padding(block) == b'MSG'


@pytest.mark.parametrize('block,reason', [
    (bytes([BLOCK_TYPE_1, BLOCK_TYPE_1]) + bytes([PADDING_BYTE]) * MIN_PADDING + bytes([SEPARATOR_BYTE]) + b'M',
     'bad leading byte'),
    (bytes([LEADING_BYTE, BLOCK_TYPE_2]) + bytes([PADDING_BYTE]) * MIN_PADDING + bytes([SEPARATOR_BYTE]) + b'M',
     'wrong block type'),
    (bytes([LEADING_BYTE, BLOCK_TYPE_1]) + bytes([PADDING_BYTE]) * 20,
     'no separator'),
    (bytes([LEADING_BYTE, BLOCK_TYPE_1]) + bytes([PADDING_BYTE]) * (MIN_PADDING - 1) + bytes([SEPARATOR_BYTE]) + b'M',
     'padding too short'),
])
def test_strip_type1_padding_rejects_malformed(block: bytes, reason: str) -> None:
    """Malformed type-1 blocks raise (header, separator and minimum-padding checks)"""
    with pytest.raises(LicenseDecryptionError):
        rd._strip_type1_padding(block)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        malformed decrypt inputs                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_public_decrypt_rejects_wrong_length(rsa_keypair: RsaKey) -> None:
    """Ciphertext whose length is not a multiple of the block size is rejected"""
    with pytest.raises(LicenseDecryptionError):
        rd.public_decrypt(b'\x00' * (RSA_BLOCK_SIZE_BYTES + 1), rsa_keypair.publickey())


def test_public_decrypt_rejects_empty(rsa_keypair: RsaKey) -> None:
    """Empty ciphertext is rejected"""
    with pytest.raises(LicenseDecryptionError):
        rd.public_decrypt(b'', rsa_keypair.publickey())


def test_public_decrypt_rejects_wrong_block_type(rsa_keypair: RsaKey) -> None:
    """Ciphertext minted with a non type-1 block fails the unpad after decryption"""
    ciphertext = _private_encrypt(b'payload', rsa_keypair, block_type=BLOCK_TYPE_2)

    with pytest.raises(LicenseDecryptionError):
        rd.public_decrypt(ciphertext, rsa_keypair.publickey())


def test_decrypt_license_blob_rejects_invalid_base64() -> None:
    """A non-Base64 blob is normalised to LicenseDecryptionError"""
    with pytest.raises(LicenseDecryptionError):
        rd.decrypt_license_blob('not valid base64!!!')


def test_decrypt_license_blob_rejects_non_object_payload(rsa_keypair: RsaKey) -> None:
    """Decrypted JSON that is not an object (e.g. a bare array) is rejected"""
    plaintext = json.dumps([1, 2, 3]).encode('utf-8')
    blob = encode_binary(_private_encrypt(plaintext, rsa_keypair))
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')

    with pytest.raises(LicenseDecryptionError):
        rd.decrypt_license_blob(blob, public_key_pem=public_pem)
