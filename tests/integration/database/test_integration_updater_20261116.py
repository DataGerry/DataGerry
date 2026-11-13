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
Integration tests for cmdb.database.updater.versions.updater_20261116 and the index it hands over to, against a real
MongoDB

Builds the predecessor ``special_type`` index on the types collection the way an existing install holds it, seeds Types
with and without the system marker, runs the migration, and asserts:

  - the predecessor is gone
  - every Type without the marker now carries ``system_type: false``; a stored ``true`` is left alone
  - a second run changes nothing; a collection that never had the predecessor is a no-op for the index

and, on a scratch collection behind the indexes CmdbType declares, that the successor refuses a second RACK Type but
stores any number of PERSON and PERSON_GROUP Types and of Types without a marker
"""
from typing import Any, Iterator

import pytest
from pymongo import ASCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261116 import REPLACED_INDEX, Update20261116
from cmdb.models.type_model import CmdbType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

PREDECESSOR: IndexModel = IndexModel([('special_type', ASCENDING)], name=REPLACED_INDEX, unique=True,
                                     partialFilterExpression={'special_type': {'$gt': ''}})
SCRATCH_COLLECTION: str = 'framework.types.index-scratch'

UNMARKED_TYPE_ID: int = 47901
SYSTEM_TYPE_ID: int = 47902
SEEDED_TYPE_IDS: list[int] = [UNMARKED_TYPE_ID, SYSTEM_TYPE_ID]


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The types collection with the predecessor index and two seeded Types; both removed again after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})
    types.insert_many([
        {'public_id': UNMARKED_TYPE_ID, 'name': 'updater-unmarked', 'special_type': ''},
        {'public_id': SYSTEM_TYPE_ID, 'name': 'updater-system', 'special_type': '', 'system_type': True},
    ])
    types.create_indexes([PREDECESSOR])

    yield types

    types.delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})
    if REPLACED_INDEX in types.index_information():
        types.drop_index(REPLACED_INDEX)


def _system_marker(types: Any, public_id: int) -> Any:
    """The stored marker of one seeded Type, or the absence of it"""
    return types.find_one({'public_id': public_id}).get('system_type', 'absent')


def test_the_predecessor_is_dropped(types: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The index that refused a second PERSON type is gone"""
    Update20261116(database_manager, database_name).start_update()

    assert REPLACED_INDEX not in types.index_information()


def test_every_type_without_the_marker_is_no_system_type(types: Any, database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
    """Written, not defaulted; a stored true stays"""
    assert _system_marker(types, UNMARKED_TYPE_ID) == 'absent'

    Update20261116(database_manager, database_name).start_update()

    assert _system_marker(types, UNMARKED_TYPE_ID) is False
    assert _system_marker(types, SYSTEM_TYPE_ID) is True
    assert types.count_documents({'system_type': {'$exists': False}}) == 0


def test_a_second_run_changes_nothing(types: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-run safe - neither the indexes nor the seeded Types change"""
    Update20261116(database_manager, database_name).start_update()
    indexes: dict[str, Any] = types.index_information()
    seeded: list[dict[str, Any]] = list(types.find({'public_id': {'$in': SEEDED_TYPE_IDS}}, {'_id': 0}))

    Update20261116(database_manager, database_name).start_update()

    assert types.index_information() == indexes
    assert list(types.find({'public_id': {'$in': SEEDED_TYPE_IDS}}, {'_id': 0})) == seeded


def test_a_new_install_without_the_predecessor_is_a_no_op(types: Any, database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
    """Nothing to drop is no failure"""
    types.drop_index(REPLACED_INDEX)
    before: dict[str, Any] = types.index_information()

    Update20261116(database_manager, database_name).start_update()

    assert types.index_information() == before


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """An empty collection behind every index CmdbType declares; dropped after"""
    scratch = database_manager.get_collection(SCRATCH_COLLECTION, database_name)
    scratch.drop()
    scratch.create_indexes(CmdbType.get_index_keys())

    yield scratch

    scratch.drop()


def _marked(public_id: int, marker: Any) -> dict[str, Any]:
    """A minimal Type document with the marker"""
    return {'public_id': public_id, 'name': f'scratch-{public_id}', 'author_id': 1,
            TypeSchemaKey.SPECIAL_TYPE.value: marker}


def test_the_successor_refuses_a_second_singleton(scratch: Any) -> None:
    """A singleton SpecialType stays one Type's"""
    scratch.insert_one(_marked(1, 'RACK'))

    with pytest.raises(DuplicateKeyError):
        scratch.insert_one(_marked(2, 'RACK'))


def test_the_successor_stores_several_person_and_group_types(scratch: Any) -> None:
    """And any number of Types without a marker, null or empty"""
    scratch.insert_many([
        _marked(1, 'PERSON'), _marked(2, 'PERSON'), _marked(3, 'PERSON_GROUP'), _marked(4, 'PERSON_GROUP'),
        _marked(5, None), _marked(6, None), _marked(7, ''), _marked(8, ''),
    ])

    assert scratch.count_documents({}) == 8
