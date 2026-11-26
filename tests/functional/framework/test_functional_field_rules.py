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
The release check of the Field Rules: a review rule on a server Type through the real routes

A server Type with a regular field (``host``), a ``system`` field stamped by the rule (``reviewed_at``, a date) and a
second ``system`` field carrying a default (``origin``); the operators edit regular fields. Pinned: the CRUD routes
(the ``set`` stored cast; every problem in one 400; the name fixed; the check answering the reach per Type; the list
narrowed to a user group); an object write changing ``host`` gets ``reviewed_at`` stamped by the server and the log
entry names the rule; an untriggered write stays as it was; an invalid rule value refuses the write naming the rule; a
create fills the ``system`` default after the check; a Type change removing the rule's field is refused; a scope may
not compare a field a rule sets
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbFieldRule, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

OPERATORS, OPERATOR = 94901, 94911
SERVER, OTHER = 94921, 94922
OPERATOR_ROLE, ADMIN_ROLE = 94931, 94932
OBJECT_ID, CREATED = 94961, 94962
ADMIN_GROUP_ID: int = 1
RULE_NAME: str = 'stamp-review'
ORIGIN_DEFAULT: str = 'portal'
FIELD_RULES: str = '/access/field_rules'
SERVER_FIELDS: list[dict[str, Any]] = [
    {'type': 'text', 'name': 'host', 'label': 'Host'},
    {'type': 'text', 'name': 'code', 'label': 'Code', 'regex': '^[A-Z]+$'},
    {'type': 'date', 'name': 'reviewed_at', 'label': 'Reviewed at', 'protection': 'system'},
    {'type': 'text', 'name': 'origin', 'label': 'Origin', 'protection': 'system', 'value': ORIGIN_DEFAULT},
]
RULE_BODY: dict[str, Any] = {'name': RULE_NAME, 'description': 'Stamp the review', 'types': [SERVER],
                             'when': {'changed': ['host']}, 'set': {'reviewed_at': '${now}'}}


