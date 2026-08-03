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
Helper functions for the OpenCelium connector REST routes

These consolidate the cache-first access checks (cache preferred, DG Service Portal fallback) that the
cloud-mode connector handlers each performed inline. A resolved cached-user dict may be passed in to
avoid re-reading (and potentially re-seeding) the cache within a single request.
"""
from typing import Any

from cmdb.manager import DgServicePortalManager, CachedUserManager

from cmdb.open_celium import CachedOcIdType

from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #


def connector_in_subscription(
    request_user: CmdbUser,
    connector_id: int,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
    cached_user: dict[str, Any] | None = None,
) -> bool:
    """
    Checks whether an OpenCelium connector belongs to the requesting user's subscription

    Prefers the local user cache and falls back to the DG Service Portal only when the user is not
    cached. Pass an already-resolved `cached_user` to reuse it instead of re-reading the cache.

    Args:
        request_user (CmdbUser): The user making the request (its email + database scope the check)
        connector_id (int): The OpenCelium connector id to validate
        cached_user_manager (CachedUserManager): Manager used to read the cached user / check ids
        dg_sp_manager (DgServicePortalManager): Manager used for the Service Portal fallback
        cached_user (dict[str, Any] | None): An already-resolved cached user, or None to resolve it here

    Returns:
        bool: True if the connector belongs to the user's subscription, otherwise False
    """
    if cached_user is None:
        cached_user = cached_user_manager.get_cached_user(request_user.email)

    if cached_user:
        return cached_user_manager.oc_id_exists(
            cached_user,
            request_user.database,
            CachedOcIdType.CONNECTORS,
            connector_id,
        )

    return dg_sp_manager.check_connector_in_sub(
        connector_id,
        request_user.email,
        request_user.database,
    )


def validate_master_password(
    request_user: CmdbUser,
    provided_pw: str,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
    cached_user: dict[str, Any] | None = None,
) -> bool:
    """
    Validates the OpenCelium master password against the cache (preferred) or the Service Portal

    Pass an already-resolved `cached_user` to reuse it instead of re-reading the cache.

    Args:
        request_user (CmdbUser): The user making the request
        provided_pw (str): The master password to validate
        cached_user_manager (CachedUserManager): Manager used for the cached password check
        dg_sp_manager (DgServicePortalManager): Manager used for the Service Portal fallback
        cached_user (dict[str, Any] | None): An already-resolved cached user, or None to resolve it here

    Returns:
        bool: True if the master password is valid for the user's subscription, otherwise False
    """
    if cached_user is None:
        cached_user = cached_user_manager.get_cached_user(request_user.email)

    if cached_user:
        return cached_user_manager.check_cached_master_password(
            cached_user,
            request_user.database,
            provided_pw,
        )

    return dg_sp_manager.check_master_pw(
        provided_pw,
        request_user.email,
        request_user.database,
    )


def get_accessible_connector_ids(
    request_user: CmdbUser,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
) -> list[int] | None:
    """
    Returns the OpenCelium connector ids visible to the requesting user (cloud mode)

    Reads the ids from the user's cache first and falls back to the DG Service Portal on a cache miss.

    Args:
        request_user (CmdbUser): The user whose accessible connector ids are resolved
        cached_user_manager (CachedUserManager): Manager used to read the cached user / ids
        dg_sp_manager (DgServicePortalManager): Manager used for the Service Portal fallback

    Returns:
        list[int] | None: The accessible connector ids, or None/empty when the user has none
    """
    cached_user = cached_user_manager.get_cached_user(request_user.email)

    if cached_user:
        return cached_user_manager.get_oc_ids(
            cached_user,
            request_user.database,
            CachedOcIdType.CONNECTORS,
        ) or []

    return dg_sp_manager.get_connector_ids(request_user.email, request_user.database)
