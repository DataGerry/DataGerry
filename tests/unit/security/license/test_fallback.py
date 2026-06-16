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
Unit tests for cmdb.security.license.fallback

Pins the embedded free defaults: the free entitlement is a well-formed free-tier document, the
default request and entitlement share the same self-binding hmac, fresh instances are returned each
call, and entitlement_or_default applies the "invalid/missing -> Community" rule (VALID keeps its
entitlement, every other status degrades to free). Pure tests
"""
import pytest
from cerberus import Validator

from cmdb.security.license import fallback
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import (
    ActivationRequestStatus,
    LicenseTier,
    LicenseVerificationStatus,
)
from cmdb.security.license.verification import LicenseVerificationResult
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                          default entitlement                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_default_entitlement_is_free_tier() -> None:
    """The default entitlement is the free tier with the embedded window and quota"""
    entitlement = fallback.default_entitlement()

    assert entitlement.license_type == LicenseTier.FREE.value
    assert entitlement.start_date == fallback.FREE_START_DATE
    assert entitlement.end_date == fallback.FREE_END_DATE
    assert entitlement.operation_usage == fallback.FREE_OPERATION_USAGE


def test_default_entitlement_validates_against_schema() -> None:
    """The free entitlement is itself a well-formed entitlement document"""
    document = LicenseEntitlement.to_json(fallback.default_entitlement())

    assert Validator(LicenseEntitlement.SCHEMA).validate(document) is True


def test_default_entitlement_returns_fresh_instances() -> None:
    """Each call returns a distinct object so callers never share mutable state"""
    first = fallback.default_entitlement()
    second = fallback.default_entitlement()

    assert first is not second
    assert LicenseEntitlement.to_json(first) == LicenseEntitlement.to_json(second)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          default activation request                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_default_activation_request_is_pending_placeholder() -> None:
    """The default request is PENDING and carries the placeholder fingerprint"""
    request = fallback.default_activation_request()

    assert request.status == ActivationRequestStatus.PENDING.value
    assert request.machine_uuid == 'MACHINE_UUID'
    assert request.request_id == fallback.DEFAULT_REQUEST_ID


def test_default_request_and_entitlement_share_binding_hmac() -> None:
    """The default request and the free entitlement are bound by the same hmac"""
    request = fallback.default_activation_request()
    entitlement = fallback.default_entitlement()

    assert request.hmac == fallback.DEFAULT_HMAC
    assert entitlement.hmac == fallback.DEFAULT_HMAC


# -------------------------------------------------------------------------------------------------------------------- #
#                                          degrade-to-Community rule                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_entitlement_or_default_keeps_valid_entitlement() -> None:
    """A VALID result yields its own verified entitlement, not the default"""
    verified = LicenseEntitlement(hmac='bind', license_type=LicenseTier.BUSINESS.value)
    result = LicenseVerificationResult(LicenseVerificationStatus.VALID, verified)

    assert fallback.entitlement_or_default(result) is verified


@pytest.mark.parametrize('status', [
    LicenseVerificationStatus.DECRYPT_FAILED,
    LicenseVerificationStatus.SCHEMA_INVALID,
    LicenseVerificationStatus.NO_ACTIVATION_REQUEST,
    LicenseVerificationStatus.BINDING_MISMATCH,
    LicenseVerificationStatus.NOT_YET_VALID,
    LicenseVerificationStatus.EXPIRED,
])
def test_entitlement_or_default_degrades_on_failure(status: LicenseVerificationStatus) -> None:
    """Every non-VALID status degrades to the free entitlement"""
    result = LicenseVerificationResult(status)

    assert fallback.entitlement_or_default(result).license_type == LicenseTier.FREE.value
