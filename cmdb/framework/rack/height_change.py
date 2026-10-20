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
What happens to a Rack's mounts when its height changes

A Rack's height is an ordinary field on the Rack CmdbObject, so it can be lowered at any time - and
lowering it can leave mounts hanging past the top of the rack. Those mounts are **unplaced**, not
deleted: the object stays a member of the rack and lands in the UNASSIGNED bucket, keeping its height as
a hint so it can be re-placed with one click. Nothing is ever lost.

The reduction is applied on the object write path (post-write, because the new height has to be stored
before the mounts are measured against it), and the same computation backs the pre-check route the
frontend calls to warn the user first. Growing a rack needs no work at all
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.manager import TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager

from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.rack_model.rack_mount_helpers import top_slot_of
from cmdb.models.special_type_model.rack_constants import RackField

from cmdb.framework.rack.enforcement import is_rack_object
from cmdb.framework.rack.rack_validator import coerce_rack_height
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def find_mounts_beyond_height(mounts: list[dict[str, Any]], new_height: int) -> list[dict[str, Any]]:
    """
    Returns the mounts that would stick out of a rack of the given height

    Pure, so the pre-check route and the write path judge the candidates identically. A FULL_DEPTH mount
    is reported once even though it occupies two views

    Args:
        mounts (list[dict[str, Any]]): The rack's mounts
        new_height (int): The height the rack would have, in U

    Returns:
        list[dict[str, Any]]: The mounts whose topmost occupied U is above the new height
    """
    beyond: list[dict[str, Any]] = []

    for mount in mounts:
        top_slot: int | None = top_slot_of(mount)

        if top_slot is not None and top_slot > new_height:
            beyond.append(mount)

    return beyond


def get_height_conflicts(
        rack_mounts_manager: RackMountsManager,
        rack_id: int,
        new_height: int) -> list[dict[str, Any]]:
    """
    Reads the mounts a height reduction would displace

    Only the main areas are read - nothing else can be affected by the rack's height

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the Rack CmdbObject
        new_height (int): The height the rack would have, in U

    Returns:
        list[dict[str, Any]]: The mounts that would no longer fit
    """
    placed: list[dict[str, Any]] = rack_mounts_manager.get_mounts_in_areas(
        rack_id, {area.value for area in RackArea.get_main_areas()},
    )

    return find_mounts_beyond_height(placed, new_height)


def build_unplace_operations(mounts: list[dict[str, Any]], first_position: int) -> list[UpdateOne]:
    """
    Builds the write operations that move a set of mounts into the UNASSIGNED bucket

    One operation per mount, but issued as a single bulk write: each displaced mount needs its own
    position in the bucket, which a single `update_many` cannot express. The height is deliberately left
    untouched - it is what makes re-placing the object a one-click action - while the start slot is
    cleared, because that is the value the user chooses when re-placing

    Args:
        mounts (list[dict[str, Any]]): The mounts to unplace
        first_position (int): The position index the first unplaced mount takes in the bucket

    Returns:
        list[UpdateOne]: The bulk-write operations, in the order the mounts were given
    """
    operations: list[UpdateOne] = []

    for offset, mount in enumerate(mounts):
        operations.append(UpdateOne(
            {RackMountKey.PUBLIC_ID.value: mount[RackMountKey.PUBLIC_ID.value]},
            {'$set': {
                RackMountKey.AREA.value: RackArea.UNASSIGNED.value,
                RackMountKey.START_SLOT.value: None,
                RackMountKey.POSITION.value: first_position + offset,
            }},
        ))

    return operations


def unplace_mounts_beyond_height(
        rack_mounts_manager: RackMountsManager,
        rack_id: int,
        new_height: int) -> list[int]:
    """
    Moves every mount that no longer fits into the rack's UNASSIGNED bucket

    Re-run safe: a second call finds nothing beyond the height, because the mounts it moved carry no
    slot geometry any more

    Args:
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the Rack CmdbObject
        new_height (int): The rack's new height, in U

    Returns:
        list[int]: public_ids of the unplaced mounts, empty when everything still fits
    """
    displaced: list[dict[str, Any]] = get_height_conflicts(rack_mounts_manager, rack_id, new_height)

    if not displaced:
        return []

    first_position: int = rack_mounts_manager.get_next_position(rack_id, RackArea.UNASSIGNED.value)

    rack_mounts_manager.bulk_write(build_unplace_operations(displaced, first_position))

    return [mount[RackMountKey.PUBLIC_ID.value] for mount in displaced]


def handle_rack_height_change(
        types_manager: TypesManager,
        rack_mounts_manager: RackMountsManager,
        rack_id: int,
        stored_rack: dict[str, Any],
        previous_rack: dict[str, Any] | None) -> list[int]:
    """
    Applies the consequences of a Rack's height changing, after the new height has been stored

    A no-op for anything that is not a Rack, and for a height that stayed the same or grew. Runs
    post-write on purpose: the mounts are measured against the height that is now persisted, so an
    interrupted request can never leave mounts unplaced for a height that was not saved

    The displacement is applied rather than refused, by decision: the objects stay rack members and keep
    their height, so nothing is lost and the change is reversible by re-placing them. The frontend warns
    the user beforehand via the height_conflicts pre-check route; a client that skipped it still ends up
    consistent, and the displacement is logged

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        rack_id (int): public_id of the CmdbObject that was written
        stored_rack (dict[str, Any]): The object as persisted, carrying the new height
        previous_rack (dict[str, Any] | None): The pre-edit document; None on insert

    Returns:
        list[int]: public_ids of the mounts that were unplaced, empty when nothing changed
    """
    if previous_rack is None or not is_rack_object(types_manager, stored_rack):
        return []

    new_height: int | None = read_rack_height(stored_rack)
    old_height: int | None = read_rack_height(previous_rack)

    if new_height is None or old_height is None or new_height >= old_height:
        return []

    unplaced: list[int] = unplace_mounts_beyond_height(rack_mounts_manager, rack_id, new_height)

    if unplaced:
        LOGGER.warning(
            "[handle_rack_height_change] Rack ID:%s shrunk from %sU to %sU - unplaced mount(s) %s",
            rack_id, old_height, new_height, unplaced,
        )

    return unplaced


def read_rack_height(rack: dict[str, Any]) -> int | None:
    """
    Reads a Rack's height field, or None when it is missing or unusable

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document

    Returns:
        int | None: The height in U, or None when it cannot be read as a whole number
    """
    return coerce_rack_height(extract_field_value(rack, RackField.HEIGHT))
