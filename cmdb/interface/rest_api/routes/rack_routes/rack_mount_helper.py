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
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
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
from cmdb.framework.rack.assignable_objects import build_assignable_rows

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

# The only value that turns a boolean query parameter on
PARAM_TRUE: str = 'true'

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


def get_type_doc(types_manager: TypesManager, type_id: Any) -> dict[str, Any] | None:
    """
    Reads a CmdbType document by id, tolerating an id that is not one

    Exists so the mount rules that judge a type - is it a Rack, does it carry a location field - can be
    answered from a single read rather than one per rule

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_id (Any): public_id of the CmdbType to read

    Returns:
        dict[str, Any] | None: The type document, or None when the id is unusable or nothing matches
    """
    if not isinstance(type_id, int):
        return None

    return types_manager.get_type(type_id)


def is_rack_type_doc(type_doc: dict[str, Any] | None) -> bool:
    """
    Reports whether a CmdbType document carries the RACK marker

    Args:
        type_doc (dict[str, Any] | None): The CmdbType document

    Returns:
        bool: True when the type is the Rack SpecialType
    """
    if not type_doc:
        return False

    return type_doc.get(TypeSchemaKey.SPECIAL_TYPE) == SpecialType.RACK


def type_doc_has_location_field(type_doc: dict[str, Any] | None) -> bool:
    """
    Reports whether a CmdbType document declares a location-typed field

    A rack member is mirrored into the location tree under its rack and the member's own location field
    is what records that, so a type without one can not be mounted at all. The check is on the field's
    TYPE, never on its name, the same way the rest of the location machinery matches - a type whose
    location field is not called 'dg_location' still counts

    Args:
        type_doc (dict[str, Any] | None): The CmdbType document

    Returns:
        bool: True when the type declares a location field
    """
    if not type_doc:
        return False

    return any(
        isinstance(field, dict) and field.get(FieldKey.TYPE.value) == FieldType.LOCATION
        for field in type_doc.get(TypeSchemaKey.FIELDS.value) or []
    )


def is_rack_type(types_manager: TypesManager, type_id: Any) -> bool:
    """
    Reports whether a CmdbType id is the Rack SpecialType

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_id (Any): public_id of the CmdbType to check

    Returns:
        bool: True when the type carries the RACK marker
    """
    return is_rack_type_doc(get_type_doc(types_manager, type_id))


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

    Four rules in the order they can be judged: the id has to be a usable int, a CmdbObject has to carry
    it, that object may be neither the rack itself nor another Rack (Racks do not nest), and its type has
    to declare a location field - the same rule the picker filters on, enforced here so an API client
    meets it too. Returns the reason instead of raising so the same rules back both the write route
    (which aborts) and the dry-run validate route (which reports); this is the blocker/guard pairing used
    by types_helper

    Belonging to ANOTHER rack is deliberately not a blocker: mounting such an object moves it

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

    type_doc: dict[str, Any] | None = get_type_doc(types_manager, member.get(CmdbObjectKey.TYPE_ID))

    if is_rack_type_doc(type_doc):
        return None, RackMountError.OBJECT_IS_A_RACK.value

    if not type_doc_has_location_field(type_doc):
        return None, RackMountError.TYPE_HAS_NO_LOCATION_FIELD.format(object_id=member_id)

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


def same_rack_membership_blocker(
        existing_mount: dict[str, Any] | None,
        rack_id: int,
        object_id: int,
        exclude_mount_id: int | None = None) -> str | None:
    """
    Judges whether the object is already in THIS rack, without aborting

    An object is still a member of at most one rack, but a second membership is no longer refused: an
    object held by ANOTHER rack is mounted by moving it out of that one, which is what the picker offers.
    What stays refused is mounting an object into the rack it is already in - the verb for that is a PATCH
    of its existing mount, and re-inserting it would drop that mount's public_id and collide with its own
    slots

    Pure - the mount is read by the caller and passed in, so both the write path and the dry run judge the
    same document they already hold

    Args:
        existing_mount (dict[str, Any] | None): The mount currently holding the object, if any
        rack_id (int): public_id of the Rack the object would be mounted into
        object_id (int): public_id of the CmdbObject being mounted
        exclude_mount_id (int | None): public_id of the mount being changed, which may hold the object

    Returns:
        str | None: The reason the object may not be mounted, or None when it may be
    """
    if not existing_mount:
        return None

    if existing_mount.get(RackMountKey.PUBLIC_ID.value) == exclude_mount_id:
        return None

    if existing_mount.get(RackMountKey.RACK_ID.value) == rack_id:
        return RackMountError.OBJECT_ALREADY_IN_THIS_RACK.format(object_id=object_id)

    return None


def resolve_move_source_or_abort(
        rack_mounts_manager: RackMountsManager,
        rack_id: int,
        object_id: int) -> dict[str, Any] | None:
    """
    Reads the mount the object has to be taken out of before it can be mounted here

    The write path's wrapper around same_rack_membership_blocker: it aborts when the object is already in
    this rack and otherwise returns the mount holding it in a DIFFERENT rack, which the caller deletes
    to complete the move. None means the object is in no rack and this is an ordinary mount

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the Rack the object is being mounted into
        object_id (int): public_id of the CmdbObject being mounted

    Raises:
        HTTPException: 400 when the object is already a member of this rack

    Returns:
        dict[str, Any] | None: The mount to remove, or None when the object is free
    """
    existing_mount: dict[str, Any] | None = rack_mounts_manager.get_mount_of_object(object_id)

    blocker: str | None = same_rack_membership_blocker(existing_mount, rack_id, object_id)

    if blocker:
        abort(400, blocker)

    return existing_mount


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

    return summary_lines, build_type_meta(types_manager, list(object_types.values())), object_types


