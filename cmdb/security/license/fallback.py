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
Free/default license fallback (license feature part P12)

An on-premise install is never license-less: with no active license - or whenever a license is
invalid (the P11 verification chain returns any non-VALID status) - the install degrades to the
Community (free) tier rather than locking the user out. This module supplies that fallback: the
embedded default activation request and free entitlement (DataGerry's equivalent of OpenCelium's
DEFAULT_AR / FREE_LICENSE), and entitlement_or_default(), the single place that maps a verification
result to either its verified entitlement or the free default.

Unlike OpenCelium these defaults are represented in code (not embedded encrypted blobs): the free
license never needs portal issuance, so there is nothing to decrypt. The default request uses the
OpenCelium placeholder fingerprint, and its hmac is computed with DataGerry's own shipped secret, so
the default entitlement and the default request share the same hmac (a consistent self-binding)
"""
from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.activation_lifecycle import build_activation_request
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import ActivationRequestKey, LicenseTier
from cmdb.security.license.verification import LicenseVerificationResult
# -------------------------------------------------------------------------------------------------------------------- #

# Placeholder machine fingerprint of the embedded default activation request (OpenCelium parity:
# the default request carries these literal placeholder tokens, not a real machine fingerprint)
DEFAULT_FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'MACHINE_UUID',
    ActivationRequestKey.MAC_ADDRESS: 'MAC_ADDRESS',
    ActivationRequestKey.SYSTEM_UUID: 'SYSTEM_UUID',
    ActivationRequestKey.COMPUTER_NAME: 'COMPUTER_NAME',
}

# Fixed id of the embedded default activation request (the OpenCelium free-sample id, reused)
DEFAULT_REQUEST_ID: str = 'eff042a1-b9db-43b3-855d-b62d712ce4c9'

# Binding hmac shared by the default request and the free entitlement (computed with the shipped secret)
DEFAULT_HMAC: str = machine_binding_hmac(DEFAULT_FINGERPRINT, DEFAULT_REQUEST_ID)

# Free entitlement validity window and quota (mirrors the OpenCelium free sample)
FREE_START_DATE: int = 1640995200000  # epoch ms, 2022-01-01
FREE_END_DATE: int = 0  # 0 = no expiry
FREE_OPERATION_USAGE: int = 25000


def default_activation_request() -> LicenseActivationRequest:
    """
    Builds the embedded default (free) activation request

    Returns:
        LicenseActivationRequest: A PENDING request over the placeholder fingerprint, bound by DEFAULT_HMAC
    """
    return build_activation_request(DEFAULT_FINGERPRINT, DEFAULT_REQUEST_ID)


def default_entitlement() -> LicenseEntitlement:
    """
    Builds the embedded free (Community) entitlement

    A fresh instance is returned on each call so callers never share mutable state. The free tier
    unlocks no subscription features, so its features list is empty

    Returns:
        LicenseEntitlement: The free-tier entitlement, bound by DEFAULT_HMAC, with no features
    """
    return LicenseEntitlement(
        hmac=DEFAULT_HMAC,
        license_type=LicenseTier.FREE.value,
        start_date=FREE_START_DATE,
        end_date=FREE_END_DATE,
        operation_usage=FREE_OPERATION_USAGE,
        features=[],
    )


def entitlement_or_default(result: LicenseVerificationResult) -> LicenseEntitlement:
    """
    Resolves a verification result to a usable entitlement, degrading to free on any failure

    This is the single place the feature applies the "invalid/missing -> Community" rule: a VALID
    result yields its verified entitlement, every other outcome yields the free default

    Args:
        result (LicenseVerificationResult): The outcome of verify_license

    Returns:
        LicenseEntitlement: The verified entitlement when VALID, otherwise the free entitlement
    """
    if result.is_valid and result.entitlement is not None:
        return result.entitlement

    return default_entitlement()
