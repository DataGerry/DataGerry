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
Functional tests: every Type answer carries the caller's ``allowed_operations``, through the real REST app

A Type the caller's role grants view only answers ``['view']``, a Type no role restricts all four - on
``GET /types/<id>``, ``GET /types/``, the category tree and an object's render (``type_information``)
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import CategoryRight
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

VIEW_TYPE_ID: int = 97561
FREE_TYPE_ID: int = 97562
TYPE_IDS: list[int] = [VIEW_TYPE_ID, FREE_TYPE_ID]
OBJECT_ID: int = 97563
CATEGORY_ID: int = 97564
GROUP_ID: int = 97565
USER_ID: int = 97566
ROLE_ID: int = 97567
ASSIGNMENT_ID: int = 97568
ALLOWED: str = 'allowed_operations'
VIEW_ONLY: list[str] = ['view']
EVERYTHING: list[str] = ['view', 'create', 'edit', 'delete']
CALLER: CmdbUser = CmdbUser(public_id=USER_ID, user_name='allowed-operations', active=True, group_ids=[GROUP_ID])


def _type_doc(public_id: int) -> dict[str, Any]:
    """A type with one field"""
    return {
        'public_id': public_id, 'name': f'allowed-operations-{public_id}', 'label': 'T', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': 'host', 'label': 'host'}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': ['host']},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Two types (one granted view only), an object of it, a category holding both, the caller"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_many([_type_doc(type_id) for type_id in TYPE_IDS])
    database[CmdbObject.COLLECTION].insert_one({
        'public_id': OBJECT_ID, 'type_id': VIEW_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': [{'name': 'host', 'value': 'h', 'type': 'text'}]})
    database[CmdbCategory.COLLECTION].insert_one({'public_id': CATEGORY_ID, 'name': 'allowed-operations',
                                                  'label': 'C', 'parent': None, 'types': TYPE_IDS})
    database[CmdbUserGroup.COLLECTION].insert_one({
        'public_id': GROUP_ID, 'name': 'allowed-operations', 'label': 'G',
        'rights': [TypeRight.VIEW.value, ObjectRightName.VIEW.value, CategoryRight.VIEW.value]})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': CALLER.user_name, 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbScopeRole.COLLECTION].insert_one({
        'public_id': ROLE_ID, 'name': 'allowed-operations', 'description': '', 'types': [VIEW_TYPE_ID],
        'operations': ['view'], 'write_regular_fields': True, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': ASSIGNMENT_ID, 'group_id': GROUP_ID,
                                                          'role_id': ROLE_ID, 'scope': '*'})

    yield

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbObject.COLLECTION].delete_one({'public_id': OBJECT_ID})
    database[CmdbCategory.COLLECTION].delete_one({'public_id': CATEGORY_ID})
    database[CmdbUserGroup.COLLECTION].delete_one({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_one({'public_id': USER_ID})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


@pytest.mark.parametrize('type_id, expected', [(VIEW_TYPE_ID, VIEW_ONLY), (FREE_TYPE_ID, EVERYTHING)],
                         ids=['view-only', 'unrestricted'])
def test_a_single_type(rest_api, type_id: int, expected: list[str]) -> None:
    """GET /types/<id>"""
    response = rest_api.get(f'/types/{type_id}', user=CALLER)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['result'][ALLOWED] == expected


def test_the_type_list(rest_api) -> None:
    """GET /types/ - each type its own list"""
    response = rest_api.get('/types/', user=CALLER, query_string={
        'filter': f'{{"public_id": {{"$in": {TYPE_IDS}}}}}', 'limit': 0})
    allowed: dict[int, list[str]] = {item['public_id']: item[ALLOWED] for item in response.get_json()['results']}

    assert allowed == {VIEW_TYPE_ID: VIEW_ONLY, FREE_TYPE_ID: EVERYTHING}


def test_the_category_tree(rest_api) -> None:
    """GET /categories/?view=tree - the types inside the nodes"""
    response = rest_api.get('/categories/', user=CALLER, query_string={'view': 'tree'})
    nodes: list[dict[str, Any]] = [node for node in response.get_json()['results']
                                   if node['category']['public_id'] == CATEGORY_ID]
    allowed: dict[int, list[str]] = {item['public_id']: item[ALLOWED] for item in nodes[0]['types']}

    assert allowed == {VIEW_TYPE_ID: VIEW_ONLY, FREE_TYPE_ID: EVERYTHING}


def test_an_object_render(rest_api) -> None:
    """GET /objects/<id> - the render's type information"""
    response = rest_api.get(f'/objects/{OBJECT_ID}', user=CALLER)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['type_information'][ALLOWED] == VIEW_ONLY
