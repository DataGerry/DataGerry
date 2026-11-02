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
License verification chain (license feature part P11)

Turns a raw license blob into an accept/reject decision, reproducing OpenCelium's chain:
decrypt (P6) -> parse + schema-validate (P10) -> findByHmac against the stored activation requests
(P9) -> HMAC equality / machine binding (P4) -> startDate / endDate window checks. The first failing
stage short-circuits with a LicenseVerificationStatus explaining why; only VALID carries the
entitlement. Every non-VALID outcome is a signal for the caller to degrade to the Community (free)
tier - verification never raises.

The chain is pure and injectable: the activation-request store (anything exposing get_by_hmac), the
clock (now_ms) and the public key are all parameters, so it unit-tests without Mongo or the system
clock.

**The first two stages are decoded once per process** (``decode_entitlement``): decrypting (with its key parse)
and the schema check depend on nothing but the blob and the key, and cost about half of a verification with the
shipped RSA-4096 key, while the stored licence is verified on every gated request. Every stage that reads the
database or the clock - the activation request, the binding, the validity window - still runs on every
verification, so activating, removing or expiring a licence is seen at once, in every worker
"""
import copy
import time
from functools import lru_cache
from typing import Any, Optional

from cerberus import Validator

from cmdb.errors.security.security_errors import LicenseDecryptionError
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.hmac_binding import constant_time_equals
from cmdb.security.license.license_constants import (
    LICENSE_PUBLIC_KEY_PEM,
    ActivationRequestKey,
    LicenseVerificationStatus,
)
from cmdb.security.license.rsa_decrypt import decrypt_license_blob
# -------------------------------------------------------------------------------------------------------------------- #

# Conversion factor for the system clock (seconds) to the entitlement's epoch-millisecond dates
MILLIS_PER_SECOND: int = 1000

# endDate sentinel meaning the license never expires
NO_EXPIRY_TIMESTAMP: int = 0

# How many distinct license blobs keep their decoded content per process: the stored one, and the few an
# activation tries before it. A blob is a few hundred bytes, so the cache stays small
DECODED_LICENSE_CACHE_SIZE: int = 8


# -------------------------------------------------------------------------------------------------------------------- #
#                                          LicenseVerificationResult - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseVerificationResult:
    """
    Outcome of verifying a license blob

    Carries the LicenseVerificationStatus and, only when the status is VALID, the verified
    LicenseEntitlement
    """

    def __init__(self, status: LicenseVerificationStatus, entitlement: Optional[LicenseEntitlement] = None) -> None:
        """
        Initialises a LicenseVerificationResult

        Args:
            status (LicenseVerificationStatus): The verification outcome
            entitlement (Optional[LicenseEntitlement]): The verified entitlement (only set when VALID)
        """
        self.status = status
        self.entitlement = entitlement

    @property
    def is_valid(self) -> bool:
        """
        Whether verification succeeded

        Returns:
            bool: True if the status is VALID
        """
        return self.status == LicenseVerificationStatus.VALID


@lru_cache(maxsize=DECODED_LICENSE_CACHE_SIZE)
def _decoded_entitlement(blob: str, public_key_pem: str) -> tuple[LicenseVerificationStatus | None, Any]:
    """
    Decrypts a blob and checks its entitlement against the schema - cached, see ``decode_entitlement``

    Args:
        blob (str): The Base64 license blob
        public_key_pem (str): PEM public key to decrypt with

    Returns:
        tuple[LicenseVerificationStatus | None, Any]: The failed stage and None, or None and the entitlement data
    """
    try:
        entitlement_data: dict[str, Any] = decrypt_license_blob(blob, public_key_pem)
    except LicenseDecryptionError:
        return LicenseVerificationStatus.DECRYPT_FAILED, None

    if not Validator(LicenseEntitlement.SCHEMA).validate(entitlement_data):
        return LicenseVerificationStatus.SCHEMA_INVALID, None

    return None, entitlement_data


def decode_entitlement(blob: str, public_key_pem: str = LICENSE_PUBLIC_KEY_PEM) -> tuple[
        LicenseVerificationStatus | None, dict[str, Any] | None]:
    """
    The first two stages of the chain - decrypt, then the schema check - decoded once per process per blob

    Both depend on nothing but the blob and the key, so their outcome is kept for the next verification of the same
    blob (``DECODED_LICENSE_CACHE_SIZE`` blobs at most). A different blob - or key - is decoded afresh. The answer is
    a copy: a caller changing it cannot change what the next verification reads

    Args:
        blob (str): The Base64 license blob
        public_key_pem (str): PEM public key to decrypt with; defaults to the shipped key

    Returns:
        tuple[LicenseVerificationStatus | None, dict[str, Any] | None]: DECRYPT_FAILED or SCHEMA_INVALID and None
            when a stage failed, otherwise None and the entitlement data
    """
    failure, entitlement_data = _decoded_entitlement(blob, public_key_pem)

    return failure, copy.deepcopy(entitlement_data)


def verify_license(
    blob: str,
    activation_requests_manager: Any,
    now_ms: Optional[int] = None,
    public_key_pem: str = LICENSE_PUBLIC_KEY_PEM,
    enforce_activation_ttl: bool = False,
) -> LicenseVerificationResult:
    """
    Verifies a license blob through the full chain

    Args:
        blob (str): The Base64 license blob to verify
        activation_requests_manager (Any): The activation-request store; must expose
            get_by_hmac(hmac) returning the stored request document or None, and - when
            enforce_activation_ttl is True - is_document_expired(document, now) returning whether
            the stored request has aged past its TTL
        now_ms (Optional[int]): Epoch milliseconds to evaluate the validity window against;
            defaults to the current time
        public_key_pem (str): PEM public key to decrypt with; defaults to the shipped key
        enforce_activation_ttl (bool): When True, reject a license bound to an activation request
            whose TTL has elapsed. This must be set ONLY at activation time. The ongoing
            verification used for feature gating must leave it False, otherwise an already-activated
            license would stop working once its (one-time) activation request aged out

    Returns:
        LicenseVerificationResult: VALID with the entitlement, or a failure status to degrade on
    """
    current_ms = int(time.time() * MILLIS_PER_SECOND) if now_ms is None else now_ms

    failure, entitlement_data = decode_entitlement(blob, public_key_pem)

    if failure is not None:
        return LicenseVerificationResult(failure)

    entitlement = LicenseEntitlement.from_data(entitlement_data)

    activation_request = activation_requests_manager.get_by_hmac(entitlement.hmac)
    if activation_request is None:
        return LicenseVerificationResult(LicenseVerificationStatus.NO_ACTIVATION_REQUEST)

    stored_hmac = activation_request.get(ActivationRequestKey.HMAC, '')
    if not constant_time_equals(entitlement.hmac, stored_hmac):
        return LicenseVerificationResult(LicenseVerificationStatus.BINDING_MISMATCH)

    # Activation-request TTL (lazy expiry). Enforced ONLY at activation time: the ongoing
    # verification used for feature gating leaves enforce_activation_ttl False, so an already
    # activated license keeps working after its one-time activation request ages out.
    if enforce_activation_ttl and activation_requests_manager.is_document_expired(
            activation_request, now=current_ms // MILLIS_PER_SECOND):
        return LicenseVerificationResult(LicenseVerificationStatus.ACTIVATION_REQUEST_EXPIRED)

    if entitlement.start_date > current_ms:
        return LicenseVerificationResult(LicenseVerificationStatus.NOT_YET_VALID)

    if entitlement.end_date != NO_EXPIRY_TIMESTAMP and entitlement.end_date < current_ms:
        return LicenseVerificationResult(LicenseVerificationStatus.EXPIRED)

    return LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement)
