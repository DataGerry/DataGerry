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
The cloud user cache's collection, indexes and date field - CmdbCachedUser is a namespace, not a model

A cached user is the DataGerry Service Portal's answer to a login, stored as it is, plus two keys DataGerry adds on
write:

* from the portal - ``email``, ``user_name``, ``password`` (replaced by its HMAC before it is stored), ``api_level`` and
  ``subscriptions``: one entry per subscription with ``database``, ``api_level``, ``config_item_limit`` and, where the
  portal has them, ``api_key``, ``is_valid``, ``opencelium`` (the tenant's ``connectors`` / ``connections`` /
  ``schedules`` id lists) and ``masterPassword`` (``CachedSubscriptionKey``)
* from DataGerry - ``public_id`` and ``creation_time``

``email`` is always present and unique: every write stores the portal's address, and every read looks the cache up by
it. The portal owns the rest of the shape and may change it, so nothing here parses the document: ``CachedUserManager``
reads and writes it as a dict, and the class supplies only what that needs - the collection name, the indexes the
cache database is built with, and the date field the generic insert turns into a real date (the TTL index only works
on one). There is no ``from_data`` / ``to_json``: the CmdbDAO base raises for a model that declares neither, which is
the answer a caller trying to build one should get
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.cached_user_model.cached_user_constants import CACHE_TTL_SECONDS, CachedUserKey
# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbCachedUser - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbCachedUser(CmdbDAO):
    """
    The cached cloud user's collection, indexes and date field (see the module docstring for the document)

    The entries live in the shared cache database and expire through the ``creation_time`` TTL index after
    CACHE_TTL_SECONDS; nothing in DataGerry deletes them on age. The cache is keyed by EMAIL, not by public_id: every
    read looks a user up by email, and the unique email index is what keeps one entry per user

    Extends: CmdbDAO - for the GenericManager type parameter; never instantiated

    Attributes:
        COLLECTION: The cache collection, in DG_CACHE_DB
        DATE_FIELDS: Turned into real dates on insert (``GenericManager._normalize_dates``) - the TTL index needs one
        INDEX_KEYS: The unique email index and the creation_time TTL index
    """
    COLLECTION = 'cache.users'
    DATE_FIELDS: tuple[str, ...] = (CachedUserKey.CREATION_TIME,)
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(CachedUserKey.EMAIL.value, CmdbDAO.DAO_ASCENDING)],
            'name': CachedUserKey.EMAIL.value,
            'unique': True,
        },
        # The TTL index: MongoDB removes an entry CACHE_TTL_SECONDS after its creation_time, so nothing
        # in DataGerry has to expire the cache. Every write refreshes creation_time and restarts it
        {
            'keys': [(CachedUserKey.CREATION_TIME.value, CmdbDAO.DAO_ASCENDING)],
            'name': CachedUserKey.CREATION_TIME.value,
            'expireAfterSeconds': CACHE_TTL_SECONDS,
        },
    ]
