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
Orchestration helpers shared by the CmdbRackMount routes

Each helper is one step of a mount write - resolve the rack, resolve the member, build the candidate,
validate its geometry - so the routes read as the sequence they are and every step stays unit-testable
on its own. The helpers abort with HTTP 400 for a business-rule rejection (the convention in this
codebase; 409 is not used) and 404 only for a mount or rack that does not exist
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.framework.rack.rack_constants import (
    MOUNT_ABORT_PREFIX,
    RackDisplayName,
    RackLimits,
    RackMountError,
    RackOverviewKey,
)
from cmdb.framework.rack.rack_validator import coerce_rack_height
from cmdb.framework.rack.mount_validator import coerce_slot_value, validate_mount_placement

from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import (
    RackMountRequestKey,
    RackMountRouteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The geometry keys a request may set on a mount, in the order they are reported
GEOMETRY_KEYS: tuple[RackMountKey, ...] = (
    RackMountKey.START_SLOT,
    RackMountKey.HEIGHT,
    RackMountKey.POSITION,
)

# -------------------------------------------------------------------------------------------------------------------- #

def format_mount_errors_for_abort(errors: list[str]) -> str:
    """
    Joins the geometry validator's messages into one string for Flask's abort(400, ...)

    Args:
        errors (list[str]): The accumulated validator messages

    Returns:
        str: 'Rack mount validation failed: <msg1> | <msg2> | ...'
    """
    return f"{MOUNT_ABORT_PREFIX}: {' | '.join(errors)}"


def get_rack_or_abort(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        rack_id: int) -> dict[str, Any]:
    """
    Loads the Rack CmdbObject behind a rack id, aborting when it is not a Rack

    A mount is meaningless without its rack, and the rack is also where the height comes from - so this
    both resolves and type-checks it. 404 when nothing carries the id, 400 when the object exists but
    is not of the RACK SpecialType

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rack_id (int): public_id of the Rack CmdbObject

    Raises:
        HTTPException: 404 when no CmdbObject has that id, 400 when it is not a Rack

    Returns:
        dict[str, Any]: The Rack CmdbObject document
    """
    rack: dict[str, Any] | None = objects_manager.get_object(rack_id)

    if not rack:
        abort(404, RackMountError.RACK_NOT_FOUND.format(rack_id=rack_id))

    if not is_rack_type(types_manager, rack.get(CmdbObjectKey.TYPE_ID)):
        abort(400, RackMountError.NOT_A_RACK.format(rack_id=rack_id))

    return rack


def is_rack_type(types_manager: TypesManager, type_id: Any) -> bool:
    """
    Reports whether a CmdbType id is the Rack SpecialType

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_id (Any): public_id of the CmdbType to check

    Returns:
        bool: True when the type carries the RACK marker
    """
    if not isinstance(type_id, int):
        return False

    type_doc: dict[str, Any] | None = types_manager.get_type(type_id)

    if not type_doc:
        return False

    return type_doc.get(TypeSchemaKey.SPECIAL_TYPE) == SpecialType.RACK


def get_rack_height(rack: dict[str, Any]) -> int:
    """
    Reads a Rack's height in U from its own field

    The height is a normal field on the Rack CmdbObject, kept a positive int by the Rack write
    invariants - so a rack that got past those always yields a usable number here. A drifted document
    falls back to 0, which makes every placement fail its fit check rather than silently succeed

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document

    Returns:
        int: The rack's height in U, 0 when the field is missing or unusable
    """
    height: int | None = coerce_rack_height(extract_field_value(rack, RackField.HEIGHT))

    return height if isinstance(height, int) and height > 0 else 0


def member_object_blocker(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        rack_id: int,
        object_id: Any) -> tuple[int | None, str | None]:
    """
    Judges whether an object may be mounted, without aborting

    Three rules in the order they can be judged: the id has to be a usable int, a CmdbObject has to carry
    it, and that object may be neither the rack itself nor another Rack - Racks do not nest. Returns the
    reason instead of raising so the same rules back both the write route (which aborts) and the dry-run
    validate route (which reports); this is the blocker/guard pairing used by types_helper

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rack_id (int): public_id of the Rack the object would be mounted into
        object_id (Any): The raw object id from the request

    Returns:
        tuple[int | None, str | None]: (the validated object id, the reason it may not be mounted)
    """
    if object_id is None:
        return None, RackMountRouteError.MISSING_OBJECT_ID.value

    member_id: int | None = coerce_slot_value(object_id)

    if member_id is None or member_id < 1:
        return None, RackMountRouteError.INVALID_OBJECT_ID.format(value=object_id)

    if member_id == rack_id:
        return None, RackMountError.OBJECT_IS_THE_RACK.value

    member: dict[str, Any] | None = objects_manager.get_object(member_id)

    if not member:
        return None, RackMountError.OBJECT_NOT_FOUND.format(object_id=member_id)

    if is_rack_type(types_manager, member.get(CmdbObjectKey.TYPE_ID)):
        return None, RackMountError.OBJECT_IS_A_RACK.value

    return member_id, None


def validate_member_object_or_abort(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        rack_id: int,
        object_id: Any) -> int:
    """
    Checks the object being mounted may be mounted, aborting 400 with the reason

    The write path's wrapper around member_object_blocker

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rack_id (int): public_id of the Rack the object is being mounted into
        object_id (Any): The raw object id from the request

    Raises:
        HTTPException: 400 when the id is unusable, the object does not exist, is the rack itself, or is
                       itself a Rack

    Returns:
        int: The validated public_id of the CmdbObject to mount
    """
    member_id, blocker = member_object_blocker(objects_manager, types_manager, rack_id, object_id)

    if blocker:
        abort(400, blocker)

    return member_id


def second_membership_blocker(
        rack_mounts_manager: RackMountsManager,
        object_id: int,
        exclude_mount_id: int | None = None) -> str | None:
    """
    Judges whether the object already belongs to a rack, without aborting

    An object is a member of at most one rack - the UNASSIGNED bucket counts, so an object can not be
    unplaced in one rack and placed in another. The unique index on 'object_id' is the real guarantee; this
    exists so the caller can report it readably

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        object_id (int): public_id of the CmdbObject being mounted
        exclude_mount_id (int | None): public_id of the mount being changed, which may hold the object

    Returns:
        str | None: The reason the object may not be mounted, or None when it is free
    """
    if rack_mounts_manager.is_object_mounted(object_id, exclude_mount_id):
        return RackMountError.OBJECT_ALREADY_MOUNTED.format(object_id=object_id)

    return None


def refuse_second_membership(
        rack_mounts_manager: RackMountsManager,
        object_id: int,
        exclude_mount_id: int | None = None) -> None:
    """
    Aborts 400 when the object already belongs to a rack

    The write path's wrapper around second_membership_blocker

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        object_id (int): public_id of the CmdbObject being mounted
        exclude_mount_id (int | None): public_id of the mount being updated

    Raises:
        HTTPException: 400 when another mount already holds the object
    """
    blocker: str | None = second_membership_blocker(rack_mounts_manager, object_id, exclude_mount_id)

    if blocker:
        abort(400, blocker)


def build_mount_candidate(rack_id: int, object_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the mount document a create request would persist

    The rack and the object are taken from the resolved arguments, never from the body, and the geometry
    is normalised: a value the request omits is stored as None rather than left absent, so a mount
    document always has the same shape. The area defaults to UNASSIGNED, which makes a bare
    {"object_id": N} request mean "assign to this rack without placing it"

    Args:
        rack_id (int): public_id of the Rack
        object_id (int): public_id of the CmdbObject to mount
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The candidate mount document, without its public_id or audit fields
    """
    candidate: dict[str, Any] = {
        RackMountKey.RACK_ID.value: rack_id,
        RackMountKey.OBJECT_ID.value: object_id,
        RackMountKey.AREA.value: payload.get(RackMountRequestKey.AREA.value, RackArea.UNASSIGNED.value),
    }

    for key in GEOMETRY_KEYS:
        candidate[key.value] = normalize_geometry_value(payload.get(key.value))

    return candidate


def apply_mount_changes(stored: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """
    Merges a PATCH body onto a stored mount, returning the candidate it would become

    Only the keys the request actually carries are applied, so a body naming just an area moves the
    mount without touching its geometry. Moving INTO the unassigned bucket clears the placement while
    keeping the height as a hint, so re-placing the object can pre-fill the size the user already chose

    Args:
        stored (dict[str, Any]): The mount as currently persisted
        payload (dict[str, Any]): The PATCH body

    Returns:
        dict[str, Any]: The merged candidate mount document
    """
    candidate: dict[str, Any] = dict(stored)

    if RackMountRequestKey.AREA.value in payload:
        candidate[RackMountKey.AREA.value] = payload[RackMountRequestKey.AREA.value]

    for key in GEOMETRY_KEYS:
        if key.value in payload:
            candidate[key.value] = normalize_geometry_value(payload[key.value])

    if candidate.get(RackMountKey.AREA.value) == RackArea.UNASSIGNED.value:
        # Unplacing frees the slots and drops the ordering of the area it left, but the height stays:
        # it is the tedious value to re-enter, and it is what makes re-placing pre-fillable
        candidate[RackMountKey.START_SLOT.value] = None

    return candidate


def normalize_geometry_value(value: Any) -> int | None:
    """
    Coerces a request-supplied geometry value to an int, or None for "not set"

    An empty string is treated as unset, because that is what an HTML form sends for a cleared number
    input. A value that is present but not a whole number is passed through untouched so the validator
    can report it against the value the caller actually sent

    Args:
        value (Any): The raw geometry value from the request

    Returns:
        int | None: The coerced value, None when unset, or the original value when unusable
    """
    if value is None or value == '':
        return None

    coerced: int | None = coerce_slot_value(value)

    return coerced if coerced is not None else value


def placement_blockers(
        rack_mounts_manager: RackMountsManager,
        candidate: dict[str, Any],
        rack_height: int,
        exclude_mount_id: int | None = None) -> list[str]:
    """
    Returns every geometry rule a candidate mount breaks, without aborting

    The competing mounts are fetched for exactly the areas the candidate's area competes with - one
    indexed read, not one per area and not the whole rack

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        candidate (dict[str, Any]): The candidate mount document
        rack_height (int): The rack's height in U
        exclude_mount_id (int | None): public_id of a mount to ignore in the overlap check

    Returns:
        list[str]: The broken rules; empty when the placement is valid
    """
    competing_areas: set[str] = set()
    area: Any = candidate.get(RackMountKey.AREA.value)

    if RackArea.is_valid(area):
        competing_areas = {
            competing.value for competing in RackArea.get_conflicting_areas(RackArea(area))
        }

    existing: list[dict[str, Any]] = rack_mounts_manager.get_mounts_in_areas(
        candidate[RackMountKey.RACK_ID.value], competing_areas,
    )

    return validate_mount_placement(candidate, rack_height, existing, exclude_mount_id)


def validate_placement_or_abort(
        rack_mounts_manager: RackMountsManager,
        candidate: dict[str, Any],
        rack_height: int,
        exclude_mount_id: int | None = None) -> None:
    """
    Aborts 400 with every geometry problem a candidate mount has

    The write path's wrapper around placement_blockers

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        candidate (dict[str, Any]): The candidate mount document
        rack_height (int): The rack's height in U
        exclude_mount_id (int | None): public_id of a mount to ignore in the overlap check

    Raises:
        HTTPException: 400 naming every geometry rule the candidate breaks
    """
    errors: list[str] = placement_blockers(
        rack_mounts_manager, candidate, rack_height, exclude_mount_id,
    )

    if errors:
        abort(400, format_mount_errors_for_abort(errors))


def assign_position_if_needed(
        rack_mounts_manager: RackMountsManager,
        candidate: dict[str, Any]) -> None:
    """
    Appends a mount to the end of its area when it needs an order index and the request gave none

    The side lists and the unassigned bucket have no geometry to sort by, so a member without a position
    would have no defined place in them. A main-area mount is ordered by its slots, so its position is
    cleared instead of invented

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        candidate (dict[str, Any]): The candidate mount document, updated in place
    """
    area: Any = candidate.get(RackMountKey.AREA.value)

    if not RackArea.is_valid(area):
        return

    if RackArea(area) not in RackArea.get_ordered_areas():
        candidate[RackMountKey.POSITION.value] = None
        return

    if candidate.get(RackMountKey.POSITION.value) is None:
        candidate[RackMountKey.POSITION.value] = rack_mounts_manager.get_next_position(
            candidate[RackMountKey.RACK_ID.value], area,
        )


def get_mount_of_rack_or_abort(
        rack_mounts_manager: RackMountsManager,
        rack_id: int,
        mount_id: int) -> dict[str, Any]:
    """
    Loads a mount and checks it belongs to the rack in the URL

    Without the ownership check a caller holding any rack's id could edit any mount by guessing its id,
    and the 404 would be indistinguishable from a wrong rack

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the Rack from the URL
        mount_id (int): public_id of the CmdbRackMount from the URL

    Raises:
        HTTPException: 404 when no such mount exists in that rack

    Returns:
        dict[str, Any]: The CmdbRackMount document
    """
    mount: dict[str, Any] | None = rack_mounts_manager.get_item(mount_id, as_dict=True)

    if not mount or mount.get(RackMountKey.RACK_ID.value) != rack_id:
        abort(404, RackMountRouteError.MOUNT_NOT_FOUND.format(mount_id=mount_id, rack_id=rack_id))

    return mount


def get_rack_display_name(rack: dict[str, Any]) -> str:
    """
    Builds the name to show for a Rack

    `dg-rack-name` is required, so it normally wins outright. The fallbacks matter because required is a
    frontend marker: a Rack predating the write invariants could carry a blank name, and an empty label
    in the picker or the location tree is worse than a generated one

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document

    Returns:
        str: The rack's name, else 'Rack #<number>', else 'Rack #<public_id>'
    """
    name: Any = extract_field_value(rack, RackField.NAME)

    if isinstance(name, str) and name.strip():
        return name.strip()

    number: Any = extract_field_value(rack, RackField.NUMBER)

    if isinstance(number, str) and number.strip():
        return RackDisplayName.NUMBER_TEMPLATE.format(number=number.strip())

    return RackDisplayName.ID_TEMPLATE.format(public_id=rack.get(CmdbObjectKey.PUBLIC_ID))


def resolve_mounted_object_meta(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        mounts: list[dict[str, Any]]) -> tuple[dict[int, str], dict[int, dict[str, Any]], dict[int, int]]:
    """
    Batch-resolves everything the overview needs about the mounted objects

    Three bulk reads for the whole rack regardless of how many objects it holds: the objects, their
    summary lines and their types. Resolving per mount would be an N+1 on the one route that is called
    every time a rack is opened

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        mounts (list[dict[str, Any]]): The rack's mounts

    Returns:
        tuple: ({object_id: summary_line}, {type_id: {label, icon, color}}, {object_id: type_id})
    """
    object_ids: list[int] = [
        mount[RackMountKey.OBJECT_ID.value]
        for mount in mounts
        if isinstance(mount.get(RackMountKey.OBJECT_ID.value), int)
    ]

    if not object_ids:
        return {}, {}, {}

    object_docs: list[dict[str, Any]] = objects_manager.find_objects(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': list(set(object_ids))}},
        as_dict=True,
    )

    object_types: dict[int, int] = {
        doc[CmdbObjectKey.PUBLIC_ID.value]: doc[CmdbObjectKey.TYPE_ID.value]
        for doc in object_docs
        if isinstance(doc.get(CmdbObjectKey.TYPE_ID.value), int)
    }

    summary_lines: dict[int, str] = objects_manager.get_summary_lines_lookup(
        object_ids, with_type=False, object_docs=object_docs,
    )

    type_meta: dict[int, dict[str, Any]] = {
        type_id: {
            RackOverviewKey.TYPE_LABEL.value: cmdb_type.label,
            RackOverviewKey.TYPE_ICON.value: cmdb_type.get_icon(),
            RackOverviewKey.TYPE_COLOR.value: cmdb_type.ci_explorer_color,
        }
        for type_id, cmdb_type in types_manager.get_types_lookup(list(set(object_types.values()))).items()
    }

    return summary_lines, type_meta, object_types


def get_requested_height_or_abort(raw_height: Any) -> int:
    """
    Validates the ?height= parameter of the shrink pre-check

    Args:
        raw_height (Any): The raw query parameter value

    Raises:
        HTTPException: 400 when the value is missing or not a positive whole number

    Returns:
        int: The height to test the rack's mounts against
    """
    if raw_height is None or raw_height == '':
        abort(400, RackMountRouteError.MISSING_HEIGHT.value)

    height: int | None = coerce_slot_value(raw_height)

    if height is None or height < RackLimits.MIN_HEIGHT:
        abort(400, RackMountRouteError.INVALID_HEIGHT.format(value=raw_height))

    return height


def get_area_filter_or_abort(raw_area: str | None) -> str | None:
    """
    Validates an optional ?area= filter

    Args:
        raw_area (str | None): The raw query parameter value

    Raises:
        HTTPException: 400 when a value was given but is no RackArea

    Returns:
        str | None: The area to filter by, or None for every area
    """
    if raw_area is None or raw_area == '':
        return None

    if not RackArea.is_valid(raw_area):
        abort(400, RackMountRouteError.UNKNOWN_AREA_FILTER.format(
            area=raw_area,
            allowed=', '.join(member.value for member in RackArea),
        ))

    return raw_area


def collect_mount_blockers(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        rack_mounts_manager: RackMountsManager,
        rack: dict[str, Any],
        rack_id: int,
        payload: dict[str, Any]) -> list[str]:
    """
    Returns every reason a candidate mount would be refused, writing nothing

    Runs the same three checks the write path runs, in the same order, through the same blocker cores - so
    the dry run cannot answer "yes" to a placement the write would refuse, or vice versa. Short-circuits
    after the membership checks: a candidate whose object may not be mounted at all has no meaningful
    geometry answer, and reporting one would bury the real problem

    ``mount_id`` in the payload means "this is a MOVE of that existing mount", which excludes it from its own
    membership and overlap checks - the same exclusion the PATCH route applies

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack (dict[str, Any]): The Rack CmdbObject, already resolved and type-checked
        rack_id (int): public_id of the Rack
        payload (dict[str, Any]): The candidate as a mount request body

    Returns:
        list[str]: The reasons the mount would be refused; empty when it would be accepted
    """
    exclude_mount_id: int | None = coerce_slot_value(payload.get(RackMountRequestKey.MOUNT_ID.value))

    member_id, blocker = member_object_blocker(
        objects_manager, types_manager, rack_id, payload.get(RackMountRequestKey.OBJECT_ID.value),
    )

    if blocker:
        return [blocker]

    membership_blocker: str | None = second_membership_blocker(
        rack_mounts_manager, member_id, exclude_mount_id,
    )

    if membership_blocker:
        return [membership_blocker]

    candidate: dict[str, Any] = build_mount_candidate(rack_id, member_id, payload)

    return placement_blockers(
        rack_mounts_manager, candidate, get_rack_height(rack), exclude_mount_id,
    )
