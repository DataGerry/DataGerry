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
Functional tests: every answer carrying a Type's ``acl`` answers the block the access rules decide, not the stored one

The stored blocks contradict the rules on purpose: the restricted Type stores an ACL switched off, the free Type one
switched on for a group that holds nothing. Each answer - ``GET /types/<id>``, ``GET /types/``, ``/types/overview``,
the category tree, an object's render - shows the rules: the restricted Type on, the caller's group with READ; the
free Type off. The stored blocks stay as they were
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

RESTRICTED_TYPE_ID: int = 97571
FREE_TYPE_ID: int = 97572
TYPE_IDS: list[int] = [RESTRICTED_TYPE_ID, FREE_TYPE_ID]
OBJECT_ID: int = 97573
CATEGORY_ID: int = 97574
GROUP_ID: int = 97575
USER_ID: int = 97576
ROLE_ID: int = 97577
ASSIGNMENT_ID: int = 97578
STALE_GROUP_ID: int = 97579
CALLER: CmdbUser = CmdbUser(public_id=USER_ID, user_name='synthesised-acl', active=True, group_ids=[GROUP_ID])

STORED_ACLS: dict[int, dict[str, Any]] = {
    RESTRICTED_TYPE_ID: {'activated': False, 'groups': {'includes': {}}},
    FREE_TYPE_ID: {'activated': True, 'groups': {'includes': {str(STALE_GROUP_ID): ['READ']}}},
}
ANSWERED: dict[int, dict[str, Any]] = {
    RESTRICTED_TYPE_ID: {'activated': True, 'groups': {'includes': {str(GROUP_ID): ['READ']}}},
    FREE_TYPE_ID: {'activated': False, 'groups': {'includes': {}}},
}


def _type_doc(public_id: int) -> dict[str, Any]:
    """A type with one field and its contradicting stored acl"""
    return {
        'public_id': public_id, 'name': f'synthesised-acl-{public_id}', 'label': 'T', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': 'host', 'label': 'host'}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': ['host']},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
        'acl': STORED_ACLS[public_id],
    }


@pytest.fixture(name='database', autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two types (one restricted, the caller's group viewing it), an object of it, a category holding both"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_many([_type_doc(type_id) for type_id in TYPE_IDS])
    database[CmdbObject.COLLECTION].insert_one({
        'public_id': OBJECT_ID, 'type_id': RESTRICTED_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': [{'name': 'host', 'value': 'h', 'type': 'text'}]})
    database[CmdbCategory.COLLECTION].insert_one({'public_id': CATEGORY_ID, 'name': 'synthesised-acl',
                                                  'label': 'C', 'parent': None, 'types': TYPE_IDS})
    database[CmdbUserGroup.COLLECTION].insert_one({
        'public_id': GROUP_ID, 'name': 'synthesised-acl', 'label': 'G',
        'rights': [TypeRight.VIEW.value, ObjectRightName.VIEW.value, CategoryRight.VIEW.value]})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': CALLER.user_name, 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbScopeRole.COLLECTION].insert_one({
        'public_id': ROLE_ID, 'name': 'synthesised-acl', 'description': '', 'types': [RESTRICTED_TYPE_ID],
        'operations': ['view'], 'write_regular_fields': True, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': ASSIGNMENT_ID, 'group_id': GROUP_ID,
                                                          'role_id': ROLE_ID, 'scope': '*'})

    yield database

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbObject.COLLECTION].delete_one({'public_id': OBJECT_ID})
    database[CmdbCategory.COLLECTION].delete_one({'public_id': CATEGORY_ID})
    database[CmdbUserGroup.COLLECTION].delete_one({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_one({'public_id': USER_ID})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


@pytest.mark.parametrize('type_id', TYPE_IDS, ids=['restricted', 'free'])
def test_a_single_type(rest_api, type_id: int) -> None:
    """GET /types/<id>"""
    response = rest_api.get(f'/types/{type_id}', user=CALLER)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['result']['acl'] == ANSWERED[type_id]


def test_the_type_list(rest_api) -> None:
    """GET /types/"""
    response = rest_api.get('/types/', user=CALLER, query_string={
        'filter': f'{{"public_id": {{"$in": {TYPE_IDS}}}}}', 'limit': 0})

    assert {item['public_id']: item['acl'] for item in response.get_json()['results']} == ANSWERED


def test_the_overview(rest_api) -> None:
    """GET /types/overview - each item's type_data"""
    response = rest_api.get('/types/overview', user=CALLER, query_string={
        'filter': f'{{"public_id": {{"$in": {TYPE_IDS}}}}}', 'limit': 0})
    items: list[dict[str, Any]] = response.get_json()['results']

    assert {item['type_data']['public_id']: item['type_data']['acl'] for item in items} == ANSWERED


def test_the_category_tree(rest_api) -> None:
    """GET /categories/?view=tree"""
    response = rest_api.get('/categories/', user=CALLER, query_string={'view': 'tree'})
    node: dict[str, Any] = next(node for node in response.get_json()['results']
                                if node['category']['public_id'] == CATEGORY_ID)

    assert {item['public_id']: item['acl'] for item in node['types']} == ANSWERED


def test_an_object_render_and_the_stored_blocks_stay(rest_api, database: Any) -> None:
    """GET /objects/<id> - type_information.acl; nothing written to the Types"""
    response = rest_api.get(f'/objects/{OBJECT_ID}', user=CALLER)

    assert response.get_json()['type_information']['acl'] == ANSWERED[RESTRICTED_TYPE_ID]
    assert {document['public_id']: document['acl']
            for document in database[CmdbType.COLLECTION].find({'public_id': {'$in': TYPE_IDS}})} == STORED_ACLS
