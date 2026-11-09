# DataGerry - OpenSource Enterprise CMDB
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
Database update 20261107: two placed rack mounts never share a U range

Two placements checked at the same moment could both find a range free and both be stored on top of each other: the
overlap check read the rack and the write came after it, with nothing in between. The placements now run inside a
per-rack lock; this update repairs what the race may have left. Per rack, the placed mounts (FRONT, BACK, FULL_DEPTH)
are taken in the order they were placed - last edit, else creation, then public_id - and a mount that collides with one
taken before it is **unplaced**, exactly as a rack height shrink does: it moves to the UNASSIGNED list (appended after
the rack's highest position there), its start slot cleared and its height kept as the hint for re-placing it. Nothing is
deleted; the object stays a member of the rack.

FRONT competes with FRONT and FULL_DEPTH, BACK with BACK and FULL_DEPTH, FULL_DEPTH with all three. Two ranges collide
when the higher bottom is not above the lower top (a mount occupies its start slot and the height - 1 slots below it).
A mount without a whole-number start slot and height takes no part.

Re-run safe: the unplaced mounts carry no slot any more, so a second run finds no collision and writes nothing
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
MOUNTS_COLLECTION: str = 'framework.rackMounts'
PUBLIC_ID_FIELD: str = 'public_id'
RACK_ID_FIELD: str = 'rack_id'
AREA_FIELD: str = 'area'
START_SLOT_FIELD: str = 'start_slot'
HEIGHT_FIELD: str = 'height'
POSITION_FIELD: str = 'position'
CREATION_TIME_FIELD: str = 'creation_time'
LAST_EDIT_TIME_FIELD: str = 'last_edit_time'
FRONT: str = 'FRONT'
BACK: str = 'BACK'
FULL_DEPTH: str = 'FULL_DEPTH'
UNASSIGNED: str = 'UNASSIGNED'
MAIN_AREAS: list[str] = [FRONT, BACK, FULL_DEPTH]
CONFLICTING_AREAS: dict[str, frozenset[str]] = {
    FRONT: frozenset({FRONT, FULL_DEPTH}),
    BACK: frozenset({BACK, FULL_DEPTH}),
    FULL_DEPTH: frozenset({FRONT, BACK, FULL_DEPTH}),
}
MOUNT_PROJECTION: dict[str, int] = {
    '_id': 0, PUBLIC_ID_FIELD: 1, RACK_ID_FIELD: 1, AREA_FIELD: 1, START_SLOT_FIELD: 1, HEIGHT_FIELD: 1,
    CREATION_TIME_FIELD: 1, LAST_EDIT_TIME_FIELD: 1,
}
POSITION_PROJECTION: dict[str, int] = {'_id': 0, POSITION_FIELD: 1}
INTEGER_BSON_TYPES: list[str] = ['int', 'long']
# A mount that never recorded when it was placed sorts first: it was there before any timed one
NEVER: datetime = datetime.min.replace(tzinfo=timezone.utc)
DESCENDING: int = -1

# -------------------------------------------------------------------------------------------------------------------- #

def whole_number(value: Any) -> int | None:
    """
    A stored slot value as an int: an int, or a float without a fraction; a bool is no number

    Args:
        value (Any): The stored value

    Returns:
        int | None: The number, None when the value is none
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float) and value.is_integer():
        return int(value)

    return None


def slot_range(mount: dict[str, Any]) -> tuple[int, int] | None:
    """
    The (bottom, top) U range a placed mount occupies

    Args:
        mount (dict[str, Any]): A stored mount

    Returns:
        tuple[int, int] | None: The range; None for a mount without a whole-number start slot and a positive height
    """
    top: int | None = whole_number(mount.get(START_SLOT_FIELD))
    height: int | None = whole_number(mount.get(HEIGHT_FIELD))

    if top is None or height is None or height < 1:
        return None

    return top - height + 1, top


def placed_at(mount: dict[str, Any]) -> tuple[datetime, int]:
    """
    The order mounts were placed in: the last edit, else the creation, then the public_id

    Args:
        mount (dict[str, Any]): A stored mount

    Returns:
        tuple[datetime, int]: The sort key
    """
    moment: Any = mount.get(LAST_EDIT_TIME_FIELD) or mount.get(CREATION_TIME_FIELD)

    if not isinstance(moment, datetime):
        moment = NEVER
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment, mount[PUBLIC_ID_FIELD]


def collides(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """
    Whether two placed mounts compete for an area and share a U

    Args:
        first (dict[str, Any]): One stored mount
        second (dict[str, Any]): The other

    Returns:
        bool: True when they overlap
    """
    if second.get(AREA_FIELD) not in CONFLICTING_AREAS.get(first.get(AREA_FIELD), frozenset()):
        return False

    first_range: tuple[int, int] | None = slot_range(first)
    second_range: tuple[int, int] | None = slot_range(second)

    if first_range is None or second_range is None:
        return False

    return max(first_range[0], second_range[0]) <= min(first_range[1], second_range[1])


def displaced_mounts(mounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The mounts of one rack to unplace: each one that collides with a mount placed before it and kept

    Args:
        mounts (list[dict[str, Any]]): The rack's placed mounts

    Returns:
        list[dict[str, Any]]: The mounts to unplace, in the order they were placed
    """
    kept: list[dict[str, Any]] = []
    displaced: list[dict[str, Any]] = []

    for mount in sorted(mounts, key=placed_at):
        if any(collides(mount, earlier) for earlier in kept):
            displaced.append(mount)
        else:
            kept.append(mount)

    return displaced


def group_by_rack(mounts: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    """
    The placed mounts by their rack, leaving out a mount without an int public_id

    Args:
        mounts (list[dict[str, Any]]): Stored mounts

    Returns:
        dict[Any, list[dict[str, Any]]]: The mounts of each rack
    """
    racks: dict[Any, list[dict[str, Any]]] = {}

    for mount in mounts:
        if isinstance(mount.get(PUBLIC_ID_FIELD), int) and not isinstance(mount.get(PUBLIC_ID_FIELD), bool):
            racks.setdefault(mount.get(RACK_ID_FIELD), []).append(mount)

    return racks


def build_unplace_operations(displaced: list[dict[str, Any]], first_position: int) -> list[UpdateOne]:
    """
    The writes that move displaced mounts to the end of their rack's UNASSIGNED list

    Args:
        displaced (list[dict[str, Any]]): The rack's mounts to unplace
        first_position (int): The position the first of them takes

    Returns:
        list[UpdateOne]: One update per mount; the height is kept
    """
    return [
        UpdateOne({PUBLIC_ID_FIELD: mount[PUBLIC_ID_FIELD]}, {'$set': {
            AREA_FIELD: UNASSIGNED,
            START_SLOT_FIELD: None,
            POSITION_FIELD: first_position + offset,
        }})
        for offset, mount in enumerate(displaced)
    ]

# ---------------------------------------------- Update20261107 - CLASS ---------------------------------------------- #

class Update20261107(BaseDatabaseUpdate):
    """
    Unplaces the later of every two rack mounts stored in the same U range

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261107


    def description(self) -> str:
        return "Unplaces the later of every two rack mounts stored in the same U range"


    def start_update(self) -> None:
        """
        Reads the placed mounts once, unplaces the colliding ones rack by rack, then bumps the version

        Raises:
            UpdaterException: If a read or the write fails
        """
        try:
            placed: list[dict[str, Any]] = list(self.dbm.find(
                collection=MOUNTS_COLLECTION,
                db_name=self.db_name,
                filter={AREA_FIELD: {'$in': MAIN_AREAS}},
                projection=MOUNT_PROJECTION,
            ))
            operations: list[UpdateOne] = []

            for rack_id, mounts in group_by_rack(placed).items():
                displaced: list[dict[str, Any]] = displaced_mounts(mounts)

                if displaced:
                    operations.extend(build_unplace_operations(displaced, self.next_unassigned_position(rack_id)))
                    LOGGER.warning("[updater_20261107] Rack ID:%s - unplaced overlapping mount(s) %s", rack_id,
                                   [mount[PUBLIC_ID_FIELD] for mount in displaced])

            if operations:
                self.dbm.bulk_write(MOUNTS_COLLECTION, self.db_name, operations)

            LOGGER.info("[updater_20261107] Unplaced %s overlapping rack mount(s)", len(operations))

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def next_unassigned_position(self, rack_id: Any) -> int:
        """
        One past the highest integer position in a rack's UNASSIGNED list, 0 when it holds none

        Args:
            rack_id (Any): The rack's public_id

        Returns:
            int: The position the first unplaced mount takes
        """
        highest: list[dict[str, Any]] = list(self.dbm.find(
            collection=MOUNTS_COLLECTION,
            db_name=self.db_name,
            filter={RACK_ID_FIELD: rack_id, AREA_FIELD: UNASSIGNED, POSITION_FIELD: {'$type': INTEGER_BSON_TYPES}},
            projection=POSITION_PROJECTION,
            sort=[(POSITION_FIELD, DESCENDING)],
            limit=1,
        ))

        return highest[0][POSITION_FIELD] + 1 if highest else 0
