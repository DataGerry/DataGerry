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
Mirroring rack membership into the CmdbLocation tree

**The tree mirrors CmdbObjects.** A RESERVATION or a BLOCKER names none, so it never appears in the tree
at all - both mount hooks refuse anything that is not an object id, and every bulk path already filters on
the same test.

**The tree follows MEMBERSHIP, not placement.** An object assigned to a rack appears under it whether or
not it is placed in a slot, so unplacing, re-slotting or a height-driven displacement never moves anything
in the tree. Only joining, moving between racks and leaving do.

There is exactly one mechanism: the member's own location field is driven to the rack's node and the
ordinary mirror (``sync_object_location``) writes the node. The field is the record and the node is
derived from it, so the object's next save keeps it. This is why only a type that declares a location
field may be mounted at all - the picker filters on it and the mount write refuses it, so a member always
has somewhere to record where it is.

Moving a member from one rack to another **re-points its existing node** rather than deleting and
recreating it: ``sync_object_location`` updates the parent of a node that already exists, so the node
keeps its public_id and anything hanging beneath the moved object rides along with it. A delete would
promote those children onto the OLD rack.

Deleting is uniform, by decision: **whenever a rack stops holding a member, that member's node goes.** The
rack losing its location and the rack being deleted both remove the members from the tree rather than
promoting them onto whatever was above the rack.

This lives in the route layer rather than under cmdb/framework/rack/ because it orchestrates the
object<->location mirror helpers, which live here
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.rack_mounts_manager import RackMountsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser

from cmdb.models.location_model.location_constants import LocationKey

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    sync_object_location,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def is_object_id(value: Any) -> bool:
    """
    Reports whether a value identifies a CmdbObject, as opposed to an occupant row's missing id

    The test both mount hooks apply before touching the tree. Booleans are excluded on purpose: bool is
    an int subclass in Python, so a drifted `object_id: true` would otherwise pass as the object with
    public_id 1 and hang a node under the rack for it - the same trap `coerce_whole_number` avoids

    Args:
        value (Any): The candidate object id

    Returns:
        bool: True when the value is a usable CmdbObject public_id
    """
    return isinstance(value, int) and not isinstance(value, bool)


def get_rack_location_node(locations_manager: LocationsManager, rack_id: int) -> dict[str, Any] | None:
    """
    Returns the Rack's own CmdbLocation node, or None when the rack is not placed anywhere

    A member can only be hung off a rack that is itself in the tree; a rack with no location simply has no
    members in the tree either, which is the documented behaviour ("if not, the objects do not need to be
    displayed in the Location view")

    Args:
        locations_manager (LocationsManager): db interface for CmdbLocations
        rack_id (int): public_id of the Rack CmdbObject

    Returns:
        dict[str, Any] | None: The rack's location node, or None when it has none
    """
    return locations_manager.get_location_for_object(rack_id)


