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
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import LocationsManager, ObjectsManager, TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.user_model import CmdbUser

from cmdb.models.location_model.location_constants import LocationKey

from cmdb.security.license.license_constants import LicenseFeature

from cmdb.framework.rack.cascade import delete_rack_memberships
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.framework.rack.enforcement import is_rack_object
from cmdb.framework.rack.height_change import handle_rack_height_change

from cmdb.interface.rest_api.routes.rack_routes.rack_location_helper import (
    detach_all_member_locations,
    reconcile_member_locations,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import (
    assign_position_if_needed,
    build_mount_candidate,
    member_object_blocker,
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


def get_rack_node_id(rack_id: int, locations_manager: LocationsManager) -> int | None:
    """
    Returns the location node a Rack itself occupies

    Args:
        rack_id (int): public_id of the Rack CmdbObject
        locations_manager (LocationsManager): db interface for CmdbLocations

    Returns:
        int | None: public_id of the Rack's CmdbLocation, or None when the Rack is not in the tree - in
            which case its members are not either, so None is also what they carry
    """
    rack_node: dict[str, Any] | None = locations_manager.get_location_for_object(rack_id)

    return rack_node[LocationKey.PUBLIC_ID.value] if rack_node else None


def resolve_rack_of_location_node(
        parent_id: int | None,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        locations_manager: LocationsManager) -> int | None:
    """
    Answers which Rack a location parent stands for, if any

    Only the rack's OWN node counts. A location further down under a rack is an ordinary place that
    happens to hang below one, and pointing an object there says nothing about membership

    Args:
        parent_id (int | None): public_id of the CmdbLocation the write asks for, None when cleared
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        locations_manager (LocationsManager): db interface for CmdbLocations

    Returns:
        int | None: public_id of the Rack CmdbObject owning that node, or None when the node belongs to
            no object, to a non-Rack object, or when no parent was requested
    """
    if parent_id is None:
        return None

    node: dict[str, Any] | None = locations_manager.get_location(parent_id)

    if not node:
        return None

    owner_id: Any = node.get(LocationKey.OBJECT_ID.value)

    if not isinstance(owner_id, int):
        return None

    owner: dict[str, Any] | None = objects_manager.get_object(owner_id)

    if not owner or not is_rack_object(types_manager, owner):
        return None

    return owner_id


def guard_rack_location_change(
        request_user: CmdbUser,
        object_id: int,
        requested_parent: int | None,
        locations_manager: LocationsManager) -> None:
    """
    Applies both pre-write Rack rules to a location change

    A location parent that IS a rack's node means membership of that rack (the mount row is written
    afterwards by reconcile_object_rack_membership), so the two rules are about the changes that
    membership can not express:

      1. **A PLACED member may not be moved or cleared from here.** Its slot, area and position are
         layout the rack view owns, and a location change gives no way to say what should happen to
         them, so the change is refused with the placement named. An UNASSIGNED member is membership
         without placement and has nothing to lose, so it may leave - the mount row goes with it
      2. **A Rack may not be pointed into another Rack.** Racks do not nest (see member_object_blocker),
         so a placement that would have to mean membership, but can not, is refused instead of being
         allowed to make the tree and the rack disagree

    A no-op for an object that is neither a rack member nor a Rack, and for a member being pointed at
    the rack it is already in

    Args:
        request_user (CmdbUser): The user performing the write
        object_id (int): public_id of the CmdbObject being written
        requested_parent (int | None): The location parent the payload asks for
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 400 when a placed member would leave its rack, or when a Rack would be pointed
            into another Rack
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
        ManagerType.RACK_MOUNTS, request_user)

    target_rack_id: int | None = resolve_rack_of_location_node(
        requested_parent, objects_manager, types_manager, locations_manager,
    )

    mount: dict[str, Any] | None = rack_mounts_manager.get_mount_of_object(object_id)

    if target_rack_id is not None:
        candidate: dict[str, Any] | None = objects_manager.get_object(object_id)

        if candidate and is_rack_object(types_manager, candidate):
            abort(400, f"A Rack can not be placed into Rack ID:{target_rack_id} - Racks do not nest!")

        if not mount or mount[RackMountKey.RACK_ID.value] != target_rack_id:
            # This write would ADD the object to a rack, which is the licensed surface the /racks routes
            # guard - so the location must not be a way around it. Leaving a rack stays possible without
            # the license: cleanup is never blocked
            abort_if_feature_locked(LicenseFeature.IPAM, request_user)

    if not mount:
        return

    rack_id: int = mount[RackMountKey.RACK_ID.value]

    if requested_parent == get_rack_node_id(rack_id, locations_manager):
        # Where the member already is - which is also what the rack's own mirroring writes, and what an
        # ordinary edit of any other field sends back. Covers the rack that has no node at all: its
        # members are not in the tree, so None is the value they carry
        return

    area: Any = mount.get(RackMountKey.AREA.value)

    if area == RackArea.UNASSIGNED.value:
        # Membership without placement: leaving costs nothing, so the write is allowed and the mount row
        # is removed (or moved to the new rack) by reconcile_object_rack_membership afterwards
        return

    abort(400, f"This object is placed in Rack ID:{rack_id} ({area}) - unplace it in the Rack view "
               f"before moving it somewhere else!")


def reconcile_object_rack_membership(
        request_user: CmdbUser,
        object_id: int,
        requested_parent: int | None,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        locations_manager: LocationsManager) -> None:
    """
    Brings a CmdbObject's rack membership into line with the location it was just given

    The counterpart of the rack's own mirroring: the rack view places a member into the location tree,
    and this places a located object into the rack, so that "the location parent is a rack's node" and
    "there is a mount row" can not disagree. Written as a reconcile against the CURRENT state rather
    than a diff, which makes it idempotent and correct for all four events at once - joining a rack,
    moving between racks, leaving one, and staying put

    Membership created here is always UNASSIGNED: a location says which rack, never where in it. The
    location itself is NOT touched - the write this reacts to has already set it, and re-mirroring would
    only re-assert what is there

    Guarded before the write by guard_rack_location_change, which is what stops a placed member from
    getting here at all; the cases left are the ones that cost nothing to apply

    Args:
        request_user (CmdbUser): The user performing the write
        object_id (int): public_id of the CmdbObject that was written
        requested_parent (int | None): The location parent it now has, None when cleared
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        locations_manager (LocationsManager): db interface for CmdbLocations
    """
    rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
        ManagerType.RACK_MOUNTS, request_user)

    mount: dict[str, Any] | None = rack_mounts_manager.get_mount_of_object(object_id)

    if mount and requested_parent == get_rack_node_id(
            mount[RackMountKey.RACK_ID.value], locations_manager):
        # Still where its membership says it is. Asked FIRST and against the rack's NODE rather than the
        # resolved target, so an ordinary edit of a member whose rack has no location - every field of it
        # sends parent None - is not read as "left the rack" and does not drop the row
        return

    target_rack_id: int | None = resolve_rack_of_location_node(
        requested_parent, objects_manager, types_manager, locations_manager,
    )

    if not mount and target_rack_id is None:
        return

    if mount:
        # Left the rack, or moved to another one: the old membership goes either way. The unique index on
        # object_id forces this order, so there is a moment where the object is in no rack
        rack_mounts_manager.delete_item(mount[RackMountKey.PUBLIC_ID.value])

    if target_rack_id is None:
        return

    if member_object_blocker(objects_manager, types_manager, target_rack_id, object_id)[1]:
        # The rack view would refuse this object as a member, so no membership is invented for it. The
        # location stands: this is the one case where the tree says more than the rack does
        return

    membership_row: dict[str, Any] = build_membership_row(target_rack_id, object_id, request_user)
    assign_position_if_needed(rack_mounts_manager, membership_row)

    rack_mounts_manager.insert_item(membership_row)


def build_membership_row(rack_id: int, object_id: int, request_user: CmdbUser) -> dict[str, Any]:
    """
    Builds the UNASSIGNED mount row that stands for "this object belongs to this rack"

    The same row the mount route writes for a bare {"object_id": N} request, audit fields included, so a
    membership created from a location change is indistinguishable from one created in the Rack view. The
    caller assigns its position in the unassigned list, exactly as the mount route does

    Args:
        rack_id (int): public_id of the Rack the object joins
        object_id (int): public_id of the joining CmdbObject
        request_user (CmdbUser): The user performing the write, recorded as the row's author

    Returns:
        dict[str, Any]: The candidate row, without its public_id
    """
    candidate: dict[str, Any] = build_mount_candidate(rack_id, object_id, {})

    candidate[RackMountKey.AUTHOR_ID.value] = request_user.get_public_id()
    candidate[RackMountKey.CREATION_TIME.value] = datetime.now(timezone.utc)
    candidate[RackMountKey.LAST_EDIT_TIME.value] = None

    return candidate
