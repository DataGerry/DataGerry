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
What the generic CmdbObject write and delete paths owe the Rack feature

A Rack is an ordinary CmdbObject, so it is created, edited and deleted through /objects - which means the
consequences for its layout and for its members' place in the location tree have to be triggered from
there. This module is the **single seam** for that: the object paths call one function per event instead of
one per rack concern, and the "is this even a Rack?" question is answered once rather than per hook.

Also the one place where the two Rack side effects of an object write meet:

  - **the height changed** -> mounts that no longer fit are unplaced (cmdb.framework.rack.height_change)
  - **the location changed** -> the members follow the rack, or leave the tree with it
    (rack_location_helper)

Deleting is the mirror image, and the ORDER matters: the members' location nodes are removed while the
mount rows still exist, because the mount rows are what says who the members are
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import LocationsManager, ObjectsManager, TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.models.user_model import CmdbUser

from cmdb.database.predefined_data.predefined_data_constants import LocationKey

from cmdb.framework.rack.cascade import delete_rack_memberships
from cmdb.framework.rack.enforcement import is_rack_object
from cmdb.framework.rack.height_change import handle_rack_height_change

from cmdb.interface.rest_api.routes.rack_routes.rack_location_helper import (
    detach_all_member_locations,
    reconcile_member_locations,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def handle_rack_object_updated(
        request_user: CmdbUser,
        object_id: int,
        stored_object: dict[str, Any],
        previous_object: dict[str, Any] | None,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        locations_manager: LocationsManager | None = None) -> None:
    """
    Applies both Rack consequences of a CmdbObject having been written

    Runs post-write, and after the object's own location has been mirrored: the height rule measures the
    mounts against the height that is now stored, and the location reconcile reads the rack's node as it now
    is. A no-op for anything that is not a Rack, at the cost of one type lookup

    Both steps are safe to reach twice, so a retried request cannot compound their effects

    Args:
        request_user (CmdbUser): The user performing the write
        object_id (int): public_id of the CmdbObject that was written
        stored_object (dict[str, Any]): The object as persisted
        previous_object (dict[str, Any] | None): The pre-edit document; None on insert
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        locations_manager (LocationsManager | None): Optional pre-resolved CmdbLocations manager
    """
    if not is_rack_object(types_manager, stored_object):
        return

    rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
        ManagerType.RACK_MOUNTS, request_user)

    handle_rack_height_change(
        types_manager, rack_mounts_manager, object_id, stored_object, previous_object,
    )

    if locations_manager is None:
        locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    reconcile_member_locations(
        object_id, request_user, objects_manager, locations_manager, rack_mounts_manager,
    )


def handle_object_deleted(
        request_user: CmdbUser,
        deleted_object: dict[str, Any],
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        locations_manager: LocationsManager | None = None) -> None:
    """
    Cleans up the Rack state a deleted CmdbObject leaves behind, in either role

    A deleted **Rack** takes its whole layout with it: its members leave the location tree and every
    membership row goes, while the mounted objects themselves survive untouched. A deleted **member** loses
    only its own membership - its own location node is already removed by the generic object-delete path.

    The order is deliberate: the location nodes are removed BEFORE the mount rows, because the mount rows
    are the only record of who the members are. Doing it the other way round would leave every member
    stranded in the tree under a rack that no longer exists

    Args:
        request_user (CmdbUser): The user performing the deletion
        deleted_object (dict[str, Any]): The CmdbObject document being deleted
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        locations_manager (LocationsManager | None): Optional pre-resolved CmdbLocations manager
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return

    rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
        ManagerType.RACK_MOUNTS, request_user)

    if is_rack_object(types_manager, deleted_object):
        if locations_manager is None:
            locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        detach_all_member_locations(
            object_id, request_user, objects_manager, locations_manager, rack_mounts_manager,
        )

    delete_rack_memberships(types_manager, rack_mounts_manager, deleted_object)


def guard_member_location_change(
        request_user: CmdbUser,
        object_id: int,
        requested_parent: int | None,
        locations_manager: LocationsManager) -> None:
    """
    Refuses moving a rack member's location away from the rack it is mounted in

    The counterpart of the ``managed_by`` guard, for the other branch: a member whose type HAS a location
    field can be edited in the ordinary object form, so without this a user could point it anywhere and the
    tree would disagree with the rack until something re-reconciled it. The rack owns where its members sit,
    so the change is refused with the rack named - the way to move the device is to take it out of the rack

    A no-op for an object that is not a rack member, and for a member being pointed at the rack it is
    already in (which is what the rack's own mirroring does)

    Args:
        request_user (CmdbUser): The user performing the write
        object_id (int): public_id of the CmdbObject being written
        requested_parent (int | None): The location parent the payload asks for
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 400 when the object is a rack member and the change would move it out of the rack
    """
    rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
        ManagerType.RACK_MOUNTS, request_user)

    mount: dict[str, Any] | None = rack_mounts_manager.get_mount_of_object(object_id)

    if not mount:
        return

    rack_id: int = mount[RackMountKey.RACK_ID.value]
    rack_node: dict[str, Any] | None = locations_manager.get_location_for_object(rack_id)
    rack_node_id: int | None = rack_node[LocationKey.PUBLIC_ID.value] if rack_node else None

    if requested_parent == rack_node_id:
        return

    abort(400, f"The Location of this object is managed by Rack ID:{rack_id} - remove it from the Rack "
               f"before placing it somewhere else!")
