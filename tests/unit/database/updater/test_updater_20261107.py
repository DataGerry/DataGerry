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
Unit tests for cmdb.database.updater.versions.updater_20261107

The migration unplaces the later of every two rack mounts stored in the same U range. Its run against a real database
is its own integration test; this module owns the frozen literals, the collision rule (areas, ranges, a mount without
slots), the order mounts count as placed in, the unplace statements, the version bump and the failure tail
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from pymongo import UpdateOne

from cmdb.database.updater.versions import updater_20261107 as module
from cmdb.database.updater.versions.updater_20261107 import (
    Update20261107,
    build_unplace_operations,
    collides,
    displaced_mounts,
    group_by_rack,
    placed_at,
    slot_range,
    whole_number,
)
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261107
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'mounts gone'
RACK_ID: int = 61
OTHER_RACK_ID: int = 62
FIRST_FREE_POSITION: int = 7
EARLY: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER: datetime = EARLY + timedelta(days=3)
LATEST: datetime = EARLY + timedelta(days=9)


def _mount(public_id: int, area: str, start: Any, height: Any, created: Any = EARLY, edited: Any = None,
           rack_id: Any = RACK_ID) -> dict[str, Any]:
    """A stored mount, as the migration's projection reads it."""
    return {'public_id': public_id, 'rack_id': rack_id, 'area': area, 'start_slot': start, 'height': height,
            'creation_time': created, 'last_edit_time': edited}


def _updater(mounts: list[dict[str, Any]], highest_position: int | None = None) -> tuple[Update20261107, MagicMock]:
    """The migration over a mocked database manager: the first find answers the mounts, later ones the position"""
    dbm = MagicMock()
    position_read: list[dict[str, Any]] = [] if highest_position is None else [{'position': highest_position}]
    dbm.find.side_effect = lambda **kwargs: iter(mounts if kwargs.get('limit') is None else position_read)
    updater = Update20261107(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.MOUNTS_COLLECTION, CmdbRackMount.COLLECTION),
    (module.PUBLIC_ID_FIELD, RackMountKey.PUBLIC_ID.value),
    (module.RACK_ID_FIELD, RackMountKey.RACK_ID.value),
    (module.AREA_FIELD, RackMountKey.AREA.value),
    (module.START_SLOT_FIELD, RackMountKey.START_SLOT.value),
    (module.HEIGHT_FIELD, RackMountKey.HEIGHT.value),
    (module.POSITION_FIELD, RackMountKey.POSITION.value),
    (module.CREATION_TIME_FIELD, RackMountKey.CREATION_TIME.value),
    (module.LAST_EDIT_TIME_FIELD, RackMountKey.LAST_EDIT_TIME.value),
    (module.FRONT, RackArea.FRONT.value),
    (module.BACK, RackArea.BACK.value),
    (module.FULL_DEPTH, RackArea.FULL_DEPTH.value),
    (module.UNASSIGNED, RackArea.UNASSIGNED.value),
])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The migration's copies of the names still mean what the code means today"""
    assert frozen == live


def test_the_frozen_conflict_table_matches_the_live_rule() -> None:
    """FRONT/BACK compete with themselves and FULL_DEPTH, FULL_DEPTH with every main area"""
    for area in RackArea.get_main_areas():
        live: set[str] = {competing.value for competing in RackArea.get_conflicting_areas(area)}
        assert module.CONFLICTING_AREAS[area.value] == live


@pytest.mark.parametrize('value, expected', [(3, 3), (3.0, 3), (3.5, None), ('3', None), (True, None), (None, None)])
def test_whole_number(value: Any, expected: int | None) -> None:
    """An int or a fraction-free float; nothing else"""
    assert whole_number(value) == expected


@pytest.mark.parametrize('start, height, expected', [(25, 3, (23, 25)), (1, 1, (1, 1)), (25, 0, None),
                                                     (None, 2, None), (25, None, None)])
def test_slot_range(start: Any, height: Any, expected: tuple[int, int] | None) -> None:
    """A mount reaches down from its start slot"""
    assert slot_range(_mount(1, 'FRONT', start, height)) == expected


@pytest.mark.parametrize('first, second, expected', [
    ('FRONT', 'FRONT', True), ('FRONT', 'FULL_DEPTH', True), ('FULL_DEPTH', 'BACK', True),
    ('FRONT', 'BACK', False), ('BACK', 'FRONT', False), ('FRONT', 'LEFT', False), ('UNASSIGNED', 'FRONT', False),
])
def test_collision_needs_competing_areas(first: str, second: str, expected: bool) -> None:
    """Same range, so only the areas decide"""
    assert collides(_mount(1, first, 10, 2), _mount(2, second, 10, 2)) is expected


@pytest.mark.parametrize('other_start, other_height, expected', [(12, 3, True), (11, 2, True), (8, 1, True),
                                                                 (13, 3, False), (7, 1, False)])
def test_collision_needs_a_shared_u(other_start: int, other_height: int, expected: bool) -> None:
    """U8-U10 against another range: touching ends collide, adjacent ones do not"""
    assert collides(_mount(1, 'FRONT', 10, 3), _mount(2, 'FRONT', other_start, other_height)) is expected


