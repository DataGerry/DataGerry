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
The slot arithmetic of a rack mount - the single source of truth for which U a mount occupies

**U numbering runs from the bottom up: slot 1 is the lowest position in the rack.** A mount is anchored at
its ``start_slot`` and extends **downward** from there, so ``start_slot`` is the mount's TOPMOST occupied
U - a 3U mount at slot 25 occupies 25, 24 and 23.

Every consumer reads its geometry through here: the model's own accessor, the mount validator's overlap
check, the overview's free-slot computation and the height-change rule. Keeping one implementation is what
stops those four from ever disagreeing about where a mount sits - they did agree only by coincidence while
the arithmetic was copied

Lives in the model layer rather than under cmdb/framework/rack/ so the CmdbRackMount model can use it
without a framework import
"""
from typing import Any

from cmdb.utils import coerce_whole_number

from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
# -------------------------------------------------------------------------------------------------------------------- #

def has_slot_geometry(mount: dict[str, Any]) -> bool:
    """
    Reports whether a mount document carries usable slot geometry

    True only for a main-area mount with a whole-number start slot and a height of at least one U. A side
    or unassigned mount holds no slots at all, and neither does a drifted row

    Args:
        mount (dict[str, Any]): The CmdbRackMount document

    Returns:
        bool: True when the mount occupies slots
    """
    if not RackArea.is_valid(mount.get(RackMountKey.AREA.value)):
        return False

    if RackArea(mount[RackMountKey.AREA.value]) not in RackArea.get_main_areas():
        return False

    start_slot: int | None = coerce_whole_number(mount.get(RackMountKey.START_SLOT.value))
    height: int | None = coerce_whole_number(mount.get(RackMountKey.HEIGHT.value))

    return start_slot is not None and height is not None and height >= 1


def top_slot_of(mount: dict[str, Any]) -> int | None:
    """
    Returns the highest U a mount occupies, or None when it occupies none

    This is simply the mount's ``start_slot``: a mount is anchored at its start slot and grows downward,
    so nothing it occupies is above it. Named for the meaning rather than the field so the height rules
    read as what they check

    Args:
        mount (dict[str, Any]): The CmdbRackMount document

    Returns:
        int | None: The topmost occupied U, or None when the mount has no slot geometry
    """
    if not has_slot_geometry(mount):
        return None

    return coerce_whole_number(mount[RackMountKey.START_SLOT.value])


def bottom_slot_of(mount: dict[str, Any]) -> int | None:
    """
    Returns the lowest U a mount occupies, or None when it occupies none

    A 3U mount anchored at slot 25 reaches down to 23. This is the value the rack floor is checked
    against - a mount may not extend below slot 1

    Args:
        mount (dict[str, Any]): The CmdbRackMount document

    Returns:
        int | None: The lowest occupied U, or None when the mount has no slot geometry
    """
    if not has_slot_geometry(mount):
        return None

    start_slot: int = coerce_whole_number(mount[RackMountKey.START_SLOT.value])
    height: int = coerce_whole_number(mount[RackMountKey.HEIGHT.value])

    return start_slot - height + 1


def occupied_slots_of(mount: dict[str, Any]) -> set[int]:
    """
    Returns every U a mount occupies

    Empty for anything without usable main-area geometry, so a side, unassigned or drifted mount simply
    blocks nothing rather than raising - one bad row must not make every placement in the rack impossible

    Args:
        mount (dict[str, Any]): The CmdbRackMount document

    Returns:
        set[int]: The occupied U numbers, counted downward from the start slot
    """
    top: int | None = top_slot_of(mount)
    bottom: int | None = bottom_slot_of(mount)

    if top is None or bottom is None:
        return set()

    return set(range(bottom, top + 1))