def shape_assignable_page(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        rack_mounts_manager: RackMountsManager,
        object_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Resolves one page of mount candidates into the rows the rack picker draws

    Four bulk reads for the whole page - the summary lines (composed from the documents already in hand,
    so nothing is re-fetched), the type metadata of the types actually present on the page, and the two
    behind the rack hint. Scoping each read to the page rather than to every mountable object keeps a
    tenant with many types or many racks from paying for lookups it never renders

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        object_docs (list[dict[str, Any]]): The candidate CmdbObject documents of one page

    Returns:
        list[dict[str, Any]]: One picker row per document, in input order
    """
    object_ids: list[int] = [
        doc[CmdbObjectKey.PUBLIC_ID.value]
        for doc in object_docs
        if isinstance(doc.get(CmdbObjectKey.PUBLIC_ID.value), int)
    ]
    type_ids: list[int] = [
        doc[CmdbObjectKey.TYPE_ID.value]
        for doc in object_docs
        if isinstance(doc.get(CmdbObjectKey.TYPE_ID.value), int)
    ]

    summary_lines: dict[int, str] = objects_manager.get_summary_lines_lookup(
        object_ids, with_type=False, object_docs=object_docs,
    ) if object_ids else {}

    return build_assignable_rows(
        object_docs,
        summary_lines,
        build_type_meta(types_manager, type_ids),
        resolve_assigned_racks(objects_manager, rack_mounts_manager, object_ids),
    )


def resolve_assigned_racks(
        objects_manager: ObjectsManager,
        rack_mounts_manager: RackMountsManager,
        object_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Batch-resolves which rack each picker candidate is currently in

    Two bulk reads for the whole page: the mounts holding these objects, then the racks those mounts
    belong to. The candidates of the rack being filled are already excluded from the page, so every
    rack found here is a DIFFERENT one - the hint the frontend shows before a mount moves the object.
    A mount pointing at a rack that no longer resolves contributes no entry, so the row simply reads as
    free rather than naming a rack the user can not open

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        object_ids (list[int]): public_ids of the candidates on the page

    Returns:
        dict[int, dict[str, Any]]: {object_id: {public_id, display_name}}, absent for a free candidate
    """
    mounts: list[dict[str, Any]] = rack_mounts_manager.get_mounts_of_objects(object_ids)

    if not mounts:
        return {}

    rack_ids: list[int] = [
        mount[RackMountKey.RACK_ID.value]
        for mount in mounts
        if isinstance(mount.get(RackMountKey.RACK_ID.value), int)
    ]

    rack_docs: list[dict[str, Any]] = objects_manager.find_objects(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': list(set(rack_ids))}},
        as_dict=True,
    )

    rack_names: dict[int, str] = {
        doc[CmdbObjectKey.PUBLIC_ID.value]: get_rack_display_name(doc)
        for doc in rack_docs
        if isinstance(doc.get(CmdbObjectKey.PUBLIC_ID.value), int)
    }

    return {
        mount[RackMountKey.OBJECT_ID.value]: {
            RackOverviewKey.PUBLIC_ID.value: mount[RackMountKey.RACK_ID.value],
            RackOverviewKey.DISPLAY_NAME.value: rack_names[mount[RackMountKey.RACK_ID.value]],
        }
        for mount in mounts
        if isinstance(mount.get(RackMountKey.OBJECT_ID.value), int)
        and mount.get(RackMountKey.RACK_ID.value) in rack_names
    }


def build_type_meta(types_manager: TypesManager, type_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Batch-resolves the type metadata a rack row carries, keyed by type id

    One bulk read for however many ids are given, duplicates collapsed. Shared by the overview and the
    assignable-objects picker so both render a type identically - the picker rows and the mount rows are
    deliberately the same shape

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_ids (list[int]): The CmdbType public_ids to resolve; duplicates are allowed

    Returns:
        dict[int, dict[str, Any]]: {type_id: {label, icon, colour}}, absent for a type that did not
                                   resolve
    """
    if not type_ids:
        return {}

    return {
        type_id: {
            RackOverviewKey.TYPE_LABEL.value: cmdb_type.label,
            RackOverviewKey.TYPE_ICON.value: cmdb_type.get_icon(),
            RackOverviewKey.TYPE_COLOR.value: cmdb_type.ci_explorer_color,
        }
        for type_id, cmdb_type in types_manager.get_types_lookup(list(set(type_ids))).items()
    }


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


def is_flag_enabled(raw_value: str | None) -> bool:
    """
    Reads a boolean query parameter

    Off unless the caller explicitly asked for it: an absent, empty or unrecognised value means off,
    never an error, so a stale frontend passing something odd gets the default list rather than a 400.
    Case-insensitive, unlike the older `onlyActiveObjCookie` check, because a query parameter typed by
    hand is as likely to read 'TRUE'

    Args:
        raw_value (str | None): The raw query parameter value

    Returns:
        bool: True when the flag is on
    """
    return isinstance(raw_value, str) and raw_value.strip().lower() == PARAM_TRUE


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

    An object held by ANOTHER rack validates like a free one, because mounting it there simply moves it -
    the answer stays silent about the move, since the picker row the candidate came from already names the
    rack it is in

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

    membership_blocker: str | None = same_rack_membership_blocker(
        rack_mounts_manager.get_mount_of_object(member_id), rack_id, member_id, exclude_mount_id,
    )

    if membership_blocker:
        return [membership_blocker]

    candidate: dict[str, Any] = build_mount_candidate(rack_id, member_id, payload)

    return placement_blockers(
        rack_mounts_manager, candidate, get_rack_height(rack), exclude_mount_id,
    )
