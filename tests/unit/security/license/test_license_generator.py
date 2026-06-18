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
Unit tests for cmdb.security.license.tooling.license_generator

The central guarantee is that the generator is the exact inverse of the P6 decrypt: anything
private_encrypt() produces, public_decrypt() recovers (single and multi block), and a minted blob
decrypts back to the same entitlement through decrypt_license_blob(). Also covers block sizing,
the entitlement assembly, and PEM loading round-trip. Pure tests (one shared keypair, tmp_path)
"""
import json
import sys
from pathlib import Path

import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.security.license.license_constants import LicenseEntitlementKey, LicenseTier
from cmdb.security.license.rsa_decrypt import decrypt_license_blob, public_decrypt
from cmdb.security.license.tooling import license_generator as gen
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048
RSA_BLOCK_SIZE_BYTES: int = 256

# Plaintext lengths that exercise the single-block and the multi-block (>245-byte chunk) paths
SINGLE_BLOCK_PAYLOAD: bytes = b'{"type":"free"}'
MULTI_BLOCK_PAYLOAD_LENGTH: int = 245 * 2 + 10


@pytest.fixture(name='rsa_keypair', scope='module')
def fixture_rsa_keypair() -> RsaKey:
    """A single RSA-2048 keypair shared across the module (key generation is slow)"""
    return RSA.generate(RSA_KEY_SIZE_BITS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                  inverse of P6 (encrypt -> decrypt)                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_private_encrypt_is_inverse_of_public_decrypt_single_block(rsa_keypair: RsaKey) -> None:
    """public_decrypt recovers exactly what private_encrypt produced (single block)"""
    ciphertext = gen.private_encrypt(SINGLE_BLOCK_PAYLOAD, rsa_keypair)

    assert len(ciphertext) == RSA_BLOCK_SIZE_BYTES
    assert public_decrypt(ciphertext, rsa_keypair.publickey()) == SINGLE_BLOCK_PAYLOAD


def test_private_encrypt_is_inverse_of_public_decrypt_multi_block(rsa_keypair: RsaKey) -> None:
    """The inverse relationship holds across multiple blocks"""
    plaintext = b'Y' * MULTI_BLOCK_PAYLOAD_LENGTH
    ciphertext = gen.private_encrypt(plaintext, rsa_keypair)

    assert len(ciphertext) == RSA_BLOCK_SIZE_BYTES * 3
    assert public_decrypt(ciphertext, rsa_keypair.publickey()) == plaintext


def test_mint_license_blob_decrypts_back_to_entitlement(rsa_keypair: RsaKey) -> None:
    """A minted blob round-trips through decrypt_license_blob to the same entitlement"""
    entitlement = gen.build_entitlement(license_type=LicenseTier.CORE.value, hmac_value='bind-1')
    blob = gen.mint_license_blob(entitlement, rsa_keypair)
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')

    assert decrypt_license_blob(blob, public_key_pem=public_pem) == entitlement


# -------------------------------------------------------------------------------------------------------------------- #
#                                          entitlement assembly                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_entitlement_uses_wire_keys_and_overrides() -> None:
    """build_entitlement keys the dict by the wire-format entitlement keys and applies overrides"""
    entitlement = gen.build_entitlement(license_type=LicenseTier.BUSINESS.value, hmac_value='bind-2')

    assert entitlement[LicenseEntitlementKey.TYPE] == LicenseTier.BUSINESS.value
    assert entitlement[LicenseEntitlementKey.HMAC] == 'bind-2'
    assert set(entitlement) == set(LicenseEntitlementKey)


def test_build_entitlement_defaults_to_free() -> None:
    """The default entitlement is the free/Community tier with no features"""
    entitlement = gen.build_entitlement()

    assert entitlement[LicenseEntitlementKey.TYPE] == LicenseTier.FREE.value
    assert entitlement[LicenseEntitlementKey.FEATURES] == []


def test_build_entitlement_carries_features() -> None:
    """build_entitlement embeds the requested feature keys"""
    entitlement = gen.build_entitlement(features=['ipam', 'webhooks'])

    assert entitlement[LicenseEntitlementKey.FEATURES] == ['ipam', 'webhooks']


# -------------------------------------------------------------------------------------------------------------------- #
#                                          key loading & sizing                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_private_encrypt_block_count_scales_with_payload(rsa_keypair: RsaKey) -> None:
    """One ciphertext block is emitted per 245-byte plaintext chunk"""
    one_chunk = gen.private_encrypt(b'a' * 245, rsa_keypair)
    just_over = gen.private_encrypt(b'a' * 246, rsa_keypair)

    assert len(one_chunk) == RSA_BLOCK_SIZE_BYTES
    assert len(just_over) == RSA_BLOCK_SIZE_BYTES * 2


def test_load_private_key_round_trip(rsa_keypair: RsaKey, tmp_path: Path) -> None:
    """load_private_key imports a PEM written to disk and yields a usable private key"""
    pem_path = tmp_path / 'priv.pem'
    pem_path.write_bytes(rsa_keypair.export_key())

    loaded = gen.load_private_key(pem_path)

    assert loaded.has_private() is True
    assert loaded.n == rsa_keypair.n


def test_minted_blob_is_written_to_file_via_helpers(rsa_keypair: RsaKey, tmp_path: Path) -> None:
    """A minted blob written out and read back decrypts to the original entitlement (file path)"""
    entitlement = gen.build_entitlement(hmac_value='bind-3')
    blob = gen.mint_license_blob(entitlement, rsa_keypair)
    out_path = tmp_path / 'license.txt'
    out_path.write_text(blob, encoding='utf-8')
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')

    assert decrypt_license_blob(out_path.read_text(encoding='utf-8'), public_key_pem=public_pem) == entitlement


def test_mint_produces_valid_json_under_the_encryption(rsa_keypair: RsaKey) -> None:
    """The encrypted payload is the compact JSON of the entitlement (sanity on the serializer)"""
    entitlement = gen.build_entitlement(hmac_value='bind-4')
    blob = gen.mint_license_blob(entitlement, rsa_keypair)
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')

    recovered = decrypt_license_blob(blob, public_key_pem=public_pem)

    assert recovered == json.loads(json.dumps(entitlement))


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CLI entry point                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_main_mints_blob_with_features_from_cli(
    rsa_keypair: RsaKey,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() mints a blob carrying the --type/--hmac/--features given on the command line"""
    private_pem = tmp_path / 'priv.pem'
    private_pem.write_bytes(rsa_keypair.export_key())
    out_path = tmp_path / 'license.txt'
    monkeypatch.setattr(sys, 'argv', [
        'license_generator',
        '--private-key', str(private_pem),
        '--type', LicenseTier.CORE.value,
        '--hmac', 'cli-bind',
        '--features', 'ipam', 'webhooks',
        '--out', str(out_path),
    ])

    gen.main()

    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')
    entitlement = decrypt_license_blob(out_path.read_text(encoding='utf-8'), public_key_pem=public_pem)

    assert entitlement[LicenseEntitlementKey.TYPE] == LicenseTier.CORE.value
    assert entitlement[LicenseEntitlementKey.HMAC] == 'cli-bind'
    assert entitlement[LicenseEntitlementKey.FEATURES] == ['ipam', 'webhooks']
