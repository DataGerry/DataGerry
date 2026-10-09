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
Functional coverage of what deleting a CmdbObject does to its CmdbObjectRelations

Over the single and the bulk delete route: every relation the object takes part in - as parent or as child -
is removed, each with exactly one DELETE log naming its parent and child, and a relation between two other
objects is left alone. The bulk route clears the relations of its whole selection at once
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.object_relation_log_constants import ObjectRelationLogKey
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from tests.functional.framework.objects.objects_route_helpers import (
    ROUTE_URL,
    drop_object,
    insert_object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

DELETED_OBJECT_ID: int = 9461
SECOND_DELETED_OBJECT_ID: int = 9462
BYSTANDER_A_ID: int = 9463
BYSTANDER_B_ID: int = 9464
OBJECT_IDS: list[int] = [DELETED_OBJECT_ID, SECOND_DELETED_OBJECT_ID, BYSTANDER_A_ID, BYSTANDER_B_ID]

RELATION_DEFINITION_ID: int = 9470
AS_PARENT_ID: int = 9471     # deleted object -> bystander A
AS_CHILD_ID: int = 9472      # bystander B -> deleted object
SECOND_ID: int = 9473        # second deleted object -> bystander A
UNTOUCHED_ID: int = 9474     # bystander A -> bystander B
RELATION_IDS: list[int] = [AS_PARENT_ID, AS_CHILD_ID, SECOND_ID, UNTOUCHED_ID]

DELETE_ACTION: str = 'DELETE'
OBJECT_VALUE: str = 'relation-cascade'


def _relation(public_id: int, parent_id: int, child_id: int) -> dict[str, Any]:
    """A stored CmdbObjectRelation between two objects."""
    return {
        ObjectRelationKey.PUBLIC_ID.value: public_id,
        'relation_id': RELATION_DEFINITION_ID,
        ObjectRelationKey.RELATION_PARENT_ID.value: parent_id,
        ObjectRelationKey.RELATION_CHILD_ID.value: child_id,
        'field_values': [],
    }


@pytest.fixture(name='related_objects')
def fixture_related_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Four objects and four relations between them; everything (and every relation log) removed afterwards."""
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)
    logs.delete_many({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS}})

    for object_id in OBJECT_IDS:
        insert_object_doc(database_manager, database_name, object_id, OBJECT_VALUE)

    relations.insert_many([
        _relation(AS_PARENT_ID, DELETED_OBJECT_ID, BYSTANDER_A_ID),
        _relation(AS_CHILD_ID, BYSTANDER_B_ID, DELETED_OBJECT_ID),
        _relation(SECOND_ID, SECOND_DELETED_OBJECT_ID, BYSTANDER_A_ID),
        _relation(UNTOUCHED_ID, BYSTANDER_A_ID, BYSTANDER_B_ID),
    ])

    yield relations, logs

    relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}})
    logs.delete_many({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS}})
    for object_id in OBJECT_IDS:
        drop_object(database_manager, database_name, object_id)


def _stored(relations: Any) -> list[int]:
    """The fixture's relations still stored."""
    return sorted(doc[ObjectRelationKey.PUBLIC_ID.value] for doc in relations.find(
        {ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}},
    ))


def _delete_logs(logs: Any) -> dict[int, list[tuple[int, int]]]:
    """relation id -> the (parent, child) of every DELETE log written for it."""
    found: dict[int, list[tuple[int, int]]] = {}

    for log in logs.find({ObjectRelationLogKey.OBJECT_RELATION_ID.value: {'$in': RELATION_IDS},
                          ObjectRelationLogKey.ACTION.value: DELETE_ACTION}):
        found.setdefault(log[ObjectRelationLogKey.OBJECT_RELATION_ID.value], []).append((
            log[ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value],
            log[ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value],
        ))

    return found


def test_the_single_delete_removes_and_logs_every_relation_of_the_object(rest_api, related_objects) -> None:
    """As parent and as child, one DELETE log each; the other objects' relations stay"""
    relations, logs = related_objects

    response = rest_api.delete(f'{ROUTE_URL}/{DELETED_OBJECT_ID}')

    assert response.status_code == HTTPStatus.OK
    assert _stored(relations) == [SECOND_ID, UNTOUCHED_ID]
    assert _delete_logs(logs) == {
        AS_PARENT_ID: [(DELETED_OBJECT_ID, BYSTANDER_A_ID)],
        AS_CHILD_ID: [(BYSTANDER_B_ID, DELETED_OBJECT_ID)],
    }


def test_the_bulk_delete_removes_and_logs_the_relations_of_the_whole_selection(rest_api, related_objects) -> None:
    """Both targets' relations go, each logged once; the relation between the bystanders stays"""
    relations, logs = related_objects

    response = rest_api.delete(f'{ROUTE_URL}/delete/{DELETED_OBJECT_ID},{SECOND_DELETED_OBJECT_ID}')

    assert response.status_code == HTTPStatus.OK
    assert _stored(relations) == [UNTOUCHED_ID]
    assert _delete_logs(logs) == {
        AS_PARENT_ID: [(DELETED_OBJECT_ID, BYSTANDER_A_ID)],
        AS_CHILD_ID: [(BYSTANDER_B_ID, DELETED_OBJECT_ID)],
        SECOND_ID: [(SECOND_DELETED_OBJECT_ID, BYSTANDER_A_ID)],
    }


def test_an_object_without_relations_is_deleted_without_relation_logs(rest_api, related_objects) -> None:
    """Deleting a bystander after its relations are gone writes no relation log"""
    relations, logs = related_objects
    relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': RELATION_IDS}})

    response = rest_api.delete(f'{ROUTE_URL}/{BYSTANDER_B_ID}')

    assert response.status_code == HTTPStatus.OK
    assert not _delete_logs(logs)
