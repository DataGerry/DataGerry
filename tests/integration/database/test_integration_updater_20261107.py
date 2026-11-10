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
Integration test for cmdb.database.updater.versions.updater_20261107 against a real MongoDB

Seeds what the placement race could leave - two mounts in one U range, a FULL_DEPTH mount across a FRONT one - next to
mounts that must not move (another rack, a BACK mount beside a FRONT one, adjacent ranges), runs the migration twice and
reads the stored mounts: the later of each pair is in UNASSIGNED after the rack's highest position there, its height
kept, and the second run changes nothing
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261107 import Update20261107
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 943201
CLEAN_RACK_ID: int = 943202
EARLY: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER: datetime = EARLY + timedelta(days=2)

KEPT_FRONT: int = 943210        # U10-U11, placed first
LATER_FRONT: int = 943211       # U11, placed later -> unplaced
LATER_FULL_DEPTH: int = 943212  # U9-U10 FULL_DEPTH, edited later -> unplaced
BACK_BESIDE: int = 943213       # U10-U11 BACK: no conflict with FRONT
ADJACENT_FRONT: int = 943214    # U12-U14: touches nothing
EXISTING_UNASSIGNED: int = 943215  # position 4 in UNASSIGNED
CLEAN_A: int = 943220           # another rack, no overlap
CLEAN_B: int = 943221
EXISTING_POSITION: int = 4
MOUNT_IDS: list[int] = [KEPT_FRONT, LATER_FRONT, LATER_FULL_DEPTH, BACK_BESIDE, ADJACENT_FRONT, EXISTING_UNASSIGNED,
                        CLEAN_A, CLEAN_B]


def _mount(public_id: int, area: str, start: int | None, height: int, created: datetime = EARLY,
           edited: datetime | None = None, rack_id: int = RACK_ID, position: int | None = None) -> dict[str, Any]:
    """A stored reservation row (no object_id, so the unique index stays out of it)."""
    return {
        RackMountKey.PUBLIC_ID.value: public_id, RackMountKey.RACK_ID.value: rack_id,
        RackMountKey.KIND.value: 'OCCUPANT', RackMountKey.LABEL.value: f'row-{public_id}',
        RackMountKey.AREA.value: area, RackMountKey.START_SLOT.value: start, RackMountKey.HEIGHT.value: height,
        RackMountKey.POSITION.value: position, RackMountKey.CREATION_TIME.value: created,
        RackMountKey.LAST_EDIT_TIME.value: edited,
    }


@pytest.fixture(name='mounts')
def fixture_mounts(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded rack mounts, removed afterwards"""
    collection = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)
    collection.delete_many({RackMountKey.PUBLIC_ID.value: {'$in': MOUNT_IDS}})
    collection.insert_many([
        _mount(KEPT_FRONT, RackArea.FRONT.value, 11, 2),
        _mount(LATER_FRONT, RackArea.FRONT.value, 11, 1, created=LATER),
        _mount(LATER_FULL_DEPTH, RackArea.FULL_DEPTH.value, 10, 2, edited=LATER + timedelta(hours=1)),
        _mount(BACK_BESIDE, RackArea.BACK.value, 11, 2, created=LATER),
        _mount(ADJACENT_FRONT, RackArea.FRONT.value, 14, 3, created=LATER),
        _mount(EXISTING_UNASSIGNED, RackArea.UNASSIGNED.value, None, 1, position=EXISTING_POSITION),
        _mount(CLEAN_A, RackArea.FRONT.value, 5, 2, rack_id=CLEAN_RACK_ID),
        _mount(CLEAN_B, RackArea.FRONT.value, 8, 2, rack_id=CLEAN_RACK_ID),
    ])
    yield collection
    collection.delete_many({RackMountKey.PUBLIC_ID.value: {'$in': MOUNT_IDS}})


def _stored(mounts: Any) -> dict[int, dict[str, Any]]:
    """The seeded mounts as stored, by id."""
    return {mount[RackMountKey.PUBLIC_ID.value]: mount
            for mount in mounts.find({RackMountKey.PUBLIC_ID.value: {'$in': MOUNT_IDS}}, {'_id': 0})}


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261107(database_manager, database_name).start_update()


def test_the_later_mount_of_each_overlap_is_unplaced(mounts: Any, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
    """Both colliders go to UNASSIGNED, in placement order, after position 4; heights kept, slots cleared"""
    _run(database_manager, database_name)

    stored = _stored(mounts)
    assert [(stored[mount_id][RackMountKey.AREA.value], stored[mount_id][RackMountKey.POSITION.value],
             stored[mount_id][RackMountKey.START_SLOT.value], stored[mount_id][RackMountKey.HEIGHT.value])
            for mount_id in (LATER_FRONT, LATER_FULL_DEPTH)] == [
        (RackArea.UNASSIGNED.value, EXISTING_POSITION + 1, None, 1),
        (RackArea.UNASSIGNED.value, EXISTING_POSITION + 2, None, 2),
    ]


def test_mounts_that_do_not_collide_stay_where_they_are(mounts: Any, database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
    """The first placement, BACK beside FRONT, an adjacent range and another rack are untouched"""
    before = _stored(mounts)

    _run(database_manager, database_name)

    after = _stored(mounts)
    for mount_id in (KEPT_FRONT, BACK_BESIDE, ADJACENT_FRONT, EXISTING_UNASSIGNED, CLEAN_A, CLEAN_B):
        assert after[mount_id] == before[mount_id]


def test_a_second_run_changes_nothing(mounts: Any, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
    """Re-run safe: the unplaced mounts carry no slot any more"""
    _run(database_manager, database_name)
    once = _stored(mounts)

    _run(database_manager, database_name)

    assert _stored(mounts) == once