def attach_member_location(
        member_id: int,
        rack_node_id: int,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> None:
    """
    Places a rack member under the rack in the location tree

    Drives the member's own location field to the rack's node and lets the ordinary mirror write the
    node. A member that already has a node - because it is being MOVED here from another rack - has that
    node re-pointed by the mirror rather than replaced, so its public_id and its children survive the
    move. Best-effort: a failure is logged and swallowed, because the membership itself is already
    written and must not be rolled back over a tree side effect - the same contract
    ``sync_object_location`` already has

    Args:
        member_id (int): public_id of the mounted CmdbObject
        rack_node_id (int): public_id of the Rack's own CmdbLocation node
        request_user (CmdbUser): The user performing the mount (used to derive the node name)
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
    """
    try:
        member: dict[str, Any] | None = objects_manager.get_object(member_id)

        if not member:
            return

        member_type: CmdbType | None = objects_manager.get_object_type(member[CmdbObjectKey.TYPE_ID.value])

        # The field is the record and the node is derived from it, so the field is written first
        objects_manager.set_location_field_for_objects([member_id], rack_node_id)
        sync_object_location(
            member_id, rack_node_id, None, member_type, request_user, objects_manager, locations_manager,
        )
    except Exception as err:
        LOGGER.error("[attach_member_location] Failed to place Object ID:%s under Rack node ID:%s: %s. Type: %s",
                     member_id, rack_node_id, err, type(err))


def detach_member_location(
        member_id: int,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> None:
    """
    Removes a member's CmdbLocation node when it stops being a member of the rack

    Uniform for every way membership ends - removed from the rack, the rack losing its location, the rack
    being deleted. The node is deleted rather than promoted onto whatever was above the rack: an object's
    place in the tree came from the rack, so it goes with the rack. Clears the object's own location field
    too when it has one, otherwise the field would dangle at a node that no longer exists and the object
    would fail validation on its next edit

    Best-effort, for the same reason as attach_member_location

    Args:
        member_id (int): public_id of the CmdbObject leaving the rack
        request_user (CmdbUser): The user performing the operation
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
    """
    del request_user

    try:
        existing: dict[str, Any] | None = locations_manager.get_location_for_object(member_id)

        # Cleared even without a node, so a field pointing at an already-gone node cannot linger
        objects_manager.clear_location_field_for_objects([member_id])

        if existing:
            locations_manager.delete_location(existing[LocationKey.PUBLIC_ID.value])
    except Exception as err:
        LOGGER.error("[detach_member_location] Failed to remove the Location of Object ID:%s: %s. Type: %s",
                     member_id, err, type(err))


def get_member_object_ids(rack_mounts_manager: RackMountsManager, rack_id: int) -> list[int]:
    """
    Returns the public_ids of every CmdbObject that is a member of a rack, placed or not

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the Rack CmdbObject

    Returns:
        list[int]: public_ids of the member objects
    """
    return [
        mount[RackMountKey.OBJECT_ID.value]
        for mount in rack_mounts_manager.get_mounts_of_rack(rack_id)
        if isinstance(mount.get(RackMountKey.OBJECT_ID.value), int)
    ]


def attach_all_member_locations(
        rack_id: int,
        rack_node_id: int,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager,
        rack_mounts_manager: RackMountsManager) -> int:
    """
    Places every member of a rack under it in the tree

    Used when the rack gains a location, or moves to a different one: the members follow it. Each member
    takes whichever branch its own type calls for, so a rack holding both kinds of type ends up with both
    kinds of node - indistinguishable in the tree

    Args:
        rack_id (int): public_id of the Rack CmdbObject
        rack_node_id (int): public_id of the Rack's own CmdbLocation node
        request_user (CmdbUser): The user performing the operation
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts

    Returns:
        int: The number of members processed
    """
    member_ids: list[int] = get_member_object_ids(rack_mounts_manager, rack_id)

    for member_id in member_ids:
        attach_member_location(
            member_id, rack_node_id, request_user, objects_manager, locations_manager,
        )

    return len(member_ids)


def detach_all_member_locations(
        rack_id: int,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager,
        rack_mounts_manager: RackMountsManager) -> int:
    """
    Removes every member of a rack from the tree

    Used when the rack loses its location and when the rack itself is deleted - by decision both remove
    the members rather than promoting them

    Args:
        rack_id (int): public_id of the Rack CmdbObject
        request_user (CmdbUser): The user performing the operation
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts

    Returns:
        int: The number of members processed
    """
    member_ids: list[int] = get_member_object_ids(rack_mounts_manager, rack_id)

    for member_id in member_ids:
        detach_member_location(member_id, request_user, objects_manager, locations_manager)

    return len(member_ids)


def handle_mount_created(
        rack_id: int,
        member_id: Any,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager,
        moved_from_rack: bool = False) -> None:
    """
    Mirrors a new membership into the tree

    **A no-op unless it is given an object id.** The tree mirrors CmdbObjects, so a RESERVATION or a
    BLOCKER - which names none - never gets a node. The guard lives here rather than at the call site so
    the invariant is stated once, in the module that owns the tree, and holds for any future caller; it
    is the same `isinstance(..., int)` test `get_member_object_ids`, `get_mounted_object_ids` and
    `delete_rack_memberships` apply, and together they are the house rule "anything keyed on the mounted
    object skips the rows that have none".

    When the new rack has a location the member is placed under it - which for a member arriving from
    another rack re-points the node it already had.

    When the new rack has NO location the two cases differ, which is what ``moved_from_rack`` is for. A
    plain new membership had no node to begin with, so there is nothing to do and the member will be
    placed later by reconcile_member_locations if the rack is ever given a location. A member MOVED here,
    though, still sits under its previous rack, so leaving it there would show the object in a rack it no
    longer belongs to - it is taken out of the tree instead

    Args:
        rack_id (int): public_id of the Rack
        member_id (Any): public_id of the newly mounted CmdbObject; anything else is an occupant row
        request_user (CmdbUser): The user performing the mount
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
        moved_from_rack (bool): True when the object was taken out of another rack to be mounted here
    """
    if not is_object_id(member_id):
        return

    rack_node: dict[str, Any] | None = get_rack_location_node(locations_manager, rack_id)

    if not rack_node:
        if moved_from_rack:
            detach_member_location(member_id, request_user, objects_manager, locations_manager)

        return

    attach_member_location(
        member_id, rack_node[LocationKey.PUBLIC_ID.value],
        request_user, objects_manager, locations_manager,
    )


def handle_mount_removed(
        member_id: Any,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> None:
    """
    Removes a member from the tree when it is taken out of the rack

    **A no-op unless it is given an object id**, for the same reason as handle_mount_created: an occupant
    never had a node to remove.

    Note this is NOT called when a member is merely unplaced: the tree follows membership, so an object
    moved into the unassigned bucket keeps its place under the rack

    Args:
        member_id (Any): public_id of the CmdbObject removed from the rack; anything else is an occupant
        request_user (CmdbUser): The user performing the removal
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
    """
    if not is_object_id(member_id):
        return

    detach_member_location(member_id, request_user, objects_manager, locations_manager)


def reconcile_member_locations(
        rack_id: int,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager,
        rack_mounts_manager: RackMountsManager) -> int:
    """
    Brings a rack's members into line with where the rack itself now is

    Deliberately stated as a reconcile rather than a diff of what changed: it reads the rack's CURRENT node
    and either places every member under it or removes every member from the tree. That makes it idempotent
    and correct for all three events at once - the rack gaining a location, moving to a different one, and
    losing it - with no before/after comparison to get wrong. Both branches are cheap when there is nothing
    to do, because a rack with no members reads one empty mount list

    Must run AFTER the rack's own location has been mirrored, since it reads the result of that

    Args:
        rack_id (int): public_id of the Rack CmdbObject
        request_user (CmdbUser): The user performing the operation
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts

    Returns:
        int: The number of members reconciled
    """
    rack_node: dict[str, Any] | None = get_rack_location_node(locations_manager, rack_id)

    if rack_node:
        return attach_all_member_locations(
            rack_id, rack_node[LocationKey.PUBLIC_ID.value],
            request_user, objects_manager, locations_manager, rack_mounts_manager,
        )

    return detach_all_member_locations(
        rack_id, request_user, objects_manager, locations_manager, rack_mounts_manager,
    )
