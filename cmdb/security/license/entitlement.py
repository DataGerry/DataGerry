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
LicenseEntitlement model (license feature part P10)

The entitlement is the decrypted license payload: the OpenCelium
`{hmac, startDate, endDate, subId, licenseId, operationUsage, duration, type}` document. `type` is
the feature-gating tier discriminator (drives the P2 tier->feature matrix); `hmac` must equal the
activation request's hmac (the P11 binding check); startDate/endDate are epoch milliseconds with
endDate 0 meaning no expiry; operationUsage is the metered quota.

Like LicenseActivationRequest this is a lightweight data holder (not a CmdbDAO - it is not keyed by
an integer public_id). from_data / to_json move between the camelCase wire dict (keyed by
LicenseEntitlementKey, as produced by P6 decryption) and the instance; SCHEMA is the Cerberus
contract the verification chain validates against
"""
from typing import Any

from cmdb.class_schema.security.license.license_entitlement_schema import (
    get_license_entitlement_schema,
)
from cmdb.security.license.license_constants import LicenseEntitlementKey, LicenseTier
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                            LicenseEntitlement - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseEntitlement:
    """
    Decrypted license payload describing what a license grants and how it is bound

    The attribute values are the OpenCelium entitlement fields; to_json emits them under the
    camelCase wire keys
    """
    SCHEMA: dict[str, Any] = get_license_entitlement_schema()

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        hmac: str,
        license_type: str = LicenseTier.FREE.value,
        start_date: int = 0,
        end_date: int = 0,
        sub_id: str = '',
        license_id: str = '',
        operation_usage: int = 0,
        duration: int = 0,
    ) -> None:
        """
        Initialises a LicenseEntitlement

        Args:
            hmac (str): The machine-binding HMAC the license is bound to
            license_type (str): The tier discriminator (a LicenseTier value); defaults to FREE
            start_date (int): Validity start, epoch milliseconds
            end_date (int): Validity end, epoch milliseconds (0 = no expiry)
            sub_id (str): Subscription id
            license_id (str): License id
            operation_usage (int): Metered operation quota
            duration (int): License duration
        """
        self.hmac = hmac
        self.license_type = license_type
        self.start_date = start_date
        self.end_date = end_date
        self.sub_id = sub_id
        self.license_id = license_id
        self.operation_usage = operation_usage
        self.duration = duration

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "LicenseEntitlement":
        """
        Builds a LicenseEntitlement from a decrypted/stored wire dict

        Args:
            data (dict[str, Any]): The entitlement document keyed by LicenseEntitlementKey

        Returns:
            LicenseEntitlement: The reconstructed instance
        """
        return cls(
            hmac=data.get(LicenseEntitlementKey.HMAC),
            license_type=data.get(LicenseEntitlementKey.TYPE, LicenseTier.FREE.value),
            start_date=data.get(LicenseEntitlementKey.START_DATE, 0),
            end_date=data.get(LicenseEntitlementKey.END_DATE, 0),
            sub_id=data.get(LicenseEntitlementKey.SUB_ID, ''),
            license_id=data.get(LicenseEntitlementKey.LICENSE_ID, ''),
            operation_usage=data.get(LicenseEntitlementKey.OPERATION_USAGE, 0),
            duration=data.get(LicenseEntitlementKey.DURATION, 0),
        )

    @classmethod
    def to_json(cls, instance: "LicenseEntitlement") -> dict[str, Any]:
        """
        Converts a LicenseEntitlement into its camelCase wire dict

        Args:
            instance (LicenseEntitlement): The instance to serialize

        Returns:
            dict[str, Any]: The entitlement document keyed by LicenseEntitlementKey
        """
        return {
            LicenseEntitlementKey.HMAC: instance.hmac,
            LicenseEntitlementKey.START_DATE: instance.start_date,
            LicenseEntitlementKey.END_DATE: instance.end_date,
            LicenseEntitlementKey.SUB_ID: instance.sub_id,
            LicenseEntitlementKey.LICENSE_ID: instance.license_id,
            LicenseEntitlementKey.OPERATION_USAGE: instance.operation_usage,
            LicenseEntitlementKey.DURATION: instance.duration,
            LicenseEntitlementKey.TYPE: instance.license_type,
        }