def _type(type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A Type with one section"""
    return {'public_id': type_id, 'name': f'field-rules-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'fields': fields,
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                          'fields': [field['name'] for field in fields]}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _role(role_id: int, operations: list[str]) -> dict[str, Any]:
    """A scope role on the server Type writing regular fields"""
    return {'public_id': role_id, 'name': f'field-rules-{role_id}', 'description': '', 'types': [SERVER],
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types, the operators, their role and assignment, one server; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbType.COLLECTION].insert_many([_type(SERVER, SERVER_FIELDS),
                                               _type(OTHER, [{'type': 'text', 'name': 'host', 'label': 'Host'}])])
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': OPERATORS, 'name': 'field-rules-operators',
                                                   'label': 'G', 'rights': ['base.framework.*']})
    database[CmdbUser.COLLECTION].insert_one({'public_id': OPERATOR, 'user_name': 'field-rules-operator', 'active': True,
                                              'group_ids': [OPERATORS], 'registration_time': datetime.now(timezone.utc)})
    database[CmdbScopeRole.COLLECTION].insert_many([_role(OPERATOR_ROLE, ['view', 'create', 'edit']),
                                                    _role(ADMIN_ROLE, ['view', 'create', 'edit', 'delete'])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': 94971, 'group_id': OPERATORS, 'role_id': OPERATOR_ROLE, 'scope': '*', 'description': ''},
        {'public_id': 94972, 'group_id': ADMIN_GROUP_ID, 'role_id': ADMIN_ROLE, 'scope': '*', 'description': ''}])
    database[CmdbObject.COLLECTION].insert_one(
        {'public_id': OBJECT_ID, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
         'fields': [{'name': 'host', 'value': 'a', 'type': 'text'}, {'name': 'code', 'value': 'A', 'type': 'text'},
                    {'name': 'reviewed_at', 'value': None, 'type': 'date'},
                    {'name': 'origin', 'value': None, 'type': 'text'}]})

    yield database

    database[CmdbFieldRule.COLLECTION].delete_many({})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVER, OTHER]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': OPERATORS})
    database[CmdbUser.COLLECTION].delete_many({'public_id': OPERATOR})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [SERVER, OTHER]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': [OBJECT_ID, CREATED]}})


def _operator() -> dict[str, Any]:
    """The request kwargs sending it as the operator"""
    return {'user': CmdbUser(public_id=OPERATOR, user_name='field-rules-operator', active=True, group_ids=[OPERATORS])}


def _body(public_id: int, host: str = 'a', code: str = 'A') -> dict[str, Any]:
    """A whole-object write body - the system fields left as stored"""
    return {'public_id': public_id, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': 'host', 'value': host}, {'name': 'code', 'value': code},
                       {'name': 'reviewed_at', 'value': None}, {'name': 'origin', 'value': None}]}


def _stored_value(db: Any, public_id: int, name: str) -> Any:
    """One field's stored value"""
    stored: dict[str, Any] = db[CmdbObject.COLLECTION].find_one({'public_id': public_id})

    return next(entry['value'] for entry in stored['fields'] if entry['name'] == name)


def _create_rule(rest_api: Any, **changes: Any) -> Any:
    """POST the review rule"""
    return rest_api.post(FIELD_RULES, json={**RULE_BODY, **changes})


class TestRoutes:
    """Create, read, update, check, list, delete"""

    def test_a_rule_round_trips(self, rest_api) -> None:
        """Stored with its defaults; read back; deleted"""
        created = _create_rule(rest_api)

        assert created.status_code == HTTPStatus.CREATED, created.get_json()
        public_id: int = created.get_json()['result_id']
        stored = rest_api.get(f'{FIELD_RULES}/{public_id}').get_json()['result']
        assert (stored['name'], stored['active'], stored['set']) == (RULE_NAME, True, {'reviewed_at': '${now}'})
        assert rest_api.delete(f'{FIELD_RULES}/{public_id}').status_code == HTTPStatus.ACCEPTED
        assert rest_api.get(f'{FIELD_RULES}/{public_id}').status_code == HTTPStatus.NOT_FOUND

    def test_every_problem_in_one_400(self, rest_api) -> None:
        """A missing field and a location-less unknown trigger field, both named"""
        response = _create_rule(rest_api, when={'changed': ['nowhere']}, set={'gone': 'x'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        message: str = response.get_json()['message']
        assert "'gone'" in message and "'nowhere'" in message

    def test_the_name_is_unique_and_fixed(self, rest_api) -> None:
        """A second rule under the name, a rename"""
        public_id: int = _create_rule(rest_api).get_json()['result_id']

        assert _create_rule(rest_api).status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.put(f'{FIELD_RULES}/{public_id}', json={'name': 'other'}).status_code == \
            HTTPStatus.BAD_REQUEST
        assert rest_api.put(f'{FIELD_RULES}/{public_id}', json={'active': False}).status_code == HTTPStatus.ACCEPTED

    def test_an_overlapping_rule_is_refused(self, rest_api) -> None:
        """A second rule setting the same field on the same Type"""
        _create_rule(rest_api)

        assert _create_rule(rest_api, name='second').status_code == HTTPStatus.BAD_REQUEST

    def test_the_check_answers_the_reach(self, rest_api) -> None:
        """The rule as it would be stored and the objects per Type - nothing stored"""
        response = rest_api.post(f'{FIELD_RULES}/check', json=RULE_BODY)

        assert response.status_code == HTTPStatus.OK, response.get_json()
        result: dict[str, Any] = response.get_json()['result']
        assert (result['types'], result['objects']) == ([{'type_id': SERVER, 'objects': 1}], 1)
        assert rest_api.get(FIELD_RULES).get_json()['total'] == 0

    def test_the_list_narrowed_to_a_group(self, rest_api) -> None:
        """The operators write host - the rule is theirs to trigger; an unknown group is a 404"""
        public_id: int = _create_rule(rest_api).get_json()['result_id']
        response = rest_api.get(FIELD_RULES, query_string={'group_id': OPERATORS})

        assert [rule['public_id'] for rule in response.get_json()['results']] == [public_id]
        assert rest_api.get(FIELD_RULES, query_string={'group_id': 99999}).status_code == HTTPStatus.NOT_FOUND


class TestObjectWrites:
    """The rule on the object writes"""

    def test_a_triggering_edit_is_stamped_and_logged(self, rest_api, db) -> None:
        """The operator changes host; the server stamps reviewed_at; the log entry names the rule"""
        rule_id: int = _create_rule(rest_api).get_json()['result_id']
        response = rest_api.put(f'/objects/{OBJECT_ID}', json=_body(OBJECT_ID, host='b'), **_operator())

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert isinstance(_stored_value(db, OBJECT_ID, 'reviewed_at'), datetime)
        log: dict[str, Any] = db[CmdbMetaLog.COLLECTION].find_one({'object_id': OBJECT_ID, 'action': 1},
                                                                  sort=[('public_id', -1)])
        assert [(change['rule_id'], change['rule_name'], change['field'], change['before'])
                for change in log['rule_changes']] == [(rule_id, RULE_NAME, 'reviewed_at', None)]

    def test_an_untriggered_edit_stays(self, rest_api, db) -> None:
        """Changing code alone runs nothing"""
        _create_rule(rest_api)

        assert rest_api.put(f'/objects/{OBJECT_ID}', json=_body(OBJECT_ID, code='B'),
                            **_operator()).status_code == HTTPStatus.ACCEPTED
        assert _stored_value(db, OBJECT_ID, 'reviewed_at') is None

    def test_an_invalid_rule_value_refuses_the_write(self, rest_api, db) -> None:
        """A value the field's pattern refuses - stored on the rule before the pattern was set"""
        _create_rule(rest_api, set={'code': 'ABC'})
        db[CmdbType.COLLECTION].update_one({'public_id': SERVER, 'fields.name': 'code'},
                                           {'$set': {'fields.$.regex': '^[0-9]+$'}})
        response = rest_api.put(f'/objects/{OBJECT_ID}', json=_body(OBJECT_ID, host='b', code='1'), **_operator())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f"'{RULE_NAME}'" in response.get_json()['message']

    def test_a_create_fills_the_system_default_after_the_check(self, rest_api, db) -> None:
        """The operator may not write origin, but its default is the server's"""
        response = rest_api.post('/objects/', json={**_body(CREATED), 'fields': [{'name': 'host', 'value': 'n'}]},
                                 **_operator())

        assert response.status_code == HTTPStatus.OK, response.get_json()
        assert _stored_value(db, CREATED, 'origin') == ORIGIN_DEFAULT


class TestGuards:
    """Rules and the other writes"""

    def test_a_type_change_removing_the_rule_s_field_is_refused(self, rest_api, db) -> None:
        """The Type update names the rule"""
        del db
        _create_rule(rest_api)
        answered: dict[str, Any] = rest_api.get(f'/types/{SERVER}').get_json()['result']
        answered['fields'] = [field for field in answered['fields'] if field['name'] != 'reviewed_at']
        answered['render_meta']['sections'][0]['fields'].remove('reviewed_at')
        response = rest_api.put(f'/types/{SERVER}', json=answered)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert RULE_NAME in response.get_json()['message']

    def test_a_scope_comparing_a_rule_set_field_is_refused(self, rest_api) -> None:
        """The scope check names the rule"""
        rule_id: int = _create_rule(rest_api, set={'code': 'ABC'}, when={'changed': ['host']}).get_json()['result_id']
        response = rest_api.post('/access/assignments/check', json={
            'role_id': OPERATOR_ROLE, 'scope': [{'field': 'code', 'op': 'equals', 'value': 'ABC'}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()
        assert str(rule_id) in response.get_json()['message']
