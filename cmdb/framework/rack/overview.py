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

  - the **buckets**: the rack's mounts grouped by area, each resolved to the object's summary line and
    type metadata (label, icon, colour) so the frontend needs no follow-up request per mounted object

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
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.special_type_model.rack_constants import RackField

from cmdb.framework.rack.rack_constants import RackOverviewKey
from cmdb.framework.rack.mount_validator import coerce_slot_value
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def build_mount_row(
        mount: dict[str, Any],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]],
        object_types: dict[int, int]) -> dict[str, Any]:
    """
    Projects one mount into the row the rack view draws

    Carries the mount's own geometry plus enough about the mounted object to render it without a
    follow-up request. An object that no longer resolves keeps its slots and is reported with no summary
    line rather than dropped - a hole in the layout would be a worse lie than an unnamed block

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
        RackOverviewKey.AREA.value: mount.get(RackMountKey.AREA.value),
        RackOverviewKey.START_SLOT.value: mount.get(RackMountKey.START_SLOT.value),
        RackOverviewKey.HEIGHT.value: mount.get(RackMountKey.HEIGHT.value),
        RackOverviewKey.POSITION.value: mount.get(RackMountKey.POSITION.value),
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
        dict[str, Any]: The overview document: the rack header, the area buckets and the member count
    """
    buckets: dict[str, list[dict[str, Any]]] = build_area_buckets(
        mounts, summary_lines, type_meta, object_types,
    )

    return {
        RackOverviewKey.RACK.value: build_rack_header(rack, rack_height, display_name),
        RackOverviewKey.AREAS.value: buckets,
        RackOverviewKey.TOTAL_MOUNTS.value: sum(len(rows) for rows in buckets.values()),
    }
