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
Functional tests: a CmdbRelation update that drops an allowed type records the instances it deletes

``PUT /relations/<id>`` deletes every CmdbObjectRelation whose parent or child CmdbType the update no longer allows.
Pinned:

  - each deleted instance gets one DELETE history entry, on the parent side and on the child side
  - instances of the kept types are neither deleted nor logged
  - the answer carries ``deleted_object_relations`` next to the relation: the count, 0 when nothing went
  - a cascade failing part-way answers 500 (the relation IS updated) and the instance deleted before it is logged
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.log_model.cmdb_object_relation_log import CmdbObjectRelationLog
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import RelationUpdateResponseKey
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/relations'
DELETE_ACTION: str = 'DELETE'
DELETED_KEY: str = RelationUpdateResponseKey.DELETED_OBJECT_RELATIONS.value

PARENT_TYPE_ID: int = 79301
SECOND_PARENT_TYPE_ID: int = 79302
CHILD_TYPE_ID: int = 79303
SECOND_CHILD_TYPE_ID: int = 79304
ALL_TYPE_IDS: list[int] = [PARENT_TYPE_ID, SECOND_PARENT_TYPE_ID, CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID]

RELATION_ID: int = 79310
KEPT_ID: int = 79321                  # PARENT_TYPE_ID  -> CHILD_TYPE_ID
DROPPED_PARENT_ID: int = 79322        # SECOND_PARENT   -> CHILD_TYPE_ID
DROPPED_CHILD_ID: int = 79323         # PARENT_TYPE_ID  -> SECOND_CHILD
SECOND_DROPPED_CHILD_ID: int = 79324  # PARENT_TYPE_ID  -> SECOND_CHILD
ALL_INSTANCE_IDS: list[int] = [KEPT_ID, DROPPED_PARENT_ID, DROPPED_CHILD_ID, SECOND_DROPPED_CHILD_ID]
# Distinct object ids per instance: one ordered pair per relation is a unique index
OBJECT_ID_BASE: int = 79400


def _relation(parent_type_ids: list[int], child_type_ids: list[int]) -> dict[str, Any]:
    """The relation definition with the given sides, as PUT sends it."""
    return {
        'public_id': RELATION_ID,
        'relation_name': f'cascade-history-{RELATION_ID}',
        'relation_name_parent': 'is-parent-of',
        'relation_name_child': 'is-child-of',
        'parent_type_ids': parent_type_ids,
        'child_type_ids': child_type_ids,
        'sections': [],
        'fields': [],
    }


def _instance(public_id: int, parent_type_id: int, child_type_id: int) -> dict[str, Any]:
    """A stored CmdbObjectRelation of RELATION_ID with stamped endpoint types."""
    offset: int = public_id - KEPT_ID

    return {
        'public_id': public_id, 'relation_id': RELATION_ID,
        'relation_parent_id': OBJECT_ID_BASE + 2 * offset, 'relation_parent_type_id': parent_type_id,
        'relation_child_id': OBJECT_ID_BASE + 2 * offset + 1, 'relation_child_type_id': child_type_id,
        'field_values': [], 'author_id': 1,
    }


