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
blueprints, so the route handlers carry no bare string literals
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Route paths (under the '/license' prefix)
ACTIVATION_REQUEST_ROUTE: str = '/activation-request'
CURRENT_LICENSE_ROUTE: str = '/current'
ACTIVATE_LICENSE_ROUTE: str = '/activate'

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


# Cerberus schema for the activate/upload request body
LICENSE_UPLOAD_SCHEMA: dict = {
    LicenseUploadKey.BLOB: {
        'type': 'string',
        'required': True,
        'empty': False,
    },
}
