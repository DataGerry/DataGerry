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
Integration tests for the atomic read-and-delete behind the ObjectRelation bulk delete, against a real MongoDB

``BaseManager.find_one_and_delete`` (through ``ObjectRelationsManager``) and ``delete_object_relations``. Pinned:

  - the call answers the stored document it removed, without `_id`, and None when nothing matched
  - of two deletes of the same relation exactly one gets the document - also when they race on threads, which is
    what lets the route log a deletion once
  - running the bulk deletion twice collects everything once and nothing the second time (re-run safe)
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import delete_object_relations
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_ID: int = 88601
SECOND_ID: int = 88602
RACED_ID: int = 88603
MISSING_ID: int = 88699
SEEDED_IDS: list[int] = [FIRST_ID, SECOND_ID, RACED_ID]

# How many deletes race for the one relation
RACING_DELETES: int = 8


def _document(public_id: int) -> dict[str, Any]:
    """A stored CmdbObjectRelation, carrying a value to recognise it by"""
    return {
        'public_id': public_id,
        'relation_id': 1,
        'relation_parent_id': 700,
        'relation_child_id': 800,
        'field_values': [{'name': 'note', 'value': f'relation-{public_id}'}],
    }


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The object relation collection holding the seeded relations, purged before and after"""
    collection = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})
    collection.insert_many([_document(public_id) for public_id in SEEDED_IDS])

    yield collection

    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ObjectRelationsManager:
    """An ObjectRelationsManager on the test database"""
    return ObjectRelationsManager(database_manager)


class TestFindOneAndDelete:
    """The atomic step itself"""

    def test_answers_the_document_it_removed(self, collection, manager: ObjectRelationsManager) -> None:
        """The stored document, `_id` left out, and it is gone"""
        deleted = manager.find_one_and_delete({'public_id': FIRST_ID})

        assert deleted == _document(FIRST_ID)
        assert collection.count_documents({'public_id': FIRST_ID}) == 0
        assert collection.count_documents({'public_id': SECOND_ID}) == 1

    def test_answers_none_when_nothing_matched(self, collection, manager: ObjectRelationsManager) -> None:
        """No document, nothing deleted"""
        assert manager.find_one_and_delete({'public_id': MISSING_ID}) is None
        assert collection.count_documents({'public_id': {'$in': SEEDED_IDS}}) == len(SEEDED_IDS)

    @pytest.mark.usefixtures('collection')
    def test_a_second_delete_of_the_same_relation_gets_nothing(self, manager: ObjectRelationsManager) -> None:
        """The second caller is told nothing was there to delete"""
        manager.find_one_and_delete({'public_id': FIRST_ID})

        assert manager.find_one_and_delete({'public_id': FIRST_ID}) is None

    def test_of_racing_deletes_exactly_one_gets_the_document(
        self, collection, manager: ObjectRelationsManager,
    ) -> None:
        """Concurrent requests for one relation: one of them deleted it, the rest learn nothing was there"""
        with ThreadPoolExecutor(max_workers=RACING_DELETES) as pool:
            answers = list(pool.map(
                lambda _attempt: manager.find_one_and_delete({'public_id': RACED_ID}), range(RACING_DELETES),
            ))

        assert [answer for answer in answers if answer is not None] == [_document(RACED_ID)]
        assert collection.count_documents({'public_id': RACED_ID}) == 0


class TestDeleteObjectRelations:
    """The bulk deletion the route runs, one atomic step per id"""

    def test_collects_each_stored_relation_once(self, collection, manager: ObjectRelationsManager) -> None:
        """A missing id is skipped, the rest collected in order and gone"""
        deleted: list[dict[str, Any]] = []

        delete_object_relations(manager, [SECOND_ID, MISSING_ID, FIRST_ID], deleted)

        assert deleted == [_document(SECOND_ID), _document(FIRST_ID)]
        assert collection.count_documents({'public_id': {'$in': [FIRST_ID, SECOND_ID]}}) == 0

    def test_a_second_run_collects_nothing(self, collection, manager: ObjectRelationsManager) -> None:
        """Re-run safe: the same selection again deletes and collects nothing, and touches nothing else"""
        delete_object_relations(manager, [FIRST_ID, SECOND_ID], [])
        second_run: list[dict[str, Any]] = []

        delete_object_relations(manager, [FIRST_ID, SECOND_ID], second_run)

        assert not second_run
        assert collection.count_documents({'public_id': RACED_ID}) == 1
