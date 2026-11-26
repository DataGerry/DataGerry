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
Functional tests: a ``related_to`` condition through the real routes, kept current by the object relation writes
(phase 11, 9.7)

A user group holds every operation on the server Type through one assignment with ``{related_to: SERVICE}``; the
administrators hold both Types unconditionally. The administrator links servers to the service through
``/object_relations``. Pinned: a created relation brings its server into the user's list, an update moving the link
to another server swaps them, a delete takes it out, and deleting the service empties every server's related list
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 95901
USER_ID: int = 95911
SERVICE_TYPE_ID, SERVER_TYPE_ID = 95921, 95922
ROLE_ID, ADMIN_ROLE_ID = 95931, 95932
ASSIGNMENT_ID, ADMIN_ASSIGNMENT_ID = 95941, 95942
SERVICE, SERVER_A, SERVER_B = 95951, 95952, 95953
RELATION_ID: int = 95961
ADMIN_GROUP_ID: int = 1
OPERATIONS: list[str] = ['view', 'create', 'edit', 'delete']
ROUTE_URL: str = '/object_relations'


def _type(type_id: int) -> dict[str, Any]:
    """A Type with one text field"""
    return {'public_id': type_id, 'name': f'related-to-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'}],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['name']},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['name']}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A stored object"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
            'fields': [{'name': 'name', 'value': f'o{public_id}', 'type': 'text'}]}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The group, its user, the Types, the relation, the assignments and the objects; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': GROUP_ID, 'name': 'related-to', 'label': 'G',
                                                   'rights': ['base.framework.*']})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': 'related-to', 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbType.COLLECTION].insert_many([_type(SERVICE_TYPE_ID), _type(SERVER_TYPE_ID)])
    database[CmdbRelation.COLLECTION].insert_one({
        'public_id': RELATION_ID, 'relation_name': 'related-to-runs-on', 'parent_type_ids': [SERVICE_TYPE_ID],
        'child_type_ids': [SERVER_TYPE_ID], 'fields': []})
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': ROLE_ID, 'name': 'related-to-servers', 'description': '', 'types': [SERVER_TYPE_ID],
         'operations': OPERATIONS, 'write_regular_fields': True, 'field_classes': []},
        {'public_id': ADMIN_ROLE_ID, 'name': 'related-to-admins', 'description': '',
         'types': [SERVICE_TYPE_ID, SERVER_TYPE_ID], 'operations': OPERATIONS, 'write_regular_fields': True,
         'field_classes': []}])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': ASSIGNMENT_ID, 'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': [{'related_to': SERVICE}],
         'description': ''},
        {'public_id': ADMIN_ASSIGNMENT_ID, 'group_id': ADMIN_GROUP_ID, 'role_id': ADMIN_ROLE_ID, 'scope': '*',
         'description': ''}])
    database[CmdbObject.COLLECTION].insert_many([_object(SERVICE, SERVICE_TYPE_ID), _object(SERVER_A, SERVER_TYPE_ID),
                                                 _object(SERVER_B, SERVER_TYPE_ID)])

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_many({'public_id': USER_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVICE_TYPE_ID, SERVER_TYPE_ID]}})
    database[CmdbRelation.COLLECTION].delete_many({'public_id': RELATION_ID})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [SERVICE_TYPE_ID, SERVER_TYPE_ID]}})
    relation_ids = [document['public_id'] for document in
                    database[CmdbObjectRelation.COLLECTION].find({'relation_id': RELATION_ID})]
    database[CmdbObjectRelation.COLLECTION].delete_many({'relation_id': RELATION_ID})
    database[CmdbObjectRelationLog.COLLECTION].delete_many({'object_relation_id': {'$in': relation_ids}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': [SERVICE, SERVER_A, SERVER_B]}})


def _user() -> dict[str, Any]:
    """The request kwargs sending it as the group's user"""
    return {'user': CmdbUser(public_id=USER_ID, user_name='related-to', active=True, group_ids=[GROUP_ID])}


def _listed(rest_api: Any) -> list[int]:
    """The servers the user lists"""
    response = rest_api.get('/objects/', query_string={'filter': json.dumps({'type_id': SERVER_TYPE_ID}),
                                                       'view': 'native', 'limit': 0}, **_user())
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return sorted(document['public_id'] for document in response.get_json()['results'])


def _link(rest_api: Any, server: int, public_id: int | None = None) -> Any:
    """The administrator links the service to a server - a create, or with public_id an update"""
    body = {'relation_id': RELATION_ID, 'relation_parent_id': SERVICE, 'relation_parent_type_id': SERVICE_TYPE_ID,
            'relation_child_id': server, 'relation_child_type_id': SERVER_TYPE_ID, 'field_values': []}

    if public_id is None:
        return rest_api.post(f'{ROUTE_URL}/', json=body)

    return rest_api.put(f'{ROUTE_URL}/{public_id}', json={**body, 'public_id': public_id})


def _related(db: Any, public_id: int) -> Any:
    """The stored related list"""
    return (db[CmdbObject.COLLECTION].find_one({'public_id': public_id}).get('_scope') or {}).get('related')


def test_nothing_is_related_yet(rest_api) -> None:
    """The user lists no server"""
    assert not _listed(rest_api)


def test_a_relation_create_update_and_delete_move_the_user_s_reach(rest_api, db: Any) -> None:
    """Both ends follow every write"""
    created = _link(rest_api, SERVER_A)
    assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), created.get_json()
    relation_id = created.get_json()['result_id']

    assert _listed(rest_api) == [SERVER_A]
    assert _related(db, SERVICE) == [{'object': SERVER_A, 'relation': RELATION_ID}]

    updated = _link(rest_api, SERVER_B, relation_id)
    assert updated.status_code == HTTPStatus.ACCEPTED, updated.get_json()
    assert _listed(rest_api) == [SERVER_B]
    assert _related(db, SERVER_A) == []

    assert rest_api.delete(f'{ROUTE_URL}/{relation_id}').status_code == HTTPStatus.ACCEPTED
    assert not _listed(rest_api)
    assert (_related(db, SERVICE), _related(db, SERVER_B)) == ([], [])


def test_deleting_the_anchor_empties_the_related_lists(rest_api, db: Any) -> None:
    """The relation cascade of an object delete refreshes the other ends"""
    assert _link(rest_api, SERVER_A).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    assert rest_api.delete(f'/objects/{SERVICE}').status_code == HTTPStatus.OK
    assert _related(db, SERVER_A) == []
    assert not _listed(rest_api)
