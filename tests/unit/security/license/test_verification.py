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
expired - plus that endDate 0 means no expiry. And the per-process decode (`decode_entitlement`): a blob is
decrypted once, a different blob or key afresh, a failed decode is remembered as failed, the answer is a copy, and
every stage after the decode - the store, the binding, the clock - still runs on every verification. Pure tests
"""
from typing import Any, Optional
from unittest.mock import patch

import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import (
    ActivationRequestKey,
    LicenseFeature,
    LicenseTier,
    LicenseVerificationStatus,
)
from cmdb.security.license.activation_lifecycle import is_request_expired
from cmdb.security.license.tooling.license_generator import build_entitlement, mint_license_blob
from cmdb.security.license import verification
from cmdb.security.license.verification import decode_entitlement, entitlement_window_status, verify_license
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048

NOW_MS: int = 1_700_000_000_000
PAST_MS: int = NOW_MS - 1_000
FUTURE_MS: int = NOW_MS + 1_000_000
NO_EXPIRY: int = 0

NOW_SECONDS: int = NOW_MS // 1_000
TTL_SECONDS: int = 3600
CREATED_AT_KEY: str = 'created_at'

FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-1',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-1',
    ActivationRequestKey.COMPUTER_NAME: 'host-1',
}
REQUEST_ID: str = 'req-verify-1'
BINDING_HMAC: str = machine_binding_hmac(FINGERPRINT, REQUEST_ID)


class _StubActivationRequests:
    """Minimal activation-request store for injection into verify_license

    Exposes get_by_hmac plus an is_document_expired mirroring the real manager's lazy-TTL static
    method, so the activation-time TTL branch can be exercised without Mongo.
    """

    def __init__(self, by_hmac: dict[str, dict[str, Any]]) -> None:
        self._by_hmac = by_hmac

    def get_by_hmac(self, hmac: str) -> Optional[dict[str, Any]]:
        """Returns the stored activation-request document for an hmac, or None"""
        return self._by_hmac.get(hmac)

    @staticmethod
    def is_document_expired(document: dict[str, Any], now: Optional[int] = None) -> bool:
        """Whether the stored request has aged past its TTL (created_at + ttl <= now)"""
        return is_request_expired(document[CREATED_AT_KEY], document[ActivationRequestKey.TTL], now)


def _store_with_binding_ttl(created_at: int, ttl: int = TTL_SECONDS) -> _StubActivationRequests:
    """A store holding one request bound to BINDING_HMAC carrying a created_at/ttl for expiry checks"""
    return _StubActivationRequests({BINDING_HMAC: {
        ActivationRequestKey.HMAC: BINDING_HMAC,
        CREATED_AT_KEY: created_at,
        ActivationRequestKey.TTL: ttl,
    }})


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


def test_valid_license_carries_its_features(rsa_keypair: RsaKey) -> None:
    """The features the license lists survive the chain onto the verified entitlement"""
    features = [LicenseFeature.IPAM.value, LicenseFeature.ISMS.value]
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY, features=features)

    result = verify_license(blob, _store_with_binding(), now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.VALID
    assert result.entitlement.features == features


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                       activation-request TTL (activation only)                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_activation_request_expired_when_enforced(rsa_keypair: RsaKey) -> None:
    """With enforce_activation_ttl, a bound request older than its TTL is rejected at activation"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    store = _store_with_binding_ttl(created_at=NOW_SECONDS - TTL_SECONDS - 1)

    result = verify_license(blob, store, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair),
                            enforce_activation_ttl=True)

    assert result.status == LicenseVerificationStatus.ACTIVATION_REQUEST_EXPIRED
    assert result.is_valid is False
    assert result.entitlement is None


