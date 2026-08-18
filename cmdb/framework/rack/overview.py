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
Assembly of the rack overview - everything needed to draw one Rack

Pure: the reads happen in the route helper and their results are passed in, so the whole projection is
unit-testable without a database. Two things it computes rather than stores:

  - the **buckets**: the rack's rows grouped by area, each resolved to the object's summary line and
    type metadata (label, icon, colour) so the frontend needs no follow-up request per mounted object
  - the **types legend**: one entry per distinct type among the rack's members, with how many of them
    carry it - the same metadata the rows already hold, tallied so a legend needs no scan of the buckets
  - the **occupants legend**: the same idea for the rows that have no type - how many reservations and
    blockers the rack holds, and how much of its height they hold

A bucket holds every kind of row: a MOUNT, and the two occupant kinds that name no CmdbObject. Each row
says which it is in ``kind``, so the grid styles a reservation differently from a blocker without
inferring it from which fields happen to be null. The type keys are null on an occupant and the
reservation keys are null on everything else - one row shape, whatever the row is.

Slot 1 is the bottom of the rack and the numbers increase upward; a mount is anchored at its ``start_slot``
and extends downward from there (see cmdb.models.rack_model.rack_mount_helpers).

Deliberately NOT computed here: which slots are free. The frontend draws the rack from the buckets, so an
unoccupied slot is visible without being told, and whether a specific placement is actually allowed is
answered by POST /racks/<id>/mounts/validate - which runs the very checks the write runs, so it can never
offer something the write would refuse
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey, RackMountKind
from cmdb.models.rack_model.rack_mount_helpers import occupied_slots_of
from cmdb.models.special_type_model.rack_constants import RackField

from cmdb.framework.rack.rack_constants import RackOverviewKey
from cmdb.framework.rack.mount_validator import coerce_slot_value
from cmdb.framework.rack.occupant_validator import read_stored_kind
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def build_mount_row(
        mount: dict[str, Any],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]],
        object_types: dict[int, int]) -> dict[str, Any]:
    """
    Projects one row of the rack into what the rack view draws

    Carries the row's own geometry plus, for a MOUNT, enough about the mounted object to render it
    without a follow-up request. An object that no longer resolves keeps its slots and is reported with
    no summary line rather than dropped - a hole in the layout would be a worse lie than an unnamed block,
    and the same holds for an occupant, which never had an object to resolve.

    Every key is present on every row. An occupant carries null type metadata, a MOUNT and a BLOCKER
    carry null reservation fields, and `kind` says which the row is - so the grid switches on one key
    instead of guessing from the nulls

    Args:
        mount (dict[str, Any]): The CmdbRackMount document
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        object_types (dict[int, int]): {object_id: type_id}, from the same batch

    Returns:
        dict[str, Any]: The overview row
    """
    object_id: Any = mount.get(RackMountKey.OBJECT_ID.value)
    type_id: int | None = object_types.get(object_id)
    meta: dict[str, Any] = type_meta.get(type_id, {}) if type_id is not None else {}

    return {
        RackOverviewKey.MOUNT_ID.value: mount.get(RackMountKey.PUBLIC_ID.value),
        RackOverviewKey.OBJECT_ID.value: object_id,
        RackOverviewKey.KIND.value: read_stored_kind(mount),
        RackOverviewKey.LABEL.value: mount.get(RackMountKey.LABEL.value),
        RackOverviewKey.AREA.value: mount.get(RackMountKey.AREA.value),
        RackOverviewKey.START_SLOT.value: mount.get(RackMountKey.START_SLOT.value),
        RackOverviewKey.HEIGHT.value: mount.get(RackMountKey.HEIGHT.value),
        RackOverviewKey.POSITION.value: mount.get(RackMountKey.POSITION.value),
        RackOverviewKey.START_DATE.value: mount.get(RackMountKey.START_DATE.value),
        RackOverviewKey.END_DATE.value: mount.get(RackMountKey.END_DATE.value),
        RackOverviewKey.COLOR.value: mount.get(RackMountKey.COLOR.value),
        RackOverviewKey.SUMMARY_LINE.value: summary_lines.get(object_id),
        RackOverviewKey.TYPE_ID.value: type_id,
        RackOverviewKey.TYPE_LABEL.value: meta.get(RackOverviewKey.TYPE_LABEL.value),
        RackOverviewKey.TYPE_ICON.value: meta.get(RackOverviewKey.TYPE_ICON.value),
        RackOverviewKey.TYPE_COLOR.value: meta.get(RackOverviewKey.TYPE_COLOR.value),
    }