def test_a_mount_without_slots_collides_with_nothing() -> None:
    """No geometry, no part in the check"""
    assert not collides(_mount(1, 'FRONT', None, 2), _mount(2, 'FRONT', 10, 2))


def test_placed_at_reads_the_last_edit_then_the_creation_then_the_id() -> None:
    """The later placement is the one that broke the rule"""
    edited = _mount(9, 'FRONT', 1, 1, created=EARLY, edited=LATEST)
    created = _mount(3, 'FRONT', 1, 1, created=LATER)
    untimed = _mount(5, 'FRONT', 1, 1, created=None)
    naive = _mount(4, 'FRONT', 1, 1, created=LATER.replace(tzinfo=None))

    assert sorted([edited, created, untimed, naive], key=placed_at) == [untimed, created, naive, edited]


def test_the_later_of_two_overlapping_mounts_is_displaced() -> None:
    """Placed second, unplaced"""
    first = _mount(2, 'FRONT', 10, 2, created=EARLY)
    second = _mount(1, 'FULL_DEPTH', 11, 4, created=LATER)

    assert displaced_mounts([second, first]) == [second]


def test_a_mount_overlapping_only_a_displaced_one_is_kept() -> None:
    """A stays, B overlaps A and goes, C overlaps only B and stays"""
    kept_a = _mount(1, 'FRONT', 10, 2, created=EARLY)
    displaced_b = _mount(2, 'FRONT', 12, 3, created=LATER)
    kept_c = _mount(3, 'FRONT', 13, 1, created=LATEST)

    assert displaced_mounts([kept_c, displaced_b, kept_a]) == [displaced_b]


def test_mounts_are_grouped_by_rack_and_unusable_ids_left_out() -> None:
    """Each rack is judged on its own"""
    mounts = [_mount(1, 'FRONT', 1, 1), _mount(2, 'FRONT', 1, 1, rack_id=OTHER_RACK_ID), _mount(True, 'FRONT', 1, 1),
              {**_mount(3, 'FRONT', 1, 1), 'public_id': None}]

    assert {rack: [mount['public_id'] for mount in rack_mounts]
            for rack, rack_mounts in group_by_rack(mounts).items()} == {RACK_ID: [1], OTHER_RACK_ID: [2]}


def test_unplacing_moves_to_unassigned_appended_and_keeps_the_height() -> None:
    """Area UNASSIGNED, slot cleared, positions from the first free one; the height untouched"""
    operations = build_unplace_operations([_mount(4, 'FRONT', 10, 2), _mount(6, 'BACK', 3, 1)], FIRST_FREE_POSITION)

    assert operations == [
        UpdateOne({'public_id': 4}, {'$set': {'area': 'UNASSIGNED', 'start_slot': None, 'position': 7}}),
        UpdateOne({'public_id': 6}, {'$set': {'area': 'UNASSIGNED', 'start_slot': None, 'position': 8}}),
    ]


def test_the_version_and_description() -> None:
    """The date the version list names"""
    updater, _dbm = _updater([])

    assert updater.creation_date() == CREATION_DATE
    assert 'same U range' in updater.description()


def test_the_overlaps_are_unplaced_in_one_write_then_the_version() -> None:
    """One read of the placed mounts, one position read per affected rack, one bulk write"""
    updater, dbm = _updater([_mount(1, 'FRONT', 10, 2, created=EARLY), _mount(2, 'FRONT', 10, 1, created=LATER),
                             _mount(3, 'BACK', 10, 2)], highest_position=FIRST_FREE_POSITION - 1)

    updater.start_update()

    mounts_read, position_read = (call.kwargs for call in dbm.find.call_args_list)
    assert mounts_read['filter'] == {'area': {'$in': ['FRONT', 'BACK', 'FULL_DEPTH']}}
    assert position_read['filter'] == {'rack_id': RACK_ID, 'area': 'UNASSIGNED', 'position': {'$type': ['int', 'long']}}
    collection, database, operations = dbm.bulk_write.call_args.args
    assert (collection, database) == (CmdbRackMount.COLLECTION, DATABASE_NAME)
    assert operations == [UpdateOne({'public_id': 2}, {'$set': {
        'area': 'UNASSIGNED', 'start_slot': None, 'position': FIRST_FREE_POSITION}})]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_an_empty_unassigned_list_starts_at_zero() -> None:
    """No stored position: the first unplaced mount takes 0"""
    updater, dbm = _updater([_mount(1, 'FRONT', 10, 2, created=EARLY), _mount(2, 'FRONT', 10, 1, created=LATER)])

    updater.start_update()

    assert dbm.bulk_write.call_args.args[2][0]._doc['$set']['position'] == 0  # pylint: disable=protected-access


def test_no_overlap_writes_nothing_and_still_bumps() -> None:
    """Nothing to repair: no write"""
    updater, dbm = _updater([_mount(1, 'FRONT', 10, 2), _mount(2, 'BACK', 10, 2)])

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failing_write_is_the_updater_exception_carrying_the_error() -> None:
    """The tail every migration shares: the error itself, not its text"""
    updater, dbm = _updater([_mount(1, 'FRONT', 10, 2, created=EARLY), _mount(2, 'FRONT', 10, 1, created=LATER)])
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
