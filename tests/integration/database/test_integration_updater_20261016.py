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
Integration tests for cmdb.database.updater.versions.updater_20261016 against a real MongoDB

Seeds three instances of one pair, the reverse pair, the same objects under another relation and a lone instance,
with the unique index absent as on a database the rule has not reached; runs the migration and asserts:
  - the lowest public_id of the pair stays, the other two are gone; the reverse pair and the other relation stay
  - each removed instance has one DELETE history entry carrying its field values
  - the unique index is in place and refuses a duplicate through the manager, as the typed duplicate-key error
  - a second run changes nothing and writes no second entry; a run interrupted after an entry does not repeat it
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261016 import UPDATE_AUTHOR_NAME, Update20261016
from cmdb.manager import ObjectRelationsManager
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.object_relation_model.object_relation_constants import OBJECT_RELATION_PAIR_INDEX
from cmdb.utils import find_cause
from cmdb.errors.database import DocumentInsertDuplicateKeyError
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 98700
OTHER_RELATION_ID: int = 98701
PARENT_ID: int = 98710
CHILD_ID: int = 98711
LONE_CHILD_ID: int = 98712
KEPT_ID: int = 98801
REMOVED_IDS: list[int] = [98802, 98803]
REVERSE_ID: int = 98804
OTHER_RELATION_INSTANCE_ID: int = 98805
LONE_ID: int = 98806
NEW_ID: int = 98807
ALL_IDS: list[int] = [KEPT_ID, *REMOVED_IDS, REVERSE_ID, OTHER_RELATION_INSTANCE_ID, LONE_ID, NEW_ID]
KEPT_AFTER: list[int] = [KEPT_ID, REVERSE_ID, OTHER_RELATION_INSTANCE_ID, LONE_ID]


def _instance(public_id: int, relation_id: int = RELATION_ID, parent_id: int = PARENT_ID,
              child_id: int = CHILD_ID) -> dict[str, Any]:
    """A stored instance whose field value names it"""
    return {'public_id': public_id, 'relation_id': relation_id, 'relation_parent_id': parent_id,
            'relation_parent_type_id': 1, 'relation_child_id': child_id, 'relation_child_type_id': 2,
            'field_values': [{'name': 'port', 'value': f'eth-{public_id}'}], 'author_id': 1}


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The instances and their logs, the pair index absent; restored afterwards"""
    instances = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)

    def _purge() -> None:
        instances.delete_many({'public_id': {'$in': ALL_IDS}})
        logs.delete_many({'object_relation_id': {'$in': ALL_IDS}})

    _purge()
    had_index: bool = OBJECT_RELATION_PAIR_INDEX in instances.index_information()

    if had_index:
        instances.drop_index(OBJECT_RELATION_PAIR_INDEX)

    instances.insert_many([
        _instance(REMOVED_IDS[1]), _instance(KEPT_ID), _instance(REMOVED_IDS[0]),
        _instance(REVERSE_ID, parent_id=CHILD_ID, child_id=PARENT_ID),
        _instance(OTHER_RELATION_INSTANCE_ID, relation_id=OTHER_RELATION_ID),
        _instance(LONE_ID, child_id=LONE_CHILD_ID),
    ])

    yield instances, logs

    _purge()

    # Leave the index as the session had it: the run built it
    if not had_index and OBJECT_RELATION_PAIR_INDEX in instances.index_information():
        instances.drop_index(OBJECT_RELATION_PAIR_INDEX)


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261016(database_manager, database_name).start_update()


def _stored_ids(instances) -> list[int]:
    """The seeded instances still stored"""
    return sorted(row['public_id'] for row in instances.find({'public_id': {'$in': ALL_IDS}}))


def _removal_entries(logs) -> list[dict[str, Any]]:
    """This update's history entries, by instance"""
    return sorted(logs.find({'author_name': UPDATE_AUTHOR_NAME, 'object_relation_id': {'$in': ALL_IDS}}),
                  key=lambda entry: entry['object_relation_id'])


def test_the_oldest_of_the_pair_stays(database_manager, database_name, collections) -> None:
    """The reverse pair, the other relation and the lone instance are other pairs"""
    instances, _logs = collections

    _run(database_manager, database_name)

    assert _stored_ids(instances) == KEPT_AFTER


def test_each_removed_instance_leaves_its_field_values_in_its_history(database_manager, database_name,
                                                                     collections) -> None:
    """One DELETE entry per removed instance"""
    _instances, logs = collections

    _run(database_manager, database_name)

    assert [(entry['object_relation_id'], entry['action'], entry['changes']) for entry in _removal_entries(logs)] == [
        (public_id, 'DELETE', {'port': f'eth-{public_id}'}) for public_id in REMOVED_IDS
    ]


def test_the_unique_index_refuses_a_duplicate_through_the_manager(database_manager, database_name,
                                                                  collections) -> None:
    """The typed duplicate-key error the routes answer with their 400"""
    instances, _logs = collections

    _run(database_manager, database_name)

    assert instances.index_information()[OBJECT_RELATION_PAIR_INDEX].get('unique') is True
    with pytest.raises(ObjectRelationsManagerInsertError) as exc_info:
        ObjectRelationsManager(database_manager, database_name).insert_object_relation(_instance(NEW_ID))

    assert find_cause(exc_info.value, DocumentInsertDuplicateKeyError) is not None


def test_a_second_run_changes_nothing(database_manager, database_name, collections) -> None:
    """Idempotent: same instances, no second entry"""
    instances, logs = collections
    _run(database_manager, database_name)

    _run(database_manager, database_name)

    assert _stored_ids(instances) == KEPT_AFTER
    assert len(_removal_entries(logs)) == len(REMOVED_IDS)


def test_a_run_interrupted_after_an_entry_does_not_repeat_it(database_manager, database_name, collections) -> None:
    """The entry is written, the delete never happened - the next run deletes without a second entry"""
    _instances, logs = collections
    logs.insert_one({'public_id': 98899, 'object_relation_id': REMOVED_IDS[0], 'author_name': UPDATE_AUTHOR_NAME,
                     'action': 'DELETE', 'changes': {}})

    _run(database_manager, database_name)

    assert [entry['object_relation_id'] for entry in _removal_entries(logs)] == REMOVED_IDS