def sort_key_for_area(area: RackArea):
    """
    Returns the sort key a bucket of the given area is ordered by

    A main area is ordered by its slots - that is its geometry and no separate index exists. The side
    lists and the unassigned bucket have no geometry, so they are ordered by their explicit position,
    with the mount id as a stable tie-break for rows that predate one

    Args:
        area (RackArea): The area whose bucket is being sorted

    Returns:
        Callable: A key function for sorted()
    """
    if area in RackArea.get_main_areas():
        return lambda row: (
            coerce_slot_value(row.get(RackOverviewKey.START_SLOT.value)) or 0,
            row.get(RackOverviewKey.MOUNT_ID.value) or 0,
        )

    return lambda row: (
        coerce_slot_value(row.get(RackOverviewKey.POSITION.value)) or 0,
        row.get(RackOverviewKey.MOUNT_ID.value) or 0,
    )


def build_area_buckets(
        mounts: list[dict[str, Any]],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]],
        object_types: dict[int, int]) -> dict[str, list[dict[str, Any]]]:
    """
    Groups the rack's mounts into one bucket per area, each sorted for drawing

    Every area is present even when empty, so the frontend can render an empty rack without special
    cases. A mount whose area is not a known one is dropped - it cannot be drawn anywhere

    Args:
        mounts (list[dict[str, Any]]): The rack's mounts
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        object_types (dict[int, int]): {object_id: type_id}, from the same batch

    Returns:
        dict[str, list[dict[str, Any]]]: {area: [row, ...]} covering every RackArea
    """
    buckets: dict[str, list[dict[str, Any]]] = {area.value: [] for area in RackArea}

    for mount in mounts:
        area: Any = mount.get(RackMountKey.AREA.value)

        if not RackArea.is_valid(area):
            LOGGER.warning("[build_area_buckets] Mount ID:%s carries the unknown area '%s' - skipped",
                           mount.get(RackMountKey.PUBLIC_ID.value), area)
            continue

        buckets[RackArea(area).value].append(
            build_mount_row(mount, summary_lines, type_meta, object_types)
        )

    for area in RackArea:
        buckets[area.value].sort(key=sort_key_for_area(area))

    return buckets


def build_types_legend(
        mounts: list[dict[str, Any]],
        type_meta: dict[int, dict[str, Any]],
        object_types: dict[int, int]) -> list[dict[str, Any]]:
    """
    Tallies the distinct types among a rack's members into the legend the rack view renders

    Follows MEMBERSHIP, not placement: an unplaced member is in the rack and its type belongs in the
    legend. The Rack's own type never appears - a Rack can not be mounted inside a Rack, so no mount
    contributes it. A mount whose object no longer resolves has no type and is tallied nowhere, and
    neither does a RESERVATION or a BLOCKER, which never had an object - so the counts can sum to less
    than the rack's total row count. The legend stays types-only by design: an occupant tally is a
    different thing and belongs beside it, not inside it

    Ordered by label with the type id as a tie-break: two types may carry the same label, and without
    the tie-break their order would wobble between two reads of the same rack

    Args:
        mounts (list[dict[str, Any]]): Every mount of the rack, all areas
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        object_types (dict[int, int]): {object_id: type_id}, from the same batch

    Returns:
        list[dict[str, Any]]: One entry per distinct type, empty when the rack holds nothing resolvable
    """
    counts: dict[int, int] = {}

    for mount in mounts:
        type_id: int | None = object_types.get(mount.get(RackMountKey.OBJECT_ID.value))

        if type_id is None:
            continue

        counts[type_id] = counts.get(type_id, 0) + 1

    legend: list[dict[str, Any]] = []

    for type_id, count in counts.items():
        meta: dict[str, Any] = type_meta.get(type_id, {})

        legend.append({
            RackOverviewKey.TYPE_ID.value: type_id,
            RackOverviewKey.TYPE_LABEL.value: meta.get(RackOverviewKey.TYPE_LABEL.value),
            RackOverviewKey.TYPE_ICON.value: meta.get(RackOverviewKey.TYPE_ICON.value),
            RackOverviewKey.TYPE_COLOR.value: meta.get(RackOverviewKey.TYPE_COLOR.value),
            RackOverviewKey.COUNT.value: count,
        })

    # A type whose document vanished keeps its entry with a null label, the same way a row keeps its
    # slots - so 'or' rather than a filter, and it sorts to the front instead of breaking the compare
    legend.sort(key=lambda entry: (
        entry[RackOverviewKey.TYPE_LABEL.value] or '',
        entry[RackOverviewKey.TYPE_ID.value],
    ))

    return legend


