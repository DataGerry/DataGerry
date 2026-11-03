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
Constants for the license REST routes

Names the route paths, the ACL right strings and the response-payload keys used by the license
blueprints, so the route handlers carry no bare string literals - and the message a refused activation answers
for each verification failure
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.security.license.license_constants import LicenseVerificationStatus
from cmdb.manager.system_manager.dg_service_portal_constants import SubscriptionLicenseResponseKey
# -------------------------------------------------------------------------------------------------------------------- #

# Route paths (under the '/license' prefix)
ACTIVATION_REQUEST_ROUTE: str = '/activation-request'
CURRENT_LICENSE_ROUTE: str = '/current'
ACTIVATE_LICENSE_ROUTE: str = '/activate'
LICENSE_ENTITLEMENTS_ROUTE: str = '/entitlements'

# ACL rights
ACTIVATION_VIEW_RIGHT: str = 'base.license.activation.view'
LICENSE_VIEW_RIGHT: str = 'base.license.view'
LICENSE_EDIT_RIGHT: str = 'base.license.edit'
LICENSE_DELETE_RIGHT: str = 'base.license.delete'

# Filename of the downloadable activation-request .txt the admin hands to the license portal
ACTIVATION_REQUEST_FILENAME: str = 'datagerry_activation_request.txt'

# Query param that flips the activation-request route from a file download to a string payload
ACTIVATION_REQUEST_AS_STRING_PARAM: str = 'as_string'

# Response-payload key carrying the activation-request blob when returned as a string
ACTIVATION_REQUEST_RESPONSE_KEY: str = 'activation_request'


class LicenseUploadKey(BaseStrEnum):
    """
    Request-body keys of the license activate/upload route

    BLOB is the Base64 license blob the admin uploads (the file issued by the license generator)
    """
    BLOB = 'blob'


class CurrentLicenseResponseKey(BaseStrEnum):
    """
    Keys of the current-license route's JSON response payload

    The effective entitlement fields (keyed by LicenseEntitlementKey) are emitted flat at the top
    level; these two keys are added alongside them. IS_ACTIVE is True when a stored license verifies
    as valid; STATUS is the verification outcome (a LicenseVerificationStatus value, or null when no
    license is stored - the install runs on the free entitlement)
    """
    IS_ACTIVE = 'is_active'
    STATUS = 'status'


class LicenseEntitlementsResponseKey(BaseStrEnum):
    """
    Keys of the entitlements route's JSON response payload

    What a client needs to decide what to show, and nothing that identifies the license: no id, no
    subscription, no binding HMAC, no dates. The tier is in because it is what a screen NAMES the
    plan by - a badge reads "Business", not a feature list - while saying nothing about which
    license granted it

    Attributes:
        IS_ACTIVE: True when a stored license verifies as valid - which includes being bound to this
            machine, already started and not yet expired
        TYPE: The effective tier (a LicenseTier value). Always answered: an install with no valid
            license runs on the free entitlement, so the key reads 'free' rather than being absent
        FEATURES: The feature keys the effective entitlement unlocks; empty on the free tier
    """
    IS_ACTIVE = 'is_active'
    TYPE = 'type'
    FEATURES = 'features'


# What GET /license/current needs from the Service Portal's subscription license (hosted cloud). Only shape is
# checked: the cloud plan names are the portal's, so 'type' is not held to the on-premise tiers, and a feature the
# backend does not know is passed through. Keys the portal adds are allowed
SUBSCRIPTION_LICENSE_SCHEMA: dict[str, Any] = {
    SubscriptionLicenseResponseKey.DATABASE_NAME.value: {'type': 'string', 'required': False},
    SubscriptionLicenseResponseKey.SUB_ID.value: {'type': 'string', 'required': True},
    SubscriptionLicenseResponseKey.LICENSE_ID.value: {'type': 'string', 'required': True},
    SubscriptionLicenseResponseKey.TYPE.value: {'type': 'string', 'required': True, 'empty': False},
    SubscriptionLicenseResponseKey.FEATURES.value: {
        'type': 'list', 'required': True, 'schema': {'type': 'string', 'empty': False},
    },
    SubscriptionLicenseResponseKey.START_DATE.value: {'type': 'integer', 'required': True, 'min': 0},
    SubscriptionLicenseResponseKey.END_DATE.value: {'type': 'integer', 'required': True, 'min': 0},
}

# What GET /license/current answers in the hosted cloud when the subscription license cannot be shown: the portal
# answered an error or an unusable license (502), or could not be reached (503)
SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE: str = (
    "The Service Portal did not answer a usable license for this subscription!"
)
SERVICE_PORTAL_UNREACHABLE_MESSAGE: str = (
    "The Service Portal could not be reached to read the license of this subscription!"
)
# Why a portal answer is unusable, for the log and the raised error
SUBSCRIPTION_LICENSE_SCHEMA_REASON: str = "The subscription license does not fit its schema: {errors}"
SUBSCRIPTION_LICENSE_DATABASE_REASON: str = (
    "The subscription license names the database '{answered}', not the requested '{requested}'"
)


# Cerberus schema for the activate/upload request body
LICENSE_UPLOAD_SCHEMA: dict[str, Any] = {
    LicenseUploadKey.BLOB: {
        'type': 'string',
        'required': True,
        'empty': False,
    },
}


# What POST /license/activate answers (400) for each way a license can fail verification. The frontend shows the
# message as it is, so each one says what is wrong and what to do - the status value itself goes to the log only
LICENSE_ACTIVATION_REFUSALS: dict[LicenseVerificationStatus, str] = {
    LicenseVerificationStatus.DECRYPT_FAILED: (
        "The license file could not be read. Make sure you imported the complete license file exactly as you "
        "received it."
    ),
    LicenseVerificationStatus.SCHEMA_INVALID: (
        "The file is not a valid DataGerry license. Please check that you imported the right file."
    ),
    LicenseVerificationStatus.NO_ACTIVATION_REQUEST: (
        "This license was not issued for an activation request of this installation. Generate an activation request "
        "here and import the license that is issued for it."
    ),
    LicenseVerificationStatus.BINDING_MISMATCH: (
        "This license was issued for a different machine and cannot be used here. Generate a new activation request "
        "on this machine and import the license that is issued for it."
    ),
    LicenseVerificationStatus.ACTIVATION_REQUEST_EXPIRED: (
        "The activation request this license was issued for has expired. Generate a new activation request and "
        "import the license that is issued for it."
    ),
    LicenseVerificationStatus.NOT_YET_VALID: (
        "This license is not valid yet. Please check its start date and import it again from that day on."
    ),
    LicenseVerificationStatus.EXPIRED: (
        "This license has expired. Please renew it and import the new license file."
    ),
}
# For a failure without a message of its own (a status added later)
LICENSE_ACTIVATION_REFUSED_MESSAGE: str = "The license could not be activated. Please check the license file."
