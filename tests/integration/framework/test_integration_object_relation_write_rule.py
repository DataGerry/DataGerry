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
Integration tests for the object-relation write rule against a real MongoDB

The conditions are real queries here, so what MongoDB makes of them is pinned: a relation with a denied type at
either end is found by the bulk check and left alone by every delete, and a relation with no type stamped on a side
(null) is neither found nor protected - the rule of the reads, where a side with no type is not refused.
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    abort_if_selection_holds_hidden_relation,
    build_readable_object_relation_criteria,
    delete_object_relations,
)
# -------------------------------------------------------------------------------------------------------------------- #

READABLE_ID: int = 88701
HIDDEN_CHILD_ID: int = 88702
HIDDEN_PARENT_ID: int = 88703
UNSTAMPED_ID: int = 88704
MISSING_ID: int = 88799
SEEDED_IDS: list[int] = [READABLE_ID, HIDDEN_CHILD_ID, HIDDEN_PARENT_ID, UNSTAMPED_ID]

READABLE_TYPE_ID: int = 88711
DENIED_TYPE_ID: int = 88712
DENIED: list[int] = [DENIED_TYPE_ID]


def _document(public_id: int, parent_type_id: int | None, child_type_id: int | None) -> dict[str, Any]:
    """A stored CmdbObjectRelation with the given stamped types"""
    return {
        'public_id': public_id, 'relation_id': 1,
        'relation_parent_id': 700, 'relation_parent_type_id': parent_type_id,
        'relation_child_id': 800, 'relation_child_type_id': child_type_id,
        'field_values': [],
    }


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The four seeded relations, purged before and after"""
    collection = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})
    collection.insert_many([
        _document(READABLE_ID, READABLE_TYPE_ID, READABLE_TYPE_ID),
        _document(HIDDEN_CHILD_ID, READABLE_TYPE_ID, DENIED_TYPE_ID),
        _document(HIDDEN_PARENT_ID, DENIED_TYPE_ID, READABLE_TYPE_ID),
        _document(UNSTAMPED_ID, None, None),
    ])

    yield collection

    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ObjectRelationsManager:
    """An ObjectRelationsManager on the test database"""
    return ObjectRelationsManager(database_manager)


def _stored_ids(collection: Any) -> set[int]:
    """The seeded relations still stored"""
    return {document['public_id'] for document in collection.find({'public_id': {'$in': SEEDED_IDS}})}


@pytest.mark.usefixtures('collection')
class TestTheBulkCheck:
    """``abort_if_selection_holds_hidden_relation`` with a real query"""

    @pytest.mark.parametrize('hidden_id', [HIDDEN_CHILD_ID, HIDDEN_PARENT_ID], ids=['child', 'parent'])
    def test_a_hidden_relation_in_the_selection_is_found_and_named(self, manager: ObjectRelationsManager,
                                                                   hidden_id: int) -> None:
        """A denied type on either side"""
        with pytest.raises(HTTPException) as caught:
            abort_if_selection_holds_hidden_relation(manager, [READABLE_ID, hidden_id, MISSING_ID], DENIED)

        assert caught.value.code == HTTPStatus.FORBIDDEN
        assert str(hidden_id) in caught.value.description

    def test_readable_unstamped_and_missing_relations_pass(self, manager: ObjectRelationsManager) -> None:
        """A null stamped type is not a denied one"""
        abort_if_selection_holds_hidden_relation(manager, [READABLE_ID, UNSTAMPED_ID, MISSING_ID], DENIED)


class TestTheDeletes:
    """Every delete runs under the readable condition"""

    def test_a_bulk_delete_leaves_the_hidden_relations_alone(self, collection, manager: ObjectRelationsManager) -> None:
        """The guard behind the route's check: only the readable and the unstamped ones go"""
        deleted: list[dict[str, Any]] = []

        delete_object_relations(manager, SEEDED_IDS, deleted, DENIED)

        assert [document['public_id'] for document in deleted] == [READABLE_ID, UNSTAMPED_ID]
        assert _stored_ids(collection) == {HIDDEN_CHILD_ID, HIDDEN_PARENT_ID}

    def test_with_nothing_denied_every_relation_is_deleted(self, collection, manager: ObjectRelationsManager) -> None:
        """The admin's case"""
        delete_object_relations(manager, SEEDED_IDS, [], [])

        assert not _stored_ids(collection)

    @pytest.mark.parametrize('public_id, deleted', [
        (READABLE_ID, True), (UNSTAMPED_ID, True), (HIDDEN_CHILD_ID, False), (HIDDEN_PARENT_ID, False),
    ], ids=['readable', 'unstamped', 'hidden-child', 'hidden-parent'])
    def test_the_single_delete_criteria(self, collection, manager: ObjectRelationsManager, public_id: int,
                                        deleted: bool) -> None:
        """What the single DELETE route's atomic read-and-delete matches"""
        answer = manager.find_one_and_delete(build_readable_object_relation_criteria(public_id, DENIED))

        assert (answer is not None) is deleted
        assert (public_id in _stored_ids(collection)) is not deleted
