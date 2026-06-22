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
Validation schema for LicenseEntitlement

A LicenseEntitlement is the decrypted license payload: the OpenCelium
`{hmac, startDate, endDate, subId, licenseId, type}` document plus a
`features` list. The keys are the camelCase wire-format names (named by LicenseEntitlementKey) and
`type` is constrained to the known license tiers. `features` is a required list of non-empty
strings (it may be empty for the free tier); its items are NOT constrained to the known feature
keys, so a portal can ship a feature the backend does not yet recognise and the backend ignores it.

This module is the single source of the document's Cerberus validation schema, consumed as
LicenseEntitlement.SCHEMA.
"""
from typing import Any

from cmdb.security.license.license_constants import LicenseEntitlementKey, LicenseTier
# -------------------------------------------------------------------------------------------------------------------- #


def get_license_entitlement_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a LicenseEntitlement document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as LicenseEntitlement.SCHEMA
    """
    return {
        LicenseEntitlementKey.HMAC: {  # Machine-binding HMAC; must equal the activation request's hmac
            'type': 'string',
            'required': True,
            'empty': False,
        },
        LicenseEntitlementKey.START_DATE: {  # Validity start, epoch milliseconds
            'type': 'integer',
            'required': True,
            'min': 0,
        },
        LicenseEntitlementKey.END_DATE: {  # Validity end, epoch milliseconds (0 = no expiry)
            'type': 'integer',
            'required': True,
            'min': 0,
        },
        LicenseEntitlementKey.SUB_ID: {  # Subscription id (may be empty for the free tier)
            'type': 'string',
            'required': True,
        },
        LicenseEntitlementKey.LICENSE_ID: {  # License id (may be empty for the free tier)
            'type': 'string',
            'required': True,
        },
        LicenseEntitlementKey.TYPE: {  # Display-only tier label (a LicenseTier value); does not drive gating
            'type': 'string',
            'required': True,
            'allowed': [tier.value for tier in LicenseTier],
        },
        LicenseEntitlementKey.FEATURES: {  # Unlocked feature keys; sole gating source, may be empty, unknowns ignored
            'type': 'list',
            'required': True,
            'schema': {'type': 'string', 'empty': False},
        },
    }
