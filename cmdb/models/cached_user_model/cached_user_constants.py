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
Lifetime and document keys of a cached cloud user (the portal's answer to a login, plus two keys DataGerry adds)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

CACHE_TTL_SECONDS: int = 3600
"""
How long a cached user stays valid (one hour)

This is the ``expireAfterSeconds`` of the ``creation_time`` index, so MongoDB - not DataGerry -
removes an expired entry. Every write refreshes ``creation_time``, which restarts the hour
"""


class CachedUserKey(BaseStrEnum):
    """
    Top-level keys of a cached-user document

    A cached user is the DataGerry Service Portal's answer to a login, stored as it is, plus a CREATION_TIME and a
    PUBLIC_ID added on write (see ``cmdb_cached_user``). The keys of one subscription entry are
    ``CachedSubscriptionKey``
    """
    PUBLIC_ID = 'public_id'
    USER_NAME = 'user_name'
    PASSWORD = 'password'
    EMAIL = 'email'
    API_LEVEL = 'api_level'
    SUBSCRIPTIONS = 'subscriptions'
    CREATION_TIME = 'creation_time'


class CachedSubscriptionKey(BaseStrEnum):
    """
    Keys of one entry of a cached user's SUBSCRIPTIONS, as the Service Portal sends them

    DATABASE, API_LEVEL and CONFIG_ITEM_LIMIT are always present; API_KEY is stamped on by an API login (and stripped
    before a validated entry is handed out); IS_VALID, OPENCELIUM and MASTER_PASSWORD are present where the portal has
    them. OPENCELIUM holds the tenant's OpenCelium id lists under ``CachedOcIdListKey``
    """
    DATABASE = 'database'
    API_LEVEL = 'api_level'
    CONFIG_ITEM_LIMIT = 'config_item_limit'
    API_KEY = 'api_key'
    IS_VALID = 'is_valid'
    OPENCELIUM = 'opencelium'
    MASTER_PASSWORD = 'masterPassword'


class CachedOcIdListKey(BaseStrEnum):
    """
    Keys of a subscription's OPENCELIUM block: the tenant's OpenCelium ids per kind, as strings

    Note the scheduler list is spelled 'schedules' by the portal, not 'schedulers'
    """
    CONNECTORS = 'connectors'
    CONNECTIONS = 'connections'
    SCHEDULES = 'schedules'
