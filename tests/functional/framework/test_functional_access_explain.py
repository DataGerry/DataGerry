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
The release check of the explain routes on a restricted server Type

The operators hold a conditional assignment (``host equals a``), the readers an unconditional view-only one, the
auditors may view the access rules and users but hold nothing on the Type. Pinned: a user's explanation names the
decisive step per operation, the assignments with each condition marked and the field list; the verdicts are what the
real object routes answer for that user (never diverge); an inactive user, a missing right; the caller must view the
object (403); 400 / 404; the per-group view answers each group by itself
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

OPERATORS, READERS, AUDITORS, NO_RIGHTS = 95901, 95902, 95903, 95904
OPERATOR, READER, AUDITOR, SLEEPER, POWERLESS = 95911, 95912, 95913, 95914, 95915
SERVER: int = 95921
OPERATOR_ROLE, READER_ROLE, ADMIN_ROLE = 95931, 95932, 95933
OPERATOR_ASSIGNMENT, READER_ASSIGNMENT, ADMIN_ASSIGNMENT = 95941, 95942, 95943
OBJECT_ID: int = 95961
MISSING_ID: int = 95999
ADMIN_GROUP_ID: int = 1
FRAMEWORK_RIGHTS: list[str] = ['base.framework.*']
EXPLAIN: str = '/access/explain'
OPERATOR_SCOPE: list[dict[str, Any]] = [{'field': 'host', 'op': 'equals', 'value': 'a'}]


def _role(role_id: int, operations: list[str]) -> dict[str, Any]:
    """A scope role on the server Type"""
    return {'public_id': role_id, 'name': f'explain-{role_id}', 'description': '', 'types': [SERVER],
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Type, the groups, users, roles, assignments and one server; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbType.COLLECTION].insert_one({
        'public_id': SERVER, 'name': 'explain-server', 'label': 'S', 'author_id': 1, 'active': True,
        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': 'host', 'label': 'Host'}],
        'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
        'acl': {'activated': False, 'groups': {'includes': {}}}})
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': OPERATORS, 'name': 'explain-operators', 'label': 'O', 'rights': FRAMEWORK_RIGHTS},
        {'public_id': READERS, 'name': 'explain-readers', 'label': 'R', 'rights': FRAMEWORK_RIGHTS},
        {'public_id': AUDITORS, 'name': 'explain-auditors', 'label': 'A',
         'rights': ['base.access.view', 'base.user-management.user.view']},
        {'public_id': NO_RIGHTS, 'name': 'explain-no-rights', 'label': 'N', 'rights': []}])
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': user_id, 'user_name': f'explain-{user_id}', 'active': active, 'group_ids': [group_id],
         'registration_time': datetime.now(timezone.utc)}
        for user_id, group_id, active in ((OPERATOR, OPERATORS, True), (READER, READERS, True),
                                          (AUDITOR, AUDITORS, True), (SLEEPER, OPERATORS, False),
                                          (POWERLESS, NO_RIGHTS, True))])
    database[CmdbScopeRole.COLLECTION].insert_many([
        _role(OPERATOR_ROLE, ['view', 'create', 'edit']), _role(READER_ROLE, ['view']),
        _role(ADMIN_ROLE, ['view', 'create', 'edit', 'delete'])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': OPERATOR_ASSIGNMENT, 'group_id': OPERATORS, 'role_id': OPERATOR_ROLE, 'scope': OPERATOR_SCOPE,
         'description': ''},
        {'public_id': READER_ASSIGNMENT, 'group_id': READERS, 'role_id': READER_ROLE, 'scope': '*',
         'description': ''},
        {'public_id': ADMIN_ASSIGNMENT, 'group_id': ADMIN_GROUP_ID, 'role_id': ADMIN_ROLE, 'scope': '*',
         'description': ''}])
    database[CmdbObject.COLLECTION].insert_one(
        {'public_id': OBJECT_ID, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
         'fields': [{'name': 'host', 'value': 'a', 'type': 'text'}]})

    yield database

    database[CmdbType.COLLECTION].delete_many({'public_id': SERVER})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [OPERATORS, READERS, AUDITORS, NO_RIGHTS]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [OPERATOR, READER, AUDITOR, SLEEPER,
                                                                     POWERLESS]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': SERVER})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': OBJECT_ID})


def _as(user_id: int, group_id: int) -> dict[str, Any]:
    """The request kwargs sending it as a user of the group"""
    return {'user': CmdbUser(public_id=user_id, user_name=f'explain-{user_id}', active=True, group_ids=[group_id])}


def _explain(rest_api: Any, user_id: int, **kwargs: Any) -> Any:
    """GET the explanation of a user on the server"""
    return rest_api.get(EXPLAIN, query_string={'user_id': user_id, 'object_id': OBJECT_ID}, **kwargs)


