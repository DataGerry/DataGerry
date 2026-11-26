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
Functional tests: a ``within`` condition through the real routes, judged on the materialised scope block (phase 10)

A user group holds every operation on a device Type through one assignment with ``{within: SITE}``, and views the site
Type in full (a location of a Type held only conditionally is refused as a parent - the fail-closed family T585); the
administrators hold both unconditionally. Two sites placed under the root, a device placed in the first. Pinned as the
user: a create placed inside passes and stores its block, one placed in the other site is a 403 (B2); an edit moving
the object to the other site is a 403 and nothing changes (B1). As an administrator the same move passes, the block
follows and the user no longer lists the object. ``_scope`` is in no answer, and a block sent in a body is not stored
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 96901
USER_ID: int = 96911
TYPE_ID, SITE_TYPE_ID = 96921, 96922
ROLE_ID, ADMIN_ROLE_ID, SITE_ROLE_ID = 96931, 96932, 96933
ASSIGNMENT_ID, ADMIN_ASSIGNMENT_ID, SITE_ASSIGNMENT_ID = 96941, 96942, 96943
SITE, OTHER_SITE, PLACED, CREATED = 96951, 96952, 96953, 96954
SITE_NODE, OTHER_NODE, PLACED_NODE = 96961, 96962, 96963
ADMIN_GROUP_ID: int = 1
ROOT_NODE: int = RootLocationDefault.PUBLIC_ID
OPERATIONS: list[str] = ['view', 'create', 'edit', 'delete']
SCOPE_BLOCK_KEY: str = '_scope'


def _fields(name: str, node_id: int | None) -> list[dict[str, Any]]:
    """The name and the placement"""
    return [{'name': 'name', 'value': name, 'type': 'text'}, {'name': 'loc', 'value': node_id, 'type': 'location'}]


