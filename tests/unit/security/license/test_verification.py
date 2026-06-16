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
Unit tests for cmdb.security.license.verification

Drives the full chain against blobs minted with the P7 generator and a stub activation-request
store (clock and store injected, no Mongo). Asserts the happy path yields VALID with the
entitlement and that each failure stage returns its distinct status with no entitlement:
bad blob, wrong key, schema-invalid payload, unknown hmac, binding mismatch, not-yet-valid and
expired - plus that endDate 0 means no expiry. Pure tests
"""
from typing import Any, Optional

import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import (
    ActivationRequestKey,
    LicenseTier,
    LicenseVerificationStatus,
)
from cmdb.security.license.tooling.license_generator import build_entitlement, mint_license_blob
from cmdb.security.license.verification import verify_license
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048

NOW_MS: int = 1_700_000_000_000
PAST_MS: int = NOW_MS - 1_000
FUTURE_MS: int = NOW_MS + 1_000_000
NO_EXPIRY: int = 0

FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-1',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-1',
    ActivationRequestKey.COMPUTER_NAME: 'host-1',
}
REQUEST_ID: str = 'req-verify-1'
BINDING_HMAC: str = machine_binding_hmac(FINGERPRINT, REQUEST_ID)


class _StubActivationRequests:
    """Minimal activation-request store exposing only get_by_hmac, for injection into verify_license"""

    def __init__(self, by_hmac: dict[str, dict[str, Any]]) -> None:
        self._by_hmac = by_hmac

    def get_by_hmac(self, hmac: str) -> Optional[dict[str, Any]]:
        """Returns the stored activation-request document for an hmac, or None"""
        return self._by_hmac.get(hmac)


@pytest.fixture(name='rsa_keypair', scope='module')
def fixture_rsa_keypair() -> RsaKey:
    """A single RSA-2048 keypair shared across the module"""
    return RSA.generate(RSA_KEY_SIZE_BITS)


def _public_pem(keypair: RsaKey) -> str:
    """PEM of a keypair's public half"""
    return keypair.publickey().export_key().decode('utf-8')


def _store_with_binding() -> _StubActivationRequests:
    """A store holding one activation request bound to BINDING_HMAC"""
    return _StubActivationRequests({BINDING_HMAC: {ActivationRequestKey.HMAC: BINDING_HMAC}})


def _mint(rsa_keypair: RsaKey, **entitlement_overrides: Any) -> str:
    """Mints a license blob for an entitlement bound to BINDING_HMAC with the given overrides"""
    entitlement = build_entitlement(hmac_value=BINDING_HMAC, **entitlement_overrides)
    return mint_license_blob(entitlement, rsa_keypair)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              happy path                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_valid_license(rsa_keypair: RsaKey) -> None:
    """A correctly bound, in-window license verifies as VALID and carries its entitlement"""
    blob = _mint(rsa_keypair, license_type=LicenseTier.CORE.value, start_date=PAST_MS, end_date=NO_EXPIRY)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.VALID
    assert result.is_valid is True
    assert result.entitlement.license_type == LicenseTier.CORE.value


def test_no_expiry_when_end_date_zero(rsa_keypair: RsaKey) -> None:
    """endDate 0 means the license never expires, even far in the future"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)

    result = verify_license(blob, _store_with_binding(), now_ms=FUTURE_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.VALID


# -------------------------------------------------------------------------------------------------------------------- #
#                                          failure stages                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_garbage_blob_is_decrypt_failed(rsa_keypair: RsaKey) -> None:
    """A non-decryptable blob fails at the decrypt stage with no entitlement"""
    result = verify_license('not a real blob!!!', _store_with_binding(), now_ms=NOW_MS,
                            public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.DECRYPT_FAILED
    assert result.is_valid is False
    assert result.entitlement is None


def test_wrong_public_key_is_decrypt_failed(rsa_keypair: RsaKey) -> None:
    """A blob minted with one key fails to decrypt under a different public key"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    other_key = RSA.generate(RSA_KEY_SIZE_BITS)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(other_key))

    assert result.status == LicenseVerificationStatus.DECRYPT_FAILED


def test_schema_invalid_payload(rsa_keypair: RsaKey) -> None:
    """A decryptable but malformed entitlement payload fails schema validation"""
    blob = mint_license_blob({ActivationRequestKey.HMAC: BINDING_HMAC}, rsa_keypair)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.SCHEMA_INVALID


def test_no_matching_activation_request(rsa_keypair: RsaKey) -> None:
    """A valid license whose hmac matches no stored request is rejected"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    empty_store = _StubActivationRequests({})

    result = verify_license(blob, empty_store, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.NO_ACTIVATION_REQUEST


def test_binding_mismatch(rsa_keypair: RsaKey) -> None:
    """A stored request whose hmac no longer equals the license hmac fails the binding check"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    tampered_store = _StubActivationRequests({BINDING_HMAC: {ActivationRequestKey.HMAC: 'TAMPERED'}})

    result = verify_license(blob, tampered_store, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.BINDING_MISMATCH


def test_not_yet_valid(rsa_keypair: RsaKey) -> None:
    """A license whose startDate is in the future is rejected as not yet valid"""
    blob = _mint(rsa_keypair, start_date=FUTURE_MS, end_date=NO_EXPIRY)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.NOT_YET_VALID


def test_expired(rsa_keypair: RsaKey) -> None:
    """A license whose endDate is in the past is rejected as expired"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=PAST_MS)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.EXPIRED
