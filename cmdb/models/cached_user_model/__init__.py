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
Provides all CmdbCachedUser related models

A CmdbCachedUser is a cloud user and their subscriptions, cached from the DataGerry Service Portal in
the shared cache database (collection ``cache.users``) so that not every request has to ask the
portal again. The entries expire on their own through a TTL index - see
``cached_user_constants.CACHE_TTL_SECONDS``
"""
from .cached_user_constants import CACHE_TTL_SECONDS, CachedUserKey
from .cmdb_cached_user import CmdbCachedUser
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CACHE_TTL_SECONDS',
    'CachedUserKey',
    'CmdbCachedUser',
]