def test_fresh_activation_request_is_valid_when_enforced(rsa_keypair: RsaKey) -> None:
    """With enforce_activation_ttl, a bound request still within its TTL verifies as VALID"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    store = _store_with_binding_ttl(created_at=NOW_SECONDS - 60)

    result = verify_license(blob, store, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair),
                            enforce_activation_ttl=True)

    assert result.status == LicenseVerificationStatus.VALID


def test_expired_activation_request_ignored_when_not_enforced(rsa_keypair: RsaKey) -> None:
    """Default (gating) verification must NOT apply the request TTL - an active license keeps working"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    store = _store_with_binding_ttl(created_at=NOW_SECONDS - TTL_SECONDS - 1)

    result = verify_license(blob, store, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.VALID


# -------------------------------------------------------------------------------------------------------------------- #
#                                        decode_entitlement (once per process)                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='counted_decrypts')
def fixture_counted_decrypts():
    """An empty decode cache and a count of the real decrypts; the cache is emptied again afterwards"""
    verification._decoded_entitlement.cache_clear()  # pylint: disable=protected-access
    calls: list[str] = []
    real = verification.decrypt_license_blob

    def _counting(blob: str, public_key_pem: str) -> dict[str, Any]:
        calls.append(blob)
        return real(blob, public_key_pem)

    with patch.object(verification, 'decrypt_license_blob', side_effect=_counting):
        yield calls

    verification._decoded_entitlement.cache_clear()  # pylint: disable=protected-access


def test_a_blob_is_decrypted_once(rsa_keypair: RsaKey, counted_decrypts: list[str]) -> None:
    """Three verifications of the stored licence, one decrypt"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)

    for _ in range(3):
        assert verify_license(blob, _store_with_binding(), NOW_MS, _public_pem(rsa_keypair)).is_valid

    assert counted_decrypts == [blob]


def test_another_blob_or_key_is_decoded_afresh(rsa_keypair: RsaKey, counted_decrypts: list[str]) -> None:
    """The cache is keyed by both - a new licence, or another key, is never answered from an old decode"""
    first = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    second = _mint(rsa_keypair, license_type=LicenseTier.BUSINESS.value, start_date=PAST_MS, end_date=NO_EXPIRY)
    other_key: str = _public_pem(RSA.generate(RSA_KEY_SIZE_BITS))

    decode_entitlement(first, _public_pem(rsa_keypair))
    decode_entitlement(second, _public_pem(rsa_keypair))
    assert decode_entitlement(first, other_key) == (LicenseVerificationStatus.DECRYPT_FAILED, None)

    assert counted_decrypts == [first, second, first]


def test_a_failed_decode_is_remembered_as_failed(rsa_keypair: RsaKey, counted_decrypts: list[str]) -> None:
    """A blob that cannot be decrypted stays DECRYPT_FAILED without being decrypted again"""
    for _ in range(2):
        assert decode_entitlement('not-a-licence', _public_pem(rsa_keypair)) == (
            LicenseVerificationStatus.DECRYPT_FAILED, None)

    assert counted_decrypts == ['not-a-licence']


def test_the_answer_is_a_copy(rsa_keypair: RsaKey, counted_decrypts: list[str]) -> None:
    """A caller changing the decoded data cannot change what the next verification reads"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY, features=[LicenseFeature.ISMS.value])

    _status, first = decode_entitlement(blob, _public_pem(rsa_keypair))
    first['features'].append(LicenseFeature.IPAM.value)
    _status, second = decode_entitlement(blob, _public_pem(rsa_keypair))

    assert second['features'] == [LicenseFeature.ISMS.value]
    assert len(counted_decrypts) == 1


def test_the_clock_is_read_on_every_verification(rsa_keypair: RsaKey, counted_decrypts: list[str]) -> None:
    """A decoded licence still expires: the validity window is judged each time"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=FUTURE_MS)
    pem: str = _public_pem(rsa_keypair)

    assert verify_license(blob, _store_with_binding(), NOW_MS, pem).status == LicenseVerificationStatus.VALID
    assert verify_license(blob, _store_with_binding(), FUTURE_MS + 1, pem).status == \
        LicenseVerificationStatus.EXPIRED
    assert len(counted_decrypts) == 1


def test_the_activation_request_is_read_on_every_verification(rsa_keypair: RsaKey,
                                                              counted_decrypts: list[str]) -> None:
    """A removed activation request unbinds a decoded licence at once"""
    blob = _mint(rsa_keypair, start_date=PAST_MS, end_date=NO_EXPIRY)
    pem: str = _public_pem(rsa_keypair)

    assert verify_license(blob, _store_with_binding(), NOW_MS, pem).is_valid
    assert verify_license(blob, _StubActivationRequests({}), NOW_MS, pem).status == \
        LicenseVerificationStatus.NO_ACTIVATION_REQUEST
    assert len(counted_decrypts) == 1


class TestEntitlementWindowStatus:
    """entitlement_window_status - the validity window both editions judge with"""

    @pytest.mark.parametrize('start, end, expected', [
        (PAST_MS, FUTURE_MS, LicenseVerificationStatus.VALID),
        (NOW_MS, NOW_MS, LicenseVerificationStatus.VALID),
        (PAST_MS, NO_EXPIRY, LicenseVerificationStatus.VALID),
        (FUTURE_MS, NO_EXPIRY, LicenseVerificationStatus.NOT_YET_VALID),
        (FUTURE_MS, FUTURE_MS + 1, LicenseVerificationStatus.NOT_YET_VALID),
        (PAST_MS - 1, PAST_MS, LicenseVerificationStatus.EXPIRED),
    ], ids=['inside', 'both-bounds-inclusive', 'no-expiry', 'not-started', 'not-started-with-end', 'ended'])
    def test_judges_the_window(self, start: int, end: int, expected: LicenseVerificationStatus) -> None:
        """Start and end inclusive, end 0 never expires, the start is judged first"""
        assert entitlement_window_status(start, end, NOW_MS) is expected
