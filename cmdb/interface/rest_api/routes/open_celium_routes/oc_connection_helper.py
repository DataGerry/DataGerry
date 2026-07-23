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
Helper functions for the OpenCelium connection REST routes
"""
from cmdb.manager import DgServicePortalManager, CachedUserManager

from cmdb.open_celium import CachedOcIdType

from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #


def connection_in_subscription(
    request_user: CmdbUser,
    connection_id: int,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
) -> bool:
    """
    Checks whether an OpenCelium connection belongs to the requesting user's subscription

    Prefers the local user cache (avoiding a Service Portal round-trip) and falls back to the DG
    Service Portal only when the user is not cached. Used by the cloud-mode connection read/update
    routes to reject connections outside the caller's subscription.

    Args:
        request_user (CmdbUser): The user making the request (its email + database scope the check)
        connection_id (int): The OpenCelium connection id to validate
        cached_user_manager (CachedUserManager): Manager used to read the cached user
        dg_sp_manager (DgServicePortalManager): Manager used for the Service Portal fallback

    Returns:
        bool: True if the connection belongs to the user's subscription, otherwise False
    """
    cached_user = cached_user_manager.get_cached_user(request_user.email)

    if cached_user:
        return cached_user_manager.oc_id_exists(
            cached_user,
            request_user.database,
            CachedOcIdType.CONNECTIONS,
            connection_id,
        )

    return dg_sp_manager.check_connection_in_sub(
        connection_id,
        request_user.email,
        request_user.database,
    )
