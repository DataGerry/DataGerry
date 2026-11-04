# DataGerry - OpenSource Enterprise CMDB
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
Paths and wire keys of the DataGerry Service Portal calls that are spelled through constants

The subscription license call (``POST /datagerry/subscription/License``) is the first; the older calls of
``DgServicePortalManager`` still spell their paths and keys in place
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The license of one subscription - the hosted cloud's counterpart of the on-premise license
SUBSCRIPTION_LICENSE_URL: str = "/datagerry/subscription/License"


class SubscriptionLicenseRequestKey(BaseStrEnum):
    """The keys of the subscription license request body"""
    USER_EMAIL = 'userEmail'
    DATABASE_NAME = 'databaseName'
