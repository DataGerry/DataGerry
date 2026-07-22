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
HMAC machine-binding primitive for the license feature (license feature part P4)

Reproduces OpenCelium's HMAC binding byte-for-byte: HMAC-SHA256 over a message built by
concatenating the request id followed by the four machine fingerprint fields (id FIRST, no
separators), keyed by the shipped HMAC secret, with the raw 32-byte digest Base64-encoded. The
id-first order mirrors OpenCelium's ActivationRequestServiceImp.generateActivReq, which signs
`HmacUtility.encode(ar.getId() + MachineUtility.getStringForHmacEncode())`.

The same compute_hmac() primitive will later seal the metering counter (a different message), so it
takes the message and secret as arguments; machine_binding_hmac() assembles the binding message in
the fixed field order. constant_time_equals() is the timing-safe comparison used to verify a
candidate digest against the expected one
"""
import base64
import hashlib
import hmac

from cmdb.security.license.license_constants import ActivationRequestKey, LICENSE_HMAC_SECRET
# -------------------------------------------------------------------------------------------------------------------- #

# Order the four machine fingerprint fields are concatenated in before the (always last) request id
_MACHINE_FIELD_ORDER: tuple[ActivationRequestKey, ...] = (
    ActivationRequestKey.MACHINE_UUID,
    ActivationRequestKey.MAC_ADDRESS,
    ActivationRequestKey.SYSTEM_UUID,
    ActivationRequestKey.COMPUTER_NAME,
)


def compute_hmac(message: str, secret: str = LICENSE_HMAC_SECRET) -> str:
    """
    Computes Base64(HMAC-SHA256(secret, message))

    Both the secret and the message are encoded as UTF-8 before hashing, matching how OpenCelium
    treats its string secret and message

    Args:
        message (str): The message to authenticate
        secret (str): The HMAC key; defaults to the shipped LICENSE_HMAC_SECRET

    Returns:
        str: The Base64-encoded raw 32-byte digest
    """
    digest = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()

    return base64.b64encode(digest).decode('ascii')


def machine_binding_hmac(fingerprint: dict[str, str], request_id: str, secret: str = LICENSE_HMAC_SECRET) -> str:
    """
    Computes the machine-binding HMAC for an activation request

    The signed message is the request id FIRST, followed by the four fingerprint fields
    (machineUuid, macAddress, systemUUID, computerName) concatenated with no separators - matching
    OpenCelium's `HmacUtility.encode(ar.getId() + MachineUtility.getStringForHmacEncode())`

    Args:
        fingerprint (dict[str, str]): A machine fingerprint keyed by the ActivationRequestKey
            machine fields (as produced by machine_fingerprint.get_machine_fingerprint)
        request_id (str): The activation request id, prepended first
        secret (str): The HMAC key; defaults to the shipped LICENSE_HMAC_SECRET

    Returns:
        str: The Base64-encoded binding HMAC
    """
    message = request_id + ''.join(fingerprint[field] for field in _MACHINE_FIELD_ORDER)

    return compute_hmac(message, secret)


def constant_time_equals(expected: str, candidate: str) -> bool:
    """
    Compares two HMAC strings in constant time

    Wraps hmac.compare_digest so a binding/tamper-seal check does not leak how many leading
    characters matched via its timing

    Args:
        expected (str): The reference HMAC
        candidate (str): The HMAC to compare against it

    Returns:
        bool: True if the two strings are equal, False otherwise
    """
    return hmac.compare_digest(expected, candidate)
