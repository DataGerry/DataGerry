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
Integration tests for the CmdbRackMount collection and its manager against a real MongoDB

Two things only a real database can show. First, that the declared unique index on 'object_id' really
refuses a second membership - the routes pre-check it, but two concurrent requests would both pass that
pre-check, so the index is the actual guarantee behind "one rack per object". Second, that the manager's
criteria match what is stored: the area filters, the append position and the bulk deletes are asserted
against seeded rows rather than mocked calls.

Note the fixture builds the model's declared indexes itself. The test database is never taken through
CollectionValidator (conftest drops the database and seeds users, nothing more), so its collections are
created implicitly by the first write and carry no index but '_id_'. Building them here is what the
application does at startup, and without it the uniqueness assertions below would silently pass on a
collection that has no constraint at all
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.models.rack_model import CmdbRackMount, RackArea
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 46101
OTHER_RACK_ID: int = 46102
OBJECT_ID: int = 46201
OTHER_OBJECT_ID: int = 46202
THIRD_OBJECT_ID: int = 46203

MOUNT_IDS: list[int] = [46301, 46302, 46303, 46304]
RACK_IDS: list[int] = [RACK_ID, OTHER_RACK_ID]


def _mount_doc(public_id: int, object_id: int, area: str, rack_id: int = RACK_ID,
               **overrides: Any) -> dict[str, Any]:
    """Builds a stored CmdbRackMount document"""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'rack_id': rack_id,
        'object_id': object_id,
        'area': area,
        'start_slot': None,
        'height': None,
        'position': None,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'last_edit_time': None,
    }
    doc.update(overrides)

    return doc


@pytest.fixture(name='mounts')
def fixture_mounts(database_manager: MongoDatabaseManager, database_name: str):
    """
    Gives the raw collection with the model's declared indexes built, cleared around each test

    The index build is what CollectionValidator does at application startup; the test database never
    goes through it (see the module docstring), so it happens here instead.
    """
    collection = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)
    collection.delete_many({'rack_id': {'$in': RACK_IDS}})
    database_manager.create_indexes(
        CmdbRackMount.COLLECTION, database_name, CmdbRackMount.get_index_keys(),
    )

    yield collection

    collection.delete_many({'rack_id': {'$in': RACK_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> RackMountsManager:
    """A real RackMountsManager backed by the test database"""
    return RackMountsManager(database_manager)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the unique index                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_object_id_index_is_unique_once_built(mounts) -> None:
    """
    The model's declaration really produces a unique index

    Guards against the declaration drifting to non-unique: nothing else in the codebase would notice,
    because index reconciliation is name-based and never compares options.
    """
    assert mounts.index_information()['object_id'].get('unique') is True


def test_a_second_membership_is_refused_by_the_database(mounts) -> None:
    """
    One rack per object, enforced where it cannot be raced

    The routes pre-check this for a readable error, but two concurrent requests would both pass the
    pre-check - only the index stops the second write.
    """
    mounts.insert_one(_mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.UNASSIGNED.value))

    with pytest.raises(DuplicateKeyError):
        mounts.insert_one(_mount_doc(MOUNT_IDS[1], OBJECT_ID, RackArea.FRONT.value))


def test_the_same_object_can_not_be_mounted_in_two_racks(mounts) -> None:
    """The membership is exclusive across racks, not just within one"""
    mounts.insert_one(_mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, rack_id=RACK_ID))

    with pytest.raises(DuplicateKeyError):
        mounts.insert_one(_mount_doc(MOUNT_IDS[1], OBJECT_ID, RackArea.FRONT.value, rack_id=OTHER_RACK_ID))


def test_different_objects_coexist_in_one_rack(mounts) -> None:
    """The index constrains the object, not the rack"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.FRONT.value),
    ])

    assert mounts.count_documents({'rack_id': RACK_ID}) == 2

# -------------------------------------------------------------------------------------------------------------------- #
#                                              manager reads                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_mount_of_object_finds_the_stored_row(mounts, manager: RackMountsManager) -> None:
    """The where-is-this-object lookup resolves against real data"""
    mounts.insert_one(_mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, start_slot=3, height=2))

    found = manager.get_mount_of_object(OBJECT_ID)

    assert found['public_id'] == MOUNT_IDS[0]
    assert found['start_slot'] == 3


def test_get_mount_of_object_is_none_for_an_unmounted_object(mounts, manager: RackMountsManager) -> None:
    """Not being mounted is not an error"""
    assert manager.get_mount_of_object(THIRD_OBJECT_ID) is None


def test_get_mounts_of_rack_returns_only_that_rack(mounts, manager: RackMountsManager) -> None:
    """A rack's listing does not leak another rack's members"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, rack_id=RACK_ID),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.FRONT.value, rack_id=OTHER_RACK_ID),
    ])

    assert [m['object_id'] for m in manager.get_mounts_of_rack(RACK_ID)] == [OBJECT_ID]


