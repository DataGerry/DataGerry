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
What a reader of the location tree may see - the read side of the location routes

Every location read is narrowed to the reader: a node is as visible as its object, and a hidden node hides its whole
branch (``location_visibility``). The Types the reader's group may not READ are resolved once per request
(``read_denied_type_ids``); the level reads leave their nodes out through the manager's ``denied_type_ids``, and a
read that names one node is refused with a 403 when the node or any node above it is hidden
(``abort_unless_location_readable``) - the answer ``GET /objects/<id>`` gives for an unreadable object
"""
from flask import abort

from cmdb.manager import LocationsManager
from cmdb.models.location_model import chain_is_hidden
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LOCATION_NOT_READABLE_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['abort_unless_location_readable', 'read_denied_type_ids']


def read_denied_type_ids(request_user: CmdbUser) -> list[int]:
    """
    Answers the Types whose nodes the reader may not see - those its group may not READ

    One projected read of the Types

    Args:
        request_user (CmdbUser): The reader

    Returns:
        list[int]: The denied Types; empty when the group may read everything
    """
    return resolve_denied_type_ids(request_user, AccessControlPermission.READ)


def abort_unless_location_readable(
        locations_manager: LocationsManager,
        public_id: int | None,
        denied_type_ids: list[int]) -> None:
    """
    Refuses a read that names a node the reader may not see

    Costs nothing when nothing is denied or the node is the synthetic root; otherwise one read of the node's chain.
    A node that does not exist passes - the route answers that case as it always did

    Args:
        locations_manager (LocationsManager): Reads the node's chain
        public_id (int | None): The node the read names; None (a node without one) passes
        denied_type_ids (list[int]): The reader's denied Types

    Raises:
        HTTPException: 403 when the node, or a node above it, holds an object of a denied Type
    """
    if not denied_type_ids or public_id is None or public_id == RootLocationDefault.PUBLIC_ID:
        return

    if chain_is_hidden(locations_manager.get_location_chain(public_id), denied_type_ids):
        abort(403, LOCATION_NOT_READABLE_MSG.format(public_id=public_id))
