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
Activation-request lifecycle helpers (license feature part P9, pure core)

The pure, side-effect-free heart of the activation lifecycle: assemble a PENDING activation request
bound to this machine (its HMAC over the fingerprint + id, P4), render it to the downloadable
Base64+JSON blob (P5), and evaluate lazy TTL expiry. "Lazy TTL" means expiry is decided at read
time from a stored creation timestamp plus the ttl - no background scheduler runs in the gunicorn
workers.

Time is injected (the `now` argument) so the expiry helpers stay deterministic and unit-testable;
persistence and the current clock live in the manager that consumes these helpers
"""
import time
import uuid

from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import LICENSE_HMAC_SECRET, ActivationRequestStatus
from cmdb.security.license.transport import encode_json
# -------------------------------------------------------------------------------------------------------------------- #

# Default time-to-live for a freshly issued activation request, in seconds (matches OpenCelium's 3600)
DEFAULT_TTL_SECONDS: int = 3600


def new_request_id() -> str:
    """
    Generates a fresh activation request id

    Returns:
        str: A random UUID4 string used as the request id (and the trailing HMAC binding component)
    """
    return str(uuid.uuid4())


def build_activation_request(
    fingerprint: dict[str, str],
    request_id: str,
    ttl: int = DEFAULT_TTL_SECONDS,
    secret: str = LICENSE_HMAC_SECRET,
) -> LicenseActivationRequest:
    """
    Builds a PENDING activation request bound to the given machine fingerprint

    Computes the machine-binding HMAC over the four fingerprint fields followed by the request id
    (P4) and wraps everything in a LicenseActivationRequest

    Args:
        fingerprint (dict[str, str]): The machine fingerprint keyed by the ActivationRequestKey
            machine fields (the get_machine_fingerprint output shape)
        request_id (str): The request id (also the trailing HMAC component)
        ttl (int): Time-to-live in seconds; defaults to DEFAULT_TTL_SECONDS
        secret (str): The HMAC secret; defaults to the shipped LICENSE_HMAC_SECRET

    Returns:
        LicenseActivationRequest: The assembled PENDING activation request
    """
    binding_hmac = machine_binding_hmac(fingerprint, request_id, secret)

    return LicenseActivationRequest(
        request_id=request_id,
        hmac=binding_hmac,
        ttl=ttl,
        fingerprint=fingerprint,
        status=ActivationRequestStatus.PENDING.value,
    )


def activation_request_blob(request: LicenseActivationRequest) -> str:
    """
    Renders an activation request to its downloadable Base64+JSON blob

    Args:
        request (LicenseActivationRequest): The activation request to encode

    Returns:
        str: The Base64-encoded JSON of the request's wire document
    """
    return encode_json(LicenseActivationRequest.to_json(request))


def is_request_expired(created_at: int, ttl: int, now: int | None = None) -> bool:
    """
    Decides whether an activation request has expired (lazy TTL)

    Args:
        created_at (int): Epoch seconds at which the request was stored
        ttl (int): Time-to-live in seconds
        now (int | None): Epoch seconds to evaluate against; defaults to the current time

    Returns:
        bool: True once created_at + ttl has been reached, False while still valid
    """
    current = int(time.time()) if now is None else now

    return current >= created_at + ttl


def seconds_until_expiry(created_at: int, ttl: int, now: int | None = None) -> int:
    """
    Returns how many seconds remain before an activation request expires

    Args:
        created_at (int): Epoch seconds at which the request was stored
        ttl (int): Time-to-live in seconds
        now (int | None): Epoch seconds to evaluate against; defaults to the current time

    Returns:
        int: Seconds remaining, clamped to 0 once expired
    """
    current = int(time.time()) if now is None else now

    return max(0, created_at + ttl - current)
