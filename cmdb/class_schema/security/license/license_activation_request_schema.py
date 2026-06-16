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
Validation schema for LicenseActivationRequest

A LicenseActivationRequest is the offline activation blob an admin downloads: the OpenCelium
`{id, hmac, ttl, status, machineUuid, macAddress, systemUUID, computerName}` document. The keys are
the camelCase wire-format names (named by ActivationRequestKey) so the stored document matches the
blob byte-for-byte.

This module is the single source of the document's Cerberus validation schema, consumed as
LicenseActivationRequest.SCHEMA.
"""
from typing import Any

from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
# -------------------------------------------------------------------------------------------------------------------- #


def get_license_activation_request_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a LicenseActivationRequest document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as LicenseActivationRequest.SCHEMA
    """
    return {
        ActivationRequestKey.ID: {  # OpenCelium request id (UUID string); the document identifier
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ActivationRequestKey.HMAC: {  # Machine-binding HMAC (Base64) over the machine fields + id
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ActivationRequestKey.TTL: {  # Time-to-live in seconds, used for lazy expiry of the request
            'type': 'integer',
            'required': True,
            'min': 1,
        },
        ActivationRequestKey.STATUS: {  # Lifecycle status (an ActivationRequestStatus value)
            'type': 'string',
            'required': True,
            'allowed': [status.value for status in ActivationRequestStatus],
        },
        ActivationRequestKey.MACHINE_UUID: {  # Persistent machine id ('0' when unresolved)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ActivationRequestKey.MAC_ADDRESS: {  # Primary NIC MAC address ('0' when unresolved)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ActivationRequestKey.SYSTEM_UUID: {  # Firmware/system UUID ('0' when unresolved)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ActivationRequestKey.COMPUTER_NAME: {  # Host/computer name ('0' when unresolved)
            'type': 'string',
            'required': True,
            'empty': False,
        },
    }