def _steps(answer: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    """Per operation: allowed and the step"""
    return {row['operation']: (row['allowed'], row['step']) for row in answer['operations']}


def _set_host(db: Any, host: str) -> None:
    """Changes the server's host behind the routes"""
    db[CmdbObject.COLLECTION].update_one({'public_id': OBJECT_ID}, {'$set': {'fields.0.value': host}})


class TestExplainingAUser:
    """GET /access/explain"""

    def test_the_conditional_operator(self, rest_api) -> None:
        """Allowed by the scope where its condition holds; delete not granted; the condition marked met"""
        response = _explain(rest_api, OPERATOR)

        assert response.status_code == HTTPStatus.OK, response.get_json()
        answer: dict[str, Any] = response.get_json()['result']
        assert _steps(answer) == {'view': (True, 'scope'), 'create': (True, 'scope'), 'edit': (True, 'scope'),
                                  'delete': (False, 'scope')}
        assert [(row['assignment_id'], row['group_id'], row['matched'], row['grants_here'],
                 [mark['met'] for mark in row['conditions']]) for row in answer['assignments']] == [
            (OPERATOR_ASSIGNMENT, OPERATORS, True, ['view', 'create', 'edit'], [True])]
        assert answer['fields'] == [{'name': 'host', 'access': 'write', 'set_by': []}]
        assert answer['user']['group_ids'] == [OPERATORS] and 'host' not in str(answer['object'])

    def test_a_condition_no_longer_met(self, rest_api, db) -> None:
        """The host changed: every operation refused by the scope, the condition marked not met"""
        _set_host(db, 'b')
        answer: dict[str, Any] = _explain(rest_api, OPERATOR).get_json()['result']

        assert {operation: allowed for operation, (allowed, _) in _steps(answer).items()} == {
            'view': False, 'create': False, 'edit': False, 'delete': False}
        assert answer['assignments'][0]['conditions'][0]['met'] is False

    @pytest.mark.parametrize('host', ['a', 'b'])
    def test_the_verdicts_are_what_the_routes_answer(self, rest_api, db, host: str) -> None:
        """Never diverge: the view and an unchanged edit, as the operator"""
        _set_host(db, host)
        steps: dict[str, tuple[bool, str]] = _steps(_explain(rest_api, OPERATOR).get_json()['result'])
        operator: dict[str, Any] = _as(OPERATOR, OPERATORS)
        viewed: int = rest_api.get(f'/objects/{OBJECT_ID}', **operator).status_code
        edited: int = rest_api.put(f'/objects/{OBJECT_ID}', json={
            'public_id': OBJECT_ID, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': 'host', 'value': host}]}, **operator).status_code

        assert (viewed == HTTPStatus.OK) is steps['view'][0]
        assert (edited == HTTPStatus.ACCEPTED) is steps['edit'][0]

    def test_the_reader_holds_view_only(self, rest_api) -> None:
        """Unconditional: matched, no conditions"""
        answer: dict[str, Any] = _explain(rest_api, READER).get_json()['result']

        assert _steps(answer)['view'] == (True, 'scope') and _steps(answer)['edit'] == (False, 'scope')
        assert answer['assignments'][0]['unconditional'] is True and answer['assignments'][0]['conditions'] == []

    @pytest.mark.parametrize('user_id, step', [(SLEEPER, 'user_inactive'), (POWERLESS, 'functional_right')])
    def test_the_checks_before_the_engine(self, rest_api, user_id: int, step: str) -> None:
        """An inactive user, a user without the object rights"""
        answer: dict[str, Any] = _explain(rest_api, user_id).get_json()['result']

        assert {row['step'] for row in answer['operations']} == {step}

    def test_the_caller_must_view_the_object(self, rest_api) -> None:
        """The auditors hold nothing on the restricted Type"""
        assert _explain(rest_api, OPERATOR, **_as(AUDITOR, AUDITORS)).status_code == HTTPStatus.FORBIDDEN

    def test_the_caller_needs_both_rights(self, rest_api) -> None:
        """The readers may view the object but not the access rules"""
        assert _explain(rest_api, OPERATOR, **_as(READER, READERS)).status_code == HTTPStatus.FORBIDDEN

    def test_refusals(self, rest_api) -> None:
        """Parameters missing, an unknown user, an unknown object"""
        assert rest_api.get(EXPLAIN, query_string={'user_id': OPERATOR}).status_code == HTTPStatus.BAD_REQUEST
        assert _explain(rest_api, MISSING_ID).status_code == HTTPStatus.NOT_FOUND
        assert rest_api.get(EXPLAIN, query_string={'user_id': OPERATOR, 'object_id': MISSING_ID}
                            ).status_code == HTTPStatus.NOT_FOUND


class TestWhoMayDoWhatHere:
    """GET /access/objects/<id>/explain"""

    def test_each_group_by_itself(self, rest_api) -> None:
        """The operators by their condition, the readers view only, the auditors nothing; the Type is restricted"""
        response = rest_api.get(f'/access/objects/{OBJECT_ID}/explain')

        assert response.status_code == HTTPStatus.OK, response.get_json()
        answer: dict[str, Any] = response.get_json()['result']
        verdicts: dict[int, dict[str, str]] = {group['group_id']: {row['operation']: row['verdict']
                                                                   for row in group['operations']}
                                               for group in answer['groups']}
        assert answer['restricted'] is True
        assert verdicts[OPERATORS] == {'view': 'allowed', 'create': 'allowed', 'edit': 'allowed', 'delete': 'denied'}
        assert verdicts[READERS] == {'view': 'allowed', 'create': 'denied', 'edit': 'denied', 'delete': 'denied'}
        assert set(verdicts[AUDITORS].values()) == {'denied'}
        assert verdicts[ADMIN_GROUP_ID] == {'view': 'allowed', 'create': 'allowed', 'edit': 'allowed',
                                            'delete': 'allowed'}

    def test_the_caller_must_view_the_object(self, rest_api) -> None:
        """403 for the auditors"""
        assert rest_api.get(f'/access/objects/{OBJECT_ID}/explain',
                            **_as(AUDITOR, AUDITORS)).status_code == HTTPStatus.FORBIDDEN
