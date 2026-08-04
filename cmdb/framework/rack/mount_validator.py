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
The geometry rules of a CmdbRackMount

Split into two layers so the expensive part is only reached when the cheap part passed:

  - the SHAPE rules are pure and need nothing but the mount itself - is the area a real area, does it
    carry the geometry that area requires, are the numbers whole and in range
  - the FIT rules need the rack (for its height) and the rack's other mounts (for the overlap), so they
    take those as plain data and stay free of any manager

Each check is a small function returning messages, which keeps them unit-testable without a database
and lets the routes report every problem with a placement at once instead of one per request
"""
from typing import Any

from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.rack_model.rack_mount_helpers import bottom_slot_of, occupied_slots_of, top_slot_of

from cmdb.utils.helpers import coerce_whole_number
from cmdb.framework.rack.rack_constants import RackMountError, RackMountLimits
# -------------------------------------------------------------------------------------------------------------------- #


def coerce_slot_value(value: Any) -> int | None:
    """
    Coerces a slot / height / position value to a whole number, or None when it is not one

    A U slot, a U count and an order index are all whole numbers, so they share the generic rules: a
    JSON client may send 3.0 and a form may send '3', but 3.5 is not a slot. Kept as a named alias
    rather than calling the utility directly so the domain reads as the domain

    Args:
        value (Any): The raw geometry value

    Returns:
        int | None: The value as an int, or None when it is not a whole number
    """
    return coerce_whole_number(value)


def validate_area(area: Any) -> list[str]:
    """
    Checks the requested area is one of the known Rack areas

    Args:
        area (Any): The requested area value

    Returns:
        list[str]: A single message when the area is unknown, empty otherwise
    """
    if RackArea.is_valid(area):
        return []

    return [RackMountError.INVALID_AREA.format(
        area=area,
        allowed=', '.join(member.value for member in RackArea),
    )]


def validate_mount_shape(mount: dict[str, Any]) -> list[str]:
    """
    Checks a mount carries the geometry its area requires, with usable values

    A main-area mount needs a start slot and a height; a side or unassigned mount needs neither, and an
    absent value there is not an error. A value that IS present is always range-checked, including the
    height retained as a hint on an unplaced mount

    Args:
        mount (dict[str, Any]): The mount document to check (area already validated)

    Returns:
        list[str]: Accumulated messages; empty when the shape is valid
    """
    errors: list[str] = []
    area = RackArea(mount[RackMountKey.AREA.value])

    start_slot: Any = mount.get(RackMountKey.START_SLOT.value)
    height: Any = mount.get(RackMountKey.HEIGHT.value)
    position: Any = mount.get(RackMountKey.POSITION.value)

    if area in RackArea.get_main_areas():
        if start_slot is None:
            errors.append(RackMountError.MISSING_START_SLOT.format(area=area.value))

        if height is None:
            errors.append(RackMountError.MISSING_HEIGHT.format(area=area.value))

    errors.extend(_check_bound(start_slot, RackMountLimits.MIN_START_SLOT, RackMountError.INVALID_START_SLOT))
    errors.extend(_check_bound(height, RackMountLimits.MIN_HEIGHT, RackMountError.INVALID_MOUNT_HEIGHT))
    errors.extend(_check_bound(position, RackMountLimits.MIN_POSITION, RackMountError.INVALID_POSITION))

    return errors


def _check_bound(value: Any, minimum: int, message: RackMountError) -> list[str]:
    """
    Checks one optional geometry value is a whole number at or above its lower bound

    An absent value is not this function's concern - whether it is allowed to be absent depends on the
    area and is decided by validate_mount_shape

    Args:
        value (Any): The raw value, possibly None
        minimum (int): The lowest accepted value
        message (RackMountError): The message to format when the value is unusable

    Returns:
        list[str]: A single message when the value is present and unusable, empty otherwise
    """
    if value is None:
        return []

    coerced: int | None = coerce_slot_value(value)

    if coerced is None or coerced < minimum:
        return [message.format(minimum=minimum, value=value)]

    return []


def validate_mount_fits_rack(mount: dict[str, Any], rack_height: int) -> list[str]:
    """
    Checks a placed mount stays inside the rack, at both ends

    A mount is anchored at its start slot and extends DOWNWARD, so it can leave the rack in two
    directions: the anchor itself can sit above the top, and a tall mount anchored low can reach below
    slot 1. Both are reported. Only main-area mounts occupy slots, so a side or unassigned mount always
    fits. Assumes the shape rules already passed, so the geometry is present and whole

    Args:
        mount (dict[str, Any]): The mount document to check
        rack_height (int): The rack's height in U

    Returns:
        list[str]: Messages for each end the mount overshoots, empty when it fits
    """
    top: int | None = top_slot_of(mount)
    bottom: int | None = bottom_slot_of(mount)

    if top is None or bottom is None:
        return []

    errors: list[str] = []

    if top > rack_height:
        errors.append(RackMountError.EXCEEDS_RACK_HEIGHT.format(
            start_slot=top,
            rack_height=rack_height,
        ))

    if bottom < RackMountLimits.MIN_START_SLOT:
        errors.append(RackMountError.BELOW_RACK_FLOOR.format(
            height=coerce_slot_value(mount.get(RackMountKey.HEIGHT.value)),
            start_slot=top,
            bottom_slot=bottom,
        ))

    return errors


def find_slot_conflicts(
        mount: dict[str, Any],
        existing_mounts: list[dict[str, Any]],
        exclude_mount_id: int | None = None) -> list[str]:
    """
    Checks a placed mount's U range against the mounts it competes with

    Which mounts compete is decided by the area: a FRONT placement competes with the other FRONT
    mounts and with every FULL_DEPTH one, and a FULL_DEPTH placement competes with all three main
    areas because it occupies the same U range in both views. 'exclude_mount_id' drops the mount being
    moved from its own comparison, so re-slotting a mount does not collide with where it currently is

    Args:
        mount (dict[str, Any]): The mount document being placed
        existing_mounts (list[dict[str, Any]]): The rack's mounts in the competing areas
        exclude_mount_id (int | None): public_id of a mount to ignore (the one being updated)

    Returns:
        list[str]: A single message naming the occupied slots and the mounts holding them, or empty
    """
    area = RackArea(mount[RackMountKey.AREA.value])
    competing_areas: frozenset[RackArea] = RackArea.get_conflicting_areas(area)

    if not competing_areas:
        return []

    wanted: set[int] = occupied_slots_of(mount)

    if not wanted:
        return []

    blocked: set[int] = set()
    blocking_ids: set[int] = set()

    for existing in existing_mounts:
        if existing.get(RackMountKey.PUBLIC_ID.value) == exclude_mount_id:
            continue

        if not RackArea.is_valid(existing.get(RackMountKey.AREA.value)):
            continue

        if RackArea(existing[RackMountKey.AREA.value]) not in competing_areas:
            continue

        overlap: set[int] = wanted & occupied_slots_of(existing)

        if overlap:
            blocked |= overlap
            blocking_ids.add(existing.get(RackMountKey.PUBLIC_ID.value))

    if not blocked:
        return []

    return [RackMountError.SLOTS_OCCUPIED.format(
        slots=sorted(blocked),
        area=area.value,
        mount_ids=sorted(mount_id for mount_id in blocking_ids if mount_id is not None),
    )]


def validate_mount_placement(
        mount: dict[str, Any],
        rack_height: int,
        existing_mounts: list[dict[str, Any]],
        exclude_mount_id: int | None = None) -> list[str]:
    """
    Runs every geometry rule for a mount, cheapest first

    The area is checked before anything reads it, then the shape, and only a mount whose shape holds is
    measured against the rack and its neighbours - checking the fit of a mount with a missing start
    slot would just add noise to the real problem

    Args:
        mount (dict[str, Any]): The mount document to validate
        rack_height (int): The rack's height in U
        existing_mounts (list[dict[str, Any]]): The rack's mounts in the competing areas
        exclude_mount_id (int | None): public_id of a mount to ignore in the overlap check

    Returns:
        list[str]: Accumulated messages; empty when the placement is valid
    """
    area_errors: list[str] = validate_area(mount.get(RackMountKey.AREA.value))

    if area_errors:
        return area_errors

    shape_errors: list[str] = validate_mount_shape(mount)

    if shape_errors:
        return shape_errors

    errors: list[str] = validate_mount_fits_rack(mount, rack_height)
    errors.extend(find_slot_conflicts(mount, existing_mounts, exclude_mount_id))

    return errors
