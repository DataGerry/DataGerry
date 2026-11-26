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
Functional tests: administrators can always re-grant themselves a Type hidden from them (phase 8 step 6, T582)

An access rule editor (not an administrator) restricts a Type to another group - the administrators lose view. They
name the hidden Type in a new role and assign it to their own group, and read the Type again - without ever opening
it. A Type the migration locked (a role without operations, assigned to the administrators) is opened up to them by
widening that role. A non-administrator stays refused both ways
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import ADMIN_GROUP_ID, CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_rules import AccessRuleMessage
# -------------------------------------------------------------------------------------------------------------------- #

EDITOR_GROUP_ID: int = 9881
OTHER_GROUP_ID: int = 9882
EDITOR_ID: int = 9883
EDITOR_NAME: str = 'recovery-editor'
HIDDEN_TYPE_ID: int = 9884
LOCKED_TYPE_ID: int = 9885
LOCKED_ROLE_ID: int = 9886
LOCKED_ASSIGNMENT_ID: int = 9887
TYPE_IDS: list[int] = [HIDDEN_TYPE_ID, LOCKED_TYPE_ID]
ROLES_URL: str = '/access/scope_roles'
ASSIGNMENTS_URL: str = '/access/assignments'


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two Types; an editor holding the access rule rights; the locked Type as the migration leaves it"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': EDITOR_GROUP_ID, 'name': 'recovery-editors', 'label': 'Editors', 'rights': ['base.access.*']},
        {'public_id': OTHER_GROUP_ID, 'name': 'recovery-other', 'label': 'Other', 'rights': []},
    ])
    database[CmdbUser.COLLECTION].insert_one({'public_id': EDITOR_ID, 'user_name': EDITOR_NAME, 'active': True,
                                              'group_ids': [EDITOR_GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbType.COLLECTION].insert_many([{'public_id': type_id, 'name': f'recovery-{type_id}', 'label': 'T',
                                                'fields': []} for type_id in TYPE_IDS])
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': LOCKED_ROLE_ID, 'name': 'recovery-locked',
                                                   'description': '', 'types': [LOCKED_TYPE_ID], 'operations': [],
                                                   'write_regular_fields': True, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': LOCKED_ASSIGNMENT_ID,
                                                          'group_id': ADMIN_GROUP_ID, 'role_id': LOCKED_ROLE_ID,
                                                          'scope': '*', 'description': ''})

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [EDITOR_GROUP_ID, OTHER_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': EDITOR_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _editor() -> dict[str, Any]:
    """The request kwargs sending the editor"""
    return {'user': CmdbUser(public_id=EDITOR_ID, user_name=EDITOR_NAME, active=True, group_ids=[EDITOR_GROUP_ID])}


def _role(rest_api: Any, operations: list[str], **kwargs: Any) -> Any:
    """Creates a role on the hidden Type"""
    return rest_api.post(ROLES_URL, json={'name': f'recovery-{operations}-{len(kwargs)}', 'types': [HIDDEN_TYPE_ID],
                                          'operations': operations}, **kwargs)


def _hide_from_the_administrators(rest_api: Any) -> None:
    """The editor gives the other group view on the hidden Type - restricted from then on"""
    role = _role(rest_api, ['view'], **_editor())
    assert role.status_code == HTTPStatus.CREATED
    assigned = rest_api.post(ASSIGNMENTS_URL, json={'group_id': OTHER_GROUP_ID, 'role_id': role.get_json()['result_id'],
                                                    'scope': '*'}, **_editor())
    assert assigned.status_code == HTTPStatus.CREATED


def test_the_administrators_regain_a_hidden_type_without_opening_it(rest_api, database: Any) -> None:
    """Hidden (403), a role naming it, assigned to group 1, readable again - the other group's assignment stays"""
    _hide_from_the_administrators(rest_api)
    assert rest_api.get(f'/types/{HIDDEN_TYPE_ID}').status_code == HTTPStatus.FORBIDDEN

    role = _role(rest_api, ['view', 'edit'])
    assigned = rest_api.post(ASSIGNMENTS_URL, json={'group_id': ADMIN_GROUP_ID,
                                                    'role_id': role.get_json()['result_id'], 'scope': '*'})

    assert (role.status_code, assigned.status_code) == (HTTPStatus.CREATED, HTTPStatus.CREATED)
    assert rest_api.get(f'/types/{HIDDEN_TYPE_ID}').status_code == HTTPStatus.OK
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({'group_id': OTHER_GROUP_ID}) == 1


def test_the_administrators_widen_the_migrations_locked_role(rest_api) -> None:
    """The empty role assigned to group 1 gains view - the locked Type is theirs again"""
    assert rest_api.get(f'/types/{LOCKED_TYPE_ID}').status_code == HTTPStatus.FORBIDDEN

    widened = rest_api.put(f'{ROLES_URL}/{LOCKED_ROLE_ID}', json={'operations': ['view']})

    assert widened.status_code == HTTPStatus.ACCEPTED
    assert rest_api.get(f'/types/{LOCKED_TYPE_ID}').status_code == HTTPStatus.OK


def test_a_non_administrator_stays_refused(rest_api) -> None:
    """The editor may not name the hidden Type (like a missing one), nor give its own group the role (403)"""
    _hide_from_the_administrators(rest_api)
    named = _role(rest_api, ['view', 'delete'], **_editor())
    other_role = rest_api.get(f'/access/assignments?filter={{"group_id": {OTHER_GROUP_ID}}}').get_json()['results'][0]
    assigned = rest_api.post(ASSIGNMENTS_URL, json={'group_id': EDITOR_GROUP_ID, 'role_id': other_role['role_id'],
                                                    'scope': '*'}, **_editor())

    assert named.status_code == HTTPStatus.BAD_REQUEST
    assert named.get_json()['message'] == AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[HIDDEN_TYPE_ID])
    assert assigned.status_code == HTTPStatus.FORBIDDEN