def _object(public_id: int, node_id: int | None, type_id: int = TYPE_ID) -> dict[str, Any]:
    """A stored object"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
            'fields': _fields(f'o{public_id}', node_id)}


def _node(node_id: int, object_id: int, parent: int, type_id: int = TYPE_ID) -> dict[str, Any]:
    """A node of the location tree"""
    return {'public_id': node_id, 'name': str(object_id), 'parent': parent, 'object_id': object_id,
            'type_id': type_id, 'type_label': 'T', 'type_icon': 'fa-cube', 'type_selectable': True}


def _type(type_id: int) -> dict[str, Any]:
    """A Type with a name and a location field, selectable as a parent"""
    return {'public_id': type_id, 'name': f'scope-block-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'selectable_as_parent': True,
            'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'},
                       {'type': 'location', 'name': 'loc', 'label': 'Location'}],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['name']},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                          'fields': ['name', 'loc']}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _role(role_id: int, types: list[int], operations: list[str]) -> dict[str, Any]:
    """A scope role writing regular fields"""
    return {'public_id': role_id, 'name': f'scope-block-{role_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int, scope: Any) -> dict[str, Any]:
    """An assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': scope, 'description': ''}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The group, its user, the Types, the assignments, the tree and the objects with their blocks; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': GROUP_ID, 'name': 'scope-block', 'label': 'G',
                                                   'rights': ['base.framework.*', 'base.access.view']})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': 'scope-block', 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbType.COLLECTION].insert_many([_type(TYPE_ID), _type(SITE_TYPE_ID)])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(ROLE_ID, [TYPE_ID], OPERATIONS),
                                                    _role(ADMIN_ROLE_ID, [TYPE_ID, SITE_TYPE_ID], OPERATIONS),
                                                    _role(SITE_ROLE_ID, [SITE_TYPE_ID], ['view'])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(ASSIGNMENT_ID, GROUP_ID, ROLE_ID, [{'within': SITE}]),
        _assignment(SITE_ASSIGNMENT_ID, GROUP_ID, SITE_ROLE_ID, '*'),
        _assignment(ADMIN_ASSIGNMENT_ID, ADMIN_GROUP_ID, ADMIN_ROLE_ID, '*')])
    empty: dict[str, list[Any]] = {'locations': [], 'networks': [], 'ips': [], 'related': []}
    database[CmdbObject.COLLECTION].insert_many([
        {**_object(SITE, ROOT_NODE, SITE_TYPE_ID), SCOPE_BLOCK_KEY: empty},
        {**_object(OTHER_SITE, ROOT_NODE, SITE_TYPE_ID), SCOPE_BLOCK_KEY: empty},
        {**_object(PLACED, SITE_NODE), SCOPE_BLOCK_KEY: {**empty, 'locations': [SITE]}}])
    database[CmdbLocation.COLLECTION].insert_many([_node(SITE_NODE, SITE, ROOT_NODE, SITE_TYPE_ID),
                                                   _node(OTHER_NODE, OTHER_SITE, ROOT_NODE, SITE_TYPE_ID),
                                                   _node(PLACED_NODE, PLACED, SITE_NODE)])

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_many({'public_id': USER_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, SITE_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [TYPE_ID, SITE_TYPE_ID]}})
    database[CmdbLocation.COLLECTION].delete_many({'type_id': {'$in': [TYPE_ID, SITE_TYPE_ID]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$gte': SITE, '$lte': CREATED}})


def _user() -> dict[str, Any]:
    """The request kwargs sending it as the group's user"""
    return {'user': CmdbUser(public_id=USER_ID, user_name='scope-block', active=True, group_ids=[GROUP_ID])}


def _body(public_id: int, node_id: int | None, **extra: Any) -> dict[str, Any]:
    """A whole-object write body"""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': USER_ID, 'version': '1.0.0',
            'fields': [{'name': 'name', 'value': f'o{public_id}'}, {'name': 'loc', 'value': node_id}], **extra}


def _listed(rest_api: Any, **kwargs: Any) -> list[int]:
    """The ids GET /objects/ answers for the Type"""
    response = rest_api.get('/objects/', query_string={'filter': json.dumps({'type_id': TYPE_ID}), 'view': 'native',
                                                       'limit': 0}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return sorted(document['public_id'] for document in response.get_json()['results'])


def _block(db: Any, public_id: int) -> Any:
    """The stored block"""
    return db[CmdbObject.COLLECTION].find_one({'public_id': public_id}).get(SCOPE_BLOCK_KEY)


def test_the_user_lists_what_is_placed_in_the_site(rest_api) -> None:
    """The administrators the same device"""
    assert _listed(rest_api, **_user()) == [PLACED]
    assert _listed(rest_api) == [PLACED]


def test_a_create_placed_inside_passes_and_stores_its_block(rest_api, db: Any) -> None:
    """B2: the new object is judged by where it is placed; a block sent along is not stored"""
    response = rest_api.post('/objects/', json=_body(CREATED, SITE_NODE, _scope={'locations': [OTHER_SITE]}),
                             **_user())

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assert _block(db, CREATED) == {'locations': [SITE], 'networks': [], 'ips': [], 'related': []}


def test_a_create_placed_in_another_site_is_a_403(rest_api, db: Any) -> None:
    """Nothing stored"""
    response = rest_api.post('/objects/', json=_body(CREATED, OTHER_NODE), **_user())

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert db[CmdbObject.COLLECTION].count_documents({'public_id': CREATED}) == 0


def test_an_edit_moving_the_object_out_is_a_403(rest_api, db: Any) -> None:
    """B1: the after state is judged by its new placement - nothing changes"""
    response = rest_api.put(f'/objects/{PLACED}', json=_body(PLACED, OTHER_NODE), **_user())

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _block(db, PLACED)['locations'] == [SITE]
    assert db[CmdbLocation.COLLECTION].find_one({'public_id': PLACED_NODE})['parent'] == SITE_NODE


def test_the_administrators_move_is_followed_by_the_block(rest_api, db: Any) -> None:
    """The user no longer lists the object"""
    response = rest_api.put(f'/objects/{PLACED}', json=_body(PLACED, OTHER_NODE))

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
    assert _block(db, PLACED)['locations'] == [OTHER_SITE]
    assert not _listed(rest_api, **_user())


@pytest.mark.parametrize('url, query', [
    (f'/objects/{PLACED}', {}),
    ('/objects/', {'filter': json.dumps({'type_id': TYPE_ID}), 'view': 'native', 'limit': 0}),
    ('/objects/', {'filter': json.dumps({'type_id': TYPE_ID}), 'limit': 0}),
], ids=['single', 'list-native', 'list-render'])
def test_no_answer_carries_the_block(rest_api, url: str, query: dict[str, Any]) -> None:
    """Server-owned and internal (D5)"""
    response = rest_api.get(url, query_string=query)

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assert SCOPE_BLOCK_KEY not in response.get_data(as_text=True)
