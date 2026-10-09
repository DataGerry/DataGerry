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
from flask import current_app

from cmdb.manager import DgServicePortalManager, CachedUserManager, OcConnectionManager
from cmdb.manager.manager_provider_model import ManagerProvider

from cmdb.open_celium import CachedOcIdType

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.open_celium_routes.oc_subscription_helper import oc_id_in_subscription
# -------------------------------------------------------------------------------------------------------------------- #

def build_connection_manager(request_user: CmdbUser) -> OcConnectionManager:
    """
    Builds the OcConnectionManager for the requesting user

    Every connection route and the Automation create and delete need the same two arguments - the process-wide
    database manager and the caller's database - so the construction lives here instead of in every route

    Args:
        request_user (CmdbUser): The user making the request; its database scopes the manager

    Returns:
        OcConnectionManager: The manager to talk to OpenCelium with
    """
    return OcConnectionManager(current_app.database_manager, ManagerProvider.tenant_database(request_user))



def connection_in_subscription(
    request_user: CmdbUser,
    connection_id: int,
    cached_user_manager: CachedUserManager,
    dg_sp_manager: DgServicePortalManager,
) -> bool:
    """
    Checks whether an OpenCelium connection belongs to the requesting user's subscription

    The connection case of ``oc_id_in_subscription``: the user's cache entry is read (seeded from the DG Service
    Portal once on a miss) and the id looked up in it. Used by the cloud-mode connection read/update routes to
    reject connections outside the caller's subscription.

    Args:
        request_user (CmdbUser): The user making the request (its email + database scope the check)
        connection_id (int): The OpenCelium connection id to validate
        cached_user_manager (CachedUserManager): The user cache
        dg_sp_manager (DgServicePortalManager): The portal client asked on a cache miss

    Returns:
        bool: True if the connection belongs to the user's subscription, otherwise False
    """
    return oc_id_in_subscription(
        request_user, CachedOcIdType.CONNECTIONS, connection_id, cached_user_manager, dg_sp_manager,
    )
