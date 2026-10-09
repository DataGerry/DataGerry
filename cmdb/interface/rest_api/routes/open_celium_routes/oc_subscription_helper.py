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
The cloud-mode subscription checks shared by the OpenCelium routes

A cloud user's OpenCelium ids (connectors, connections, schedulers) are listed in their entry of the user cache
(``CachedUserManager``, in ``DG_CACHE_DB``). The cache is read first; on a miss it is seeded from the DataGerry Service
Portal once (``read_or_seed_cached_user``) - the one place that orchestrates the two managers, which is why it lives
here and not in either of them.

``oc_id_in_subscription`` is the one id check behind ``connector_in_subscription``, ``connection_in_subscription`` and
``assert_scheduler_access``: the id is in the subscription when the user's cached entry lists it. A user the portal does
not know either has no subscription to hold the id, so the answer is False without asking the portal a second time.
"""
from typing import Any

from cmdb.manager import DgServicePortalManager, CachedUserManager

from cmdb.open_celium import CachedOcIdType

from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #


def read_or_seed_cached_user(
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
    email: str,
) -> dict[str, Any] | None:
    """
    Reads a cloud user's cache entry, seeding it from the DataGerry Service Portal on a miss

    A hit costs no portal call. On a miss the portal's user data is inserted into the cache and read back, so the
    stored document (with its id and creation time) is returned and the next request is served from the cache

    Args:
        cached_user_manager (CachedUserManager): The user cache
        dg_sp_manager (DgServicePortalManager): The portal client asked on a miss
        email (str): The user's email

    Raises:
        DgServicePortalGetError: When the portal answers the user lookup with an error status - an unknown email
            among them, if that is how the portal reports one

    Returns:
        dict[str, Any] | None: The cached entry, or None when the portal returns no user data either
    """
    cached_user: dict[str, Any] | None = cached_user_manager.get_cached_user(email)

    if cached_user:
        return cached_user

    user_data: dict[str, Any] | None = dg_sp_manager.get_dg_sp_user_data(email)

    if not user_data:
        return None

    cached_user_manager.insert_cached_user(user_data)

    return cached_user_manager.get_cached_user(email)


def oc_id_in_subscription(
    request_user: CmdbUser,
    id_type: CachedOcIdType,
    oc_id: int,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
    cached_user: dict[str, Any] | None = None,
) -> bool:
    """
    Checks whether an OpenCelium id belongs to the requesting user's subscription

    Reads (or seeds) the user's cache entry once and looks the id up in the subscription of the user's database.
    Pass an already-resolved ``cached_user`` to reuse it within a request

    Args:
        request_user (CmdbUser): The user making the request; its email and database scope the check
        id_type (CachedOcIdType): Which id list to look in
        oc_id (int): The OpenCelium id to validate
        cached_user_manager (CachedUserManager): The user cache
        dg_sp_manager (DgServicePortalManager): The portal client asked on a cache miss
        cached_user (dict[str, Any] | None): An already-resolved cache entry, or None to resolve it here

    Returns:
        bool: True if the id is listed in the user's subscription; False otherwise, and for a user neither the
            cache nor the portal knows
    """
    if cached_user is None:
        cached_user = read_or_seed_cached_user(cached_user_manager, dg_sp_manager, request_user.email)

    if not cached_user:
        return False

    return cached_user_manager.oc_id_exists(cached_user, request_user.database, id_type, oc_id)