def test_get_mounts_of_rack_filters_by_area(mounts, manager: RackMountsManager) -> None:
    """The area filter hits the compound index's exact key"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, start_slot=1, height=1),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.LEFT.value, position=0),
    ])

    found = manager.get_mounts_of_rack(RACK_ID, RackArea.LEFT.value)

    assert [m['object_id'] for m in found] == [OTHER_OBJECT_ID]


def test_get_mounts_in_areas_spans_several_buckets(mounts, manager: RackMountsManager) -> None:
    """The overlap read collects every competing area in one query"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, start_slot=1, height=1),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.FULL_DEPTH.value, start_slot=5, height=1),
        _mount_doc(MOUNT_IDS[2], THIRD_OBJECT_ID, RackArea.LEFT.value, position=0),
    ])

    found = manager.get_mounts_in_areas(RACK_ID, {RackArea.FRONT.value, RackArea.FULL_DEPTH.value})

    assert sorted(m['object_id'] for m in found) == [OBJECT_ID, OTHER_OBJECT_ID]


def test_get_unassigned_mounts_returns_the_bucket(mounts, manager: RackMountsManager) -> None:
    """The unplaced members, including anything a shrink will displace later"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.UNASSIGNED.value, position=0, height=4),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.FRONT.value, start_slot=1, height=1),
    ])

    found = manager.get_unassigned_mounts(RACK_ID)

    assert [m['object_id'] for m in found] == [OBJECT_ID]
    assert found[0]['height'] == 4


def test_get_next_position_appends_after_the_stored_rows(mounts, manager: RackMountsManager) -> None:
    """The append index is computed from what is actually in the area"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.LEFT.value, position=0),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.LEFT.value, position=3),
    ])

    assert manager.get_next_position(RACK_ID, RackArea.LEFT.value) == 4


def test_count_mounts_counts_placed_and_unplaced_alike(mounts, manager: RackMountsManager) -> None:
    """Membership is membership, placed or not"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, start_slot=1, height=1),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.UNASSIGNED.value, position=0),
    ])

    assert manager.count_mounts_of_rack(RACK_ID) == 2

# -------------------------------------------------------------------------------------------------------------------- #
#                                             manager deletes                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_delete_mounts_of_rack_clears_only_that_rack(mounts, manager: RackMountsManager) -> None:
    """Deleting a rack's memberships leaves another rack's alone"""
    mounts.insert_many([
        _mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, rack_id=RACK_ID, start_slot=1, height=1),
        _mount_doc(MOUNT_IDS[1], OTHER_OBJECT_ID, RackArea.FRONT.value, rack_id=OTHER_RACK_ID,
                   start_slot=1, height=1),
    ])

    assert manager.delete_mounts_of_rack(RACK_ID) == 1
    assert mounts.count_documents({'rack_id': OTHER_RACK_ID}) == 1


def test_delete_mount_of_object_frees_the_object(mounts, manager: RackMountsManager) -> None:
    """After the delete the object may be mounted again - the unique index no longer holds it"""
    mounts.insert_one(_mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.FRONT.value, start_slot=1, height=1))

    assert manager.delete_mount_of_object(OBJECT_ID) == 1

    mounts.insert_one(_mount_doc(MOUNT_IDS[1], OBJECT_ID, RackArea.BACK.value, start_slot=1, height=1))
    assert mounts.count_documents({'object_id': OBJECT_ID}) == 1


def test_is_object_mounted_reflects_the_stored_state(mounts, manager: RackMountsManager) -> None:
    """The pre-check the routes rely on agrees with the database"""
    mounts.insert_one(_mount_doc(MOUNT_IDS[0], OBJECT_ID, RackArea.UNASSIGNED.value, position=0))

    assert manager.is_object_mounted(OBJECT_ID) is True
    assert manager.is_object_mounted(OBJECT_ID, exclude_mount_id=MOUNT_IDS[0]) is False
    assert manager.is_object_mounted(THIRD_OBJECT_ID) is False
