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
Lifetime and document keys of a CmdbCachedUser
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
    Keys of a cached-user document

    A cached user is the DataGerry Service Portal's answer to a login, stored verbatim plus a
    CREATION_TIME (added on write) and a PUBLIC_ID (assigned on write). The portal payload itself
    carries EMAIL, USER_NAME, PASSWORD and SUBSCRIPTIONS; ACTIVE is part of the model but is never
    written by any current path

    Only the TOP-LEVEL keys are named here. The keys inside a subscription (database, api_level,
    api_key, is_valid, opencelium, masterPassword, ...) are deliberately left out: what a subscription
    document really contains is an open question - the Cerberus schema, the Service Portal payload and
    the manager's readers currently disagree - and naming half of them would fix the disagreement in
    place
    """
    PUBLIC_ID = 'public_id'
    USER_NAME = 'user_name'
    PASSWORD = 'password'
    EMAIL = 'email'
    ACTIVE = 'active'
    SUBSCRIPTIONS = 'subscriptions'
    CREATION_TIME = 'creation_time'
