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
LicenseActivationRequest model (license feature part P8)

The activation request is the offline blob an admin downloads to hand to the license generator:
the OpenCelium `{id, hmac, ttl, status, machineUuid, macAddress, systemUUID, computerName}`
document. It binds a future license to this machine - the `hmac` is the machine-binding HMAC over
the four fingerprint fields plus the id (P4), and a minted license's `hmac` must equal it (the P11
binding check).

This is a lightweight data holder (not a CmdbDAO: it is keyed by the string UUID `id`, not an
integer public_id), mirroring CmdbAuthSettings. from_data / to_json move between the camelCase
wire dict (keyed by ActivationRequestKey) and the instance; SCHEMA is the Cerberus contract a
manager validates against before persisting
"""
from typing import Any

from cmdb.class_schema.security.license.license_activation_request_schema import (
    get_license_activation_request_schema,
)
from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                         LicenseActivationRequest - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseActivationRequest:
    """
    Offline activation request binding a future license to one machine

    The attribute values are the OpenCelium activation-request fields; to_json emits them under the
    camelCase wire keys for the downloadable blob and Mongo storage
    """
    SCHEMA: dict[str, Any] = get_license_activation_request_schema()

    def __init__(
        self,
        request_id: str,
        hmac: str,
        ttl: int,
        fingerprint: dict[str, str],
        status: str = ActivationRequestStatus.PENDING.value,
    ) -> None:
        """
        Initialises a LicenseActivationRequest

        Args:
            request_id (str): The OpenCelium request id (UUID string)
            hmac (str): The machine-binding HMAC (Base64)
            ttl (int): Time-to-live in seconds for lazy expiry
            fingerprint (dict[str, str]): The machine fingerprint keyed by the ActivationRequestKey
                machine fields (as produced by machine_fingerprint.get_machine_fingerprint); missing
                fields default to an empty string
            status (str): Lifecycle status (an ActivationRequestStatus value); defaults to PENDING
        """
        self.request_id = request_id
        self.hmac = hmac
        self.ttl = ttl
        self.status = status
        self.machine_uuid = fingerprint.get(ActivationRequestKey.MACHINE_UUID, '')
        self.mac_address = fingerprint.get(ActivationRequestKey.MAC_ADDRESS, '')
        self.system_uuid = fingerprint.get(ActivationRequestKey.SYSTEM_UUID, '')
        self.computer_name = fingerprint.get(ActivationRequestKey.COMPUTER_NAME, '')

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "LicenseActivationRequest":
        """
        Builds a LicenseActivationRequest from a wire/stored dict

        Args:
            data (dict[str, Any]): The activation-request document keyed by ActivationRequestKey

        Returns:
            LicenseActivationRequest: The reconstructed instance
        """
        fingerprint = {
            ActivationRequestKey.MACHINE_UUID: data.get(ActivationRequestKey.MACHINE_UUID, ''),
            ActivationRequestKey.MAC_ADDRESS: data.get(ActivationRequestKey.MAC_ADDRESS, ''),
            ActivationRequestKey.SYSTEM_UUID: data.get(ActivationRequestKey.SYSTEM_UUID, ''),
            ActivationRequestKey.COMPUTER_NAME: data.get(ActivationRequestKey.COMPUTER_NAME, ''),
        }

        return cls(
            request_id=data.get(ActivationRequestKey.ID),
            hmac=data.get(ActivationRequestKey.HMAC),
            ttl=data.get(ActivationRequestKey.TTL),
            fingerprint=fingerprint,
            status=data.get(ActivationRequestKey.STATUS, ActivationRequestStatus.PENDING.value),
        )

    @classmethod
    def to_json(cls, instance: "LicenseActivationRequest") -> dict[str, Any]:
        """
        Converts a LicenseActivationRequest into its full camelCase document

        This is the storage representation (it carries the lifecycle fields ttl and status); the
        downloadable request file is the trimmed projection produced by to_blob_dict

        Args:
            instance (LicenseActivationRequest): The instance to serialize

        Returns:
            dict[str, Any]: The activation-request document keyed by ActivationRequestKey
        """
        return {
            ActivationRequestKey.ID: instance.request_id,
            ActivationRequestKey.HMAC: instance.hmac,
            ActivationRequestKey.TTL: instance.ttl,
            ActivationRequestKey.STATUS: instance.status,
            ActivationRequestKey.MACHINE_UUID: instance.machine_uuid,
            ActivationRequestKey.MAC_ADDRESS: instance.mac_address,
            ActivationRequestKey.SYSTEM_UUID: instance.system_uuid,
            ActivationRequestKey.COMPUTER_NAME: instance.computer_name,
        }

    @classmethod
    def to_blob_dict(cls, instance: "LicenseActivationRequest") -> dict[str, Any]:
        """
        Converts a LicenseActivationRequest into the downloadable request-file document

        Emits only the fields the license portal needs: the request id, the machine-binding HMAC
        and the four machine fingerprint fields. The lifecycle fields (ttl, status) and the
        server-side created_at are storage-only and deliberately excluded from the file

        Args:
            instance (LicenseActivationRequest): The instance to serialize

        Returns:
            dict[str, Any]: The request-file document keyed by ActivationRequestKey (6 fields)
        """
        return {
            ActivationRequestKey.ID: instance.request_id,
            ActivationRequestKey.HMAC: instance.hmac,
            ActivationRequestKey.MACHINE_UUID: instance.machine_uuid,
            ActivationRequestKey.MAC_ADDRESS: instance.mac_address,
            ActivationRequestKey.SYSTEM_UUID: instance.system_uuid,
            ActivationRequestKey.COMPUTER_NAME: instance.computer_name,
        }
