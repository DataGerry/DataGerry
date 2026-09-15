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
Integration tests for cmdb.database.updater.versions.updater_20260804 against a real MongoDB

Reproduces a pre-migration database by dropping the unique 'object_id' index (which the current model
declares, so a fresh test database already has it) and seeding an object that owns three location
nodes plus a child hanging off one of the duplicates. Asserts the migration keeps the node the
object's own location field points at, re-parents the child onto that keeper, re-points a second
object's location field away from a deleted duplicate, rebuilds the index as unique, bumps the
persisted updater version, is idempotent on a second run, and that a duplicate insert is refused
afterwards - the guarantee the whole migration exists to establish.
"""
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.type_model import FieldType
from cmdb.database.updater.versions.updater_20260804 import (
    OBJECT_ID_INDEX_NAME,
    Update20260804,
)
# -------------------------------------------------------------------------------------------------------------------- #

# The object owning the duplicated nodes, and the three nodes themselves
DUPLICATED_OBJECT_ID: int = 8810
MIRRORED_NODE_ID: int = 8822          # parent matches the object's location field -> the keeper
LOWEST_NODE_ID: int = 8820            # lower public_id, but the object does not point at it
THIRD_NODE_ID: int = 8824

# The parent the object's own location field records, and an unrelated parent the duplicates carry
MIRRORED_PARENT_ID: int = 8801
STALE_PARENT_ID: int = 8802

# A child node hanging off a duplicate, and the object owning it
CHILD_OBJECT_ID: int = 8811
CHILD_NODE_ID: int = 8830

NODE_IDS: list[int] = [LOWEST_NODE_ID, MIRRORED_NODE_ID, THIRD_NODE_ID, CHILD_NODE_ID]
OBJECT_IDS: list[int] = [DUPLICATED_OBJECT_ID, CHILD_OBJECT_ID]

TYPE_ID: int = 8850
LOCATION_FIELD_NAME: str = 'dg_location'

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'


def _location_doc(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """Builds a CmdbLocation document with the keys the model requires"""
    return {
        'public_id': public_id,
        'name': f'location-{public_id}',
        'parent': parent,
        'object_id': object_id,
        'type_id': TYPE_ID,
        'type_label': 'Rack',
        'type_icon': 'fas fa-cube',
        'type_selectable': True,
    }


def _object_doc(public_id: int, location_value: int) -> dict[str, Any]:
    """Builds a CmdbObject document whose only field is the location field"""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'fields': [
            {'name': LOCATION_FIELD_NAME, 'value': location_value, 'type': FieldType.LOCATION.value},
        ],
        'multi_data_sections': [],
    }


@pytest.fixture(name='legacy_locations')
def fixture_legacy_locations(database_manager: MongoDatabaseManager, database_name: str):
    """
    Recreates a pre-migration collection: no unique index, and one object owning three nodes

    The index has to be dropped before the duplicates can be inserted at all - which is exactly the
    state every database created before this migration is in.
    """
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    locations.delete_many({'public_id': {'$in': NODE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    if OBJECT_ID_INDEX_NAME in locations.index_information():
        locations.drop_index(OBJECT_ID_INDEX_NAME)

    locations.insert_many([
        _location_doc(LOWEST_NODE_ID, DUPLICATED_OBJECT_ID, STALE_PARENT_ID),
        _location_doc(MIRRORED_NODE_ID, DUPLICATED_OBJECT_ID, MIRRORED_PARENT_ID),
        _location_doc(THIRD_NODE_ID, DUPLICATED_OBJECT_ID, STALE_PARENT_ID),
        # A child of one of the duplicates - it must survive the fold, re-parented onto the keeper
        _location_doc(CHILD_NODE_ID, CHILD_OBJECT_ID, THIRD_NODE_ID),
    ])
    objects.insert_many([
        _object_doc(DUPLICATED_OBJECT_ID, MIRRORED_PARENT_ID),
        # This object's location field points at a node that is about to be deleted
        _object_doc(CHILD_OBJECT_ID, THIRD_NODE_ID),
    ])

    yield locations, objects

    locations.delete_many({'public_id': {'$in': NODE_IDS}})
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})

    # Restore the index the model declares, so later tests see a normal collection
    if OBJECT_ID_INDEX_NAME not in locations.index_information():
        database_manager.create_indexes(
            CmdbLocation.COLLECTION, database_name, CmdbLocation.get_index_keys(),
        )


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260804(database_manager, database_name).start_update()

# -------------------------------------------------------------------------------------------------------------------- #

def test_keeps_only_the_node_the_object_points_at(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The surviving node is the mirrored one, not simply the lowest public_id"""
    locations, _ = legacy_locations

    _run_migration(database_manager, database_name)

    remaining = list(locations.find({'object_id': DUPLICATED_OBJECT_ID}))

    assert len(remaining) == 1
    assert remaining[0]['public_id'] == MIRRORED_NODE_ID