@pytest.fixture(name='stored', autouse=True)
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str):
    """The four types, the relation allowing both on each side, and one instance per type pair"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    instances = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        relations.delete_many({'public_id': RELATION_ID})
        instances.delete_many({'relation_id': RELATION_ID})
        logs.delete_many({'object_relation_id': {'$in': ALL_INSTANCE_IDS}})

    _purge()
    types.insert_many([{'public_id': type_id, 'name': f'cascade-type-{type_id}', 'label': f'T{type_id}'}
                       for type_id in ALL_TYPE_IDS])
    relations.insert_one(_relation([PARENT_TYPE_ID, SECOND_PARENT_TYPE_ID], [CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID]))
    instances.insert_many([
        _instance(KEPT_ID, PARENT_TYPE_ID, CHILD_TYPE_ID),
        _instance(DROPPED_PARENT_ID, SECOND_PARENT_TYPE_ID, CHILD_TYPE_ID),
        _instance(DROPPED_CHILD_ID, PARENT_TYPE_ID, SECOND_CHILD_TYPE_ID),
        _instance(SECOND_DROPPED_CHILD_ID, PARENT_TYPE_ID, SECOND_CHILD_TYPE_ID),
    ])
    yield {'instances': instances, 'logs': logs}
    _purge()


def _stored_ids(stored: dict[str, Any]) -> set[int]:
    """The instances of RELATION_ID still stored."""
    return {doc['public_id'] for doc in stored['instances'].find({'relation_id': RELATION_ID})}


def _logged(stored: dict[str, Any]) -> dict[int, list[str]]:
    """The recorded actions per instance id, oldest first."""
    actions: dict[int, list[str]] = {}

    for log in stored['logs'].find({'object_relation_id': {'$in': ALL_INSTANCE_IDS}}).sort('public_id', 1):
        actions.setdefault(log['object_relation_id'], []).append(log['action'])

    return actions


@pytest.mark.parametrize('parent_type_ids,child_type_ids,dropped', [
    pytest.param([PARENT_TYPE_ID], [CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID], [DROPPED_PARENT_ID], id='parent side'),
    pytest.param([PARENT_TYPE_ID, SECOND_PARENT_TYPE_ID], [CHILD_TYPE_ID],
                 [DROPPED_CHILD_ID, SECOND_DROPPED_CHILD_ID], id='child side'),
    pytest.param([PARENT_TYPE_ID], [CHILD_TYPE_ID],
                 [DROPPED_PARENT_ID, DROPPED_CHILD_ID, SECOND_DROPPED_CHILD_ID], id='both sides'),
])
def test_each_deleted_instance_is_logged_once_and_counted(
    rest_api, stored, parent_type_ids: list[int], child_type_ids: list[int], dropped: list[int],
) -> None:
    """One DELETE entry per dropped instance; the kept ones are untouched and unlogged; the count answers"""
    response = rest_api.put(f'{ROUTE_URL}/{RELATION_ID}', json=_relation(parent_type_ids, child_type_ids))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.get_json()[DELETED_KEY] == len(dropped)
    assert response.get_json()['result']['parent_type_ids'] == parent_type_ids
    assert _stored_ids(stored) == set(ALL_INSTANCE_IDS) - set(dropped)
    assert _logged(stored) == {public_id: [DELETE_ACTION] for public_id in dropped}


def test_an_update_that_drops_no_type_deletes_and_logs_nothing(rest_api, stored) -> None:
    """A rename keeps every instance: the count is 0 and no history is written"""
    payload = _relation([PARENT_TYPE_ID, SECOND_PARENT_TYPE_ID], [CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID])
    payload['relation_name'] = 'renamed-cascade-history'

    response = rest_api.put(f'{ROUTE_URL}/{RELATION_ID}', json=payload)

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.get_json()[DELETED_KEY] == 0
    assert _stored_ids(stored) == set(ALL_INSTANCE_IDS)
    assert not _logged(stored)


def test_a_cascade_failing_part_way_logs_what_it_deleted(rest_api, stored, monkeypatch) -> None:
    """The second delete fails: 500 (partial application), the first deleted instance is in the history"""
    real_delete = BaseManager.find_one_and_delete
    calls: list[int] = []

    def _second_fails(self, criteria):
        calls.append(1)
        if len(calls) == 2:
            raise BaseManagerDeleteError('boom')

        return real_delete(self, criteria)

    monkeypatch.setattr(BaseManager, 'find_one_and_delete', _second_fails)

    response = rest_api.put(f'{ROUTE_URL}/{RELATION_ID}', json=_relation(
        [PARENT_TYPE_ID, SECOND_PARENT_TYPE_ID], [CHILD_TYPE_ID],
    ))

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    deleted: set[int] = {DROPPED_CHILD_ID, SECOND_DROPPED_CHILD_ID} - _stored_ids(stored)
    assert len(deleted) == 1
    assert _logged(stored) == {deleted.pop(): [DELETE_ACTION]}
