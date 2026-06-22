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
Unit tests for cmdb.security.license.activation_lifecycle

Pins the pure lifecycle core: a built request is PENDING and carries the OpenCelium-correct binding
HMAC (re-checked against the verified sample), the blob round-trips through the P5 transport, and
lazy TTL expiry is exact at the boundary (with time injected, plus the default-clock path). Pure tests
"""
import uuid

import pytest

from cmdb.security.license import activation_lifecycle as lc
from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
from cmdb.security.license.transport import decode_json
# -------------------------------------------------------------------------------------------------------------------- #

OPENCELIUM_SECRET: str = 'my-secret-key'

PLACEHOLDER_FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'MACHINE_UUID',
    ActivationRequestKey.MAC_ADDRESS: 'MAC_ADDRESS',
    ActivationRequestKey.SYSTEM_UUID: 'SYSTEM_UUID',
    ActivationRequestKey.COMPUTER_NAME: 'COMPUTER_NAME',
}
SAMPLE_REQUEST_ID: str = 'eff042a1-b9db-43b3-855d-b62d712ce4c9'
# OpenCelium generateActivReq order: encode(id + fingerprint), id FIRST (see test_hmac_binding)
SAMPLE_EXPECTED_HMAC: str = 'C6VD+atCNUYDIeWdMbJRGkzDbcFp5n87tcAbnxcZJeU='

# A fingerprint with distinct, realistic field values
FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-1',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-1',
    ActivationRequestKey.COMPUTER_NAME: 'host-1',
}

CREATED_AT: int = 1_000_000
TTL: int = 3600


# -------------------------------------------------------------------------------------------------------------------- #
#                                              request id                                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_new_request_id_is_a_unique_uuid() -> None:
    """new_request_id returns parseable UUID strings that differ between calls"""
    first = lc.new_request_id()
    second = lc.new_request_id()

    assert uuid.UUID(first)
    assert first != second


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_activation_request                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_activation_request_is_pending_and_bound() -> None:
    """The built request is PENDING, carries the ttl, and stores the fingerprint fields"""
    request = lc.build_activation_request(FINGERPRINT, 'req-1', ttl=TTL)

    assert request.status == ActivationRequestStatus.PENDING.value
    assert request.ttl == TTL
    assert request.machine_uuid == 'machine-1'
    assert request.hmac == machine_binding_hmac(FINGERPRINT, 'req-1')


def test_build_activation_request_matches_opencelium_sample() -> None:
    """With the OC secret + placeholders + sample id, the binding HMAC matches the id-first order"""
    request = lc.build_activation_request(PLACEHOLDER_FINGERPRINT, SAMPLE_REQUEST_ID, secret=OPENCELIUM_SECRET)

    assert request.hmac == SAMPLE_EXPECTED_HMAC


# -------------------------------------------------------------------------------------------------------------------- #
#                                          activation_request_blob                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_activation_request_blob_contains_only_the_request_file_fields() -> None:
    """The downloadable blob decodes to the six request-file fields, excluding ttl and status"""
    request = lc.build_activation_request(FINGERPRINT, 'req-1', ttl=TTL)

    decoded = decode_json(lc.activation_request_blob(request))

    assert decoded == LicenseActivationRequest.to_blob_dict(request)
    assert set(decoded) == {
        ActivationRequestKey.ID.value,
        ActivationRequestKey.HMAC.value,
        ActivationRequestKey.MACHINE_UUID.value,
        ActivationRequestKey.MAC_ADDRESS.value,
        ActivationRequestKey.SYSTEM_UUID.value,
        ActivationRequestKey.COMPUTER_NAME.value,
    }
    assert ActivationRequestKey.TTL.value not in decoded
    assert ActivationRequestKey.STATUS.value not in decoded


# -------------------------------------------------------------------------------------------------------------------- #
#                                              lazy TTL                                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('now,expected', [
    (CREATED_AT + TTL - 1, False),
    (CREATED_AT + TTL, True),
    (CREATED_AT + TTL + 1, True),
])
def test_is_request_expired_boundary(now: int, expected: bool) -> None:
    """Expiry flips exactly at created_at + ttl (inclusive)"""
    assert lc.is_request_expired(CREATED_AT, TTL, now) is expected


def test_is_request_expired_uses_current_time_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no now argument, the current clock is consulted"""
    monkeypatch.setattr(lc.time, 'time', lambda: CREATED_AT + TTL + 5)

    assert lc.is_request_expired(CREATED_AT, TTL) is True


@pytest.mark.parametrize('now,expected', [
    (CREATED_AT, TTL),
    (CREATED_AT + TTL - 60, 60),
    (CREATED_AT + TTL, 0),
    (CREATED_AT + TTL + 100, 0),
])
def test_seconds_until_expiry(now: int, expected: int) -> None:
    """Remaining seconds count down and clamp to zero once expired"""
    assert lc.seconds_until_expiry(CREATED_AT, TTL, now) == expected