def test_reparents_the_child_of_a_deleted_duplicate_onto_the_keeper(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A child must never be left pointing at a node that was deleted"""
    locations, _ = legacy_locations

    _run_migration(database_manager, database_name)

    child = locations.find_one({'public_id': CHILD_NODE_ID})

    assert child is not None
    assert child['parent'] == MIRRORED_NODE_ID


def test_repoints_the_mirrored_object_field_of_a_deleted_duplicate(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The object<->location mirror is kept consistent on the object side too"""
    _, objects = legacy_locations

    _run_migration(database_manager, database_name)

    child_object = objects.find_one({'public_id': CHILD_OBJECT_ID})
    location_field = next(
        field for field in child_object['fields'] if field['type'] == FieldType.LOCATION.value
    )

    assert location_field['value'] == MIRRORED_NODE_ID


def test_rebuilds_the_index_as_unique_and_bumps_the_version(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The migration leaves the declared unique index in place and records itself as applied"""
    locations, _ = legacy_locations
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    _run_migration(database_manager, database_name)

    assert locations.index_information()[OBJECT_ID_INDEX_NAME].get('unique') is True
    assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == 20260804


def test_duplicate_insert_is_refused_after_the_migration(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The point of the whole migration: a second node for one object can no longer be stored"""
    locations, _ = legacy_locations

    _run_migration(database_manager, database_name)

    with pytest.raises(DuplicateKeyError):
        locations.insert_one(_location_doc(8899, DUPLICATED_OBJECT_ID, STALE_PARENT_ID))

    locations.delete_many({'public_id': 8899})


def test_second_run_is_a_no_op(
        legacy_locations, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Re-running the completed migration changes nothing

    Covers the crash-then-restart case: the version is only written once both steps finished, so an
    interrupted run always starts over from the top and must be safe to repeat.
    """
    locations, objects = legacy_locations

    _run_migration(database_manager, database_name)

    nodes_after_first = sorted(doc['public_id'] for doc in locations.find({'object_id': DUPLICATED_OBJECT_ID}))
    child_after_first = locations.find_one({'public_id': CHILD_NODE_ID})['parent']

    _run_migration(database_manager, database_name)

    assert sorted(
        doc['public_id'] for doc in locations.find({'object_id': DUPLICATED_OBJECT_ID})
    ) == nodes_after_first
    assert locations.find_one({'public_id': CHILD_NODE_ID})['parent'] == child_after_first
    assert locations.index_information()[OBJECT_ID_INDEX_NAME].get('unique') is True
    assert objects.find_one({'public_id': DUPLICATED_OBJECT_ID}) is not None


def test_migration_on_a_clean_collection_only_builds_the_index(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A database with no duplicates is migrated by the index rebuild alone"""
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    if OBJECT_ID_INDEX_NAME in locations.index_information():
        locations.drop_index(OBJECT_ID_INDEX_NAME)

    count_before: int = locations.count_documents({})

    try:
        _run_migration(database_manager, database_name)

        assert locations.count_documents({}) == count_before
        assert locations.index_information()[OBJECT_ID_INDEX_NAME].get('unique') is True
    finally:
        if previous_setting is not None:
            settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
        else:
            settings.delete_many({'_id': UPDATER_SETTINGS_ID})