def build_occupants_legend(mounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Tallies the rack's reservations and blockers into the legend drawn beside the types legend

    The counterpart of build_types_legend for the rows that have no type: an occupant is tallied by its
    KIND instead. Together the two legends explain the rack's total row count, which the types legend
    alone can not - it skips every row that names no resolvable object.

    Two numbers per kind, because they answer different questions. ``count`` is how many rows there are
    and follows MEMBERSHIP, so an unassigned blocker is still one blocker the user has to deal with.
    ``slots`` is how much of the rack's height is actually held, so only a placed row contributes - an
    unassigned one holds nothing, which is exactly what makes the unassigned bucket a to-do list.

    A kind the rack does not hold is left out, the same way a type nobody uses is left out of the types
    legend, so an ordinary rack renders no occupant legend at all rather than two zeroes. Ordered by kind
    so two reads of the same rack agree

    Args:
        mounts (list[dict[str, Any]]): Every row of the rack, all areas

    Returns:
        list[dict[str, Any]]: One entry per occupant kind present, empty when the rack holds none
    """
    counts: dict[str, int] = {}
    slots: dict[str, int] = {}

    for mount in mounts:
        kind: str = read_stored_kind(mount)

        if not RackMountKind.is_occupant(kind):
            continue

        counts[kind] = counts.get(kind, 0) + 1
        slots[kind] = slots.get(kind, 0) + len(occupied_slots_of(mount))

    return [
        {
            RackOverviewKey.KIND.value: kind,
            RackOverviewKey.COUNT.value: count,
            RackOverviewKey.SLOTS.value: slots[kind],
        }
        for kind, count in sorted(counts.items())
    ]


def build_rack_header(rack: dict[str, Any], rack_height: int, display_name: str) -> dict[str, Any]:
    """
    Projects the Rack CmdbObject's own fields into the overview header

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document
        rack_height (int): The rack's height in U, already coerced
        display_name (str): The name to show for the rack

    Returns:
        dict[str, Any]: The header block of the overview
    """
    return {
        RackOverviewKey.PUBLIC_ID.value: rack.get('public_id'),
        RackOverviewKey.DISPLAY_NAME.value: display_name,
        RackOverviewKey.NAME.value: extract_field_value(rack, RackField.NAME),
        RackOverviewKey.NUMBER.value: extract_field_value(rack, RackField.NUMBER),
        RackOverviewKey.NOTES.value: extract_field_value(rack, RackField.NOTES),
        RackOverviewKey.HEIGHT.value: rack_height,
    }


def build_rack_overview(
        rack: dict[str, Any],
        rack_height: int,
        display_name: str,
        mounts: list[dict[str, Any]],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]],
        object_types: dict[int, int]) -> dict[str, Any]:
    """
    Assembles the whole rack overview from already-read data

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document
        rack_height (int): The rack's height in U
        display_name (str): The name to show for the rack
        mounts (list[dict[str, Any]]): Every mount of the rack, all areas
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        object_types (dict[int, int]): {object_id: type_id}, from the same batch

    Returns:
        dict[str, Any]: The overview document: the rack header, the two legends, the area buckets and the
                        row count

    Note ``total_mounts`` counts every ROW the rack holds, occupants included - they occupy the rack the
    same way a mount does. The two legends account for that total between them: the types legend tallies
    the rows that name a resolvable object, the occupants legend the rows that name none. A shortfall in
    both is a mount whose object or type no longer resolves - drawn in its bucket, tallied nowhere
    """
    buckets: dict[str, list[dict[str, Any]]] = build_area_buckets(
        mounts, summary_lines, type_meta, object_types,
    )

    return {
        RackOverviewKey.RACK.value: build_rack_header(rack, rack_height, display_name),
        RackOverviewKey.TYPES_LEGEND.value: build_types_legend(mounts, type_meta, object_types),
        RackOverviewKey.OCCUPANTS_LEGEND.value: build_occupants_legend(mounts),
        RackOverviewKey.AREAS.value: buckets,
        RackOverviewKey.TOTAL_MOUNTS.value: sum(len(rows) for rows in buckets.values()),
    }
