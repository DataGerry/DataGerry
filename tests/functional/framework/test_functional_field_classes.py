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
The release check of field classes (phase 12): the concept's operator / auditor example through the real routes

A server Type with a regular field (``host``), a field of the class ``compliance`` (``iso``, required) and a ``system``
field (``iso_at``); a global template ``iso-audit`` carried by a second Type. The operators write regular fields, the
auditors only the compliance class, the administrators both. Pinned: each writes only its fields (403 naming the
others), nobody writes a system field, the operator saves without the required compliance field and is warned; the
render answers each user's ``field_access``; the Field Protection list (with a group's view), its update (a template
field reaching every Type carrying it), its refusals and the pattern test; a type write may not change a class; a class
carried by a field cannot be deleted and its usage lists the field
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbFieldClass, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

OPERATORS, AUDITORS = 93901, 93902
OPERATOR, AUDITOR = 93911, 93912
SERVER, AUDITED = 93921, 93922
OPERATOR_ROLE, AUDITOR_ROLE, ADMIN_ROLE = 93931, 93932, 93933
CLASS_ID: int = 93941
TEMPLATE_ID: int = 93951
OBJECT_ID, CREATED = 93961, 93962
ADMIN_GROUP_ID: int = 1
TEMPLATE_NAME: str = 'dg-iso-audit-93951'
COMPLIANCE: str = 'compliance'
SERVER_FIELDS: list[dict[str, Any]] = [
    {'type': 'text', 'name': 'host', 'label': 'Host'},
    {'type': 'checkbox', 'name': 'iso', 'label': 'ISO verified', 'protection': COMPLIANCE, 'required': True},
    {'type': 'text', 'name': 'iso_at', 'label': 'ISO verified at', 'protection': 'system'},
]
TEMPLATE_FIELDS: list[dict[str, Any]] = [{'type': 'text', 'name': 'audit_note', 'label': 'Audit note'}]
FIELD_PROTECTION: str = '/access/field_protection'


def _type(type_id: int, fields: list[dict[str, Any]], template: bool = False) -> dict[str, Any]:
    """A Type - with the global template's section when it carries it"""
    sections: list[dict[str, Any]] = [{'type': 'section', 'name': 'main', 'label': 'Main',
                                       'fields': [field['name'] for field in fields]}]

    if template:
        sections.append({'type': 'section', 'name': TEMPLATE_NAME, 'label': 'Audit',
                         'fields': [field['name'] for field in TEMPLATE_FIELDS]})

    return {'public_id': type_id, 'name': f'field-classes-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc),
            'global_template_ids': [TEMPLATE_NAME] if template else [],
            'fields': [*fields, *(TEMPLATE_FIELDS if template else [])],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']}, 'sections': sections},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _role(role_id: int, operations: list[str], regular: bool, classes: list[str]) -> dict[str, Any]:
    """A scope role on the server Type"""
    return {'public_id': role_id, 'name': f'field-classes-{role_id}', 'description': '', 'types': [SERVER],
            'operations': operations, 'write_regular_fields': regular, 'field_classes': classes}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The class, the template, the Types, the groups, users, roles, assignments and one server; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbFieldClass.COLLECTION].insert_one({'public_id': CLASS_ID, 'name': COMPLIANCE, 'label': 'Compliance',
                                                    'description': ''})
    database[CmdbSectionTemplate.COLLECTION].insert_one({
        'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Audit', 'type': 'section', 'is_global': True,
        'predefined': False, 'fields': TEMPLATE_FIELDS})
    database[CmdbType.COLLECTION].insert_many([_type(SERVER, SERVER_FIELDS), _type(AUDITED, [
        {'type': 'text', 'name': 'host', 'label': 'Host'}], template=True)])
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': group_id, 'name': f'field-classes-{group_id}', 'label': 'G', 'rights': ['base.framework.*']}
        for group_id in (OPERATORS, AUDITORS)])
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': user_id, 'user_name': f'field-classes-{user_id}', 'active': True, 'group_ids': [group_id],
         'registration_time': datetime.now(timezone.utc)} for user_id, group_id in ((OPERATOR, OPERATORS),
                                                                                    (AUDITOR, AUDITORS))])
    database[CmdbScopeRole.COLLECTION].insert_many([
        _role(OPERATOR_ROLE, ['view', 'create', 'edit'], True, []),
        _role(AUDITOR_ROLE, ['view', 'edit'], False, [COMPLIANCE]),
        _role(ADMIN_ROLE, ['view', 'create', 'edit', 'delete'], True, [COMPLIANCE])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': index, 'group_id': group_id, 'role_id': role_id, 'scope': '*', 'description': ''}
        for index, (group_id, role_id) in enumerate(((OPERATORS, OPERATOR_ROLE), (AUDITORS, AUDITOR_ROLE),
                                                     (ADMIN_GROUP_ID, ADMIN_ROLE)), start=93971)])
    database[CmdbObject.COLLECTION].insert_one(
        {'public_id': OBJECT_ID, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
         'fields': [{'name': 'host', 'value': 'a', 'type': 'text'}, {'name': 'iso', 'value': False, 'type': 'checkbox'},
                    {'name': 'iso_at', 'value': None, 'type': 'text'}]})

    yield database

    database[CmdbFieldClass.COLLECTION].delete_many({'public_id': CLASS_ID})
    database[CmdbSectionTemplate.COLLECTION].delete_many({'public_id': TEMPLATE_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVER, AUDITED]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [OPERATORS, AUDITORS]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [OPERATOR, AUDITOR]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [SERVER, AUDITED]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': [OBJECT_ID, CREATED]}})


def _as(user_id: int, group_id: int) -> dict[str, Any]:
    """The request kwargs sending it as a user of the group"""
    return {'user': CmdbUser(public_id=user_id, user_name=f'field-classes-{user_id}', active=True,
                             group_ids=[group_id])}


def _body(public_id: int, host: str = 'a', iso: Any = False, iso_at: Any = None) -> dict[str, Any]:
    """A whole-object write body"""
    return {'public_id': public_id, 'type_id': SERVER, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': 'host', 'value': host}, {'name': 'iso', 'value': iso},
                       {'name': 'iso_at', 'value': iso_at}]}


def _put(rest_api: Any, body: dict[str, Any], **kwargs: Any) -> Any:
    """PUT the server"""
    return rest_api.put(f'/objects/{OBJECT_ID}', json=body, **kwargs)


class TestWritingFields:
    """Each writes only its fields"""

    def test_the_operator_writes_regular_fields_only(self, rest_api) -> None:
        """host passes, iso is the 403 naming it"""
        operator = _as(OPERATOR, OPERATORS)

        assert _put(rest_api, _body(OBJECT_ID, host='b'), **operator).status_code == HTTPStatus.ACCEPTED
        refused = _put(rest_api, _body(OBJECT_ID, host='b', iso=True), **operator)

        assert refused.status_code == HTTPStatus.FORBIDDEN
        assert 'iso' in refused.get_json()['message']

    def test_the_auditor_writes_the_compliance_class_only(self, rest_api) -> None:
        """iso passes, host is refused"""
        auditor = _as(AUDITOR, AUDITORS)

        assert _put(rest_api, _body(OBJECT_ID, iso=True), **auditor).status_code == HTTPStatus.ACCEPTED
        assert _put(rest_api, _body(OBJECT_ID, host='c', iso=True), **auditor).status_code == HTTPStatus.FORBIDDEN

    def test_nobody_writes_a_system_field(self, rest_api) -> None:
        """Not even the administrators"""
        assert _put(rest_api, _body(OBJECT_ID, iso_at='today')).status_code == HTTPStatus.FORBIDDEN

    def test_the_operator_creates_without_the_required_compliance_field_and_is_warned(self, rest_api, db) -> None:
        """Required only for whoever may write the class - the answer says so"""
        response = rest_api.post('/objects/', json=_body(CREATED, iso=None), **_as(OPERATOR, OPERATORS))

        assert response.status_code == HTTPStatus.OK, response.get_json()
        warnings = json.loads(response.headers['X-Field-Warnings'])
        assert [warning['field'] for warning in warnings] == ['iso']
        assert db[CmdbObject.COLLECTION].count_documents({'public_id': CREATED}) == 1

    def test_the_administrator_is_held_to_the_required_field(self, rest_api) -> None:
        """They may write the class"""
        assert rest_api.post('/objects/', json=_body(CREATED, iso=None)).status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize('user, expected', [
    ((OPERATOR, OPERATORS), {'host': 'write', 'iso': 'read', 'iso_at': 'system'}),
    ((AUDITOR, AUDITORS), {'host': 'read', 'iso': 'write', 'iso_at': 'system'}),
], ids=['operator', 'auditor'])
def test_the_render_answers_each_user_s_field_access(rest_api, user: tuple[int, int], expected: dict[str, str]) -> None:
    """Per field of the object"""
    response = rest_api.get(f'/objects/{OBJECT_ID}', **_as(*user))

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assert response.get_json()['type_information']['field_access'] == expected


class TestFieldProtection:
    """The list, the update, the pattern test"""

    def test_the_list_with_a_group_s_view(self, rest_api) -> None:
        """The server's own fields, what the operators may do with each"""
        response = rest_api.get(FIELD_PROTECTION, query_string={'type_id': SERVER, 'group_id': OPERATORS})

        assert response.status_code == HTTPStatus.OK, response.get_json()
        rows = {row['name']: row for row in response.get_json()['results']}
        assert set(rows) == {'host', 'iso', 'iso_at'}
        assert (rows['iso']['protection'], rows['iso']['required'], rows['iso']['reach']) == (COMPLIANCE, True,
                                                                                            [SERVER])
        assert [rows[name]['group'][0]['access'] for name in ('host', 'iso', 'iso_at')] == ['write', 'read',
                                                                                            'system']

    def test_a_template_field_reaches_every_type_carrying_it(self, rest_api, db) -> None:
        """Set on the template, copied into the Type"""
        response = rest_api.put(FIELD_PROTECTION, json={'source': 'template', 'source_id': TEMPLATE_ID,
                                                        'name': 'audit_note', 'protection': COMPLIANCE,
                                                        'audit_relevant': True})

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert response.get_json()['result']['reach'] == [AUDITED]
        copy = next(field for field in db[CmdbType.COLLECTION].find_one({'public_id': AUDITED})['fields']
                    if field['name'] == 'audit_note')
        assert (copy['protection'], copy['audit_relevant']) == (COMPLIANCE, True)

    @pytest.mark.parametrize('body, status', [
        ({'source': 'type', 'source_id': SERVER, 'name': 'host', 'protection': 'gone'}, HTTPStatus.BAD_REQUEST),
        ({'source': 'type', 'source_id': SERVER, 'name': 'host', 'regex': '('}, HTTPStatus.BAD_REQUEST),
        ({'source': 'type', 'source_id': SERVER, 'name': 'gone'}, HTTPStatus.NOT_FOUND),
        ({'source': 'type', 'source_id': AUDITED, 'name': 'audit_note'}, HTTPStatus.BAD_REQUEST),
        ({'source': 'object', 'source_id': SERVER, 'name': 'host'}, HTTPStatus.BAD_REQUEST),
        ({'source': 'type', 'source_id': 99999, 'name': 'host'}, HTTPStatus.NOT_FOUND),
    ], ids=['unknown-class', 'bad-pattern', 'unknown-field', 'template-owned', 'unknown-source-kind', 'gone-source'])
    def test_the_update_refusals(self, rest_api, body: dict[str, Any], status: HTTPStatus) -> None:
        """Nothing written"""
        assert rest_api.put(FIELD_PROTECTION, json=body).status_code == status

    def test_the_update_needs_the_field_edit_right(self, rest_api) -> None:
        """The operators hold none"""
        assert rest_api.put(FIELD_PROTECTION, json={'source': 'type', 'source_id': SERVER, 'name': 'host',
                                                    'required': True},
                            **_as(OPERATOR, OPERATORS)).status_code == HTTPStatus.FORBIDDEN

    def test_the_pattern_test(self, rest_api) -> None:
        """Anchored like an object write"""
        response = rest_api.post(f'{FIELD_PROTECTION}/regex_test', json={'regex': '[a-z]+', 'samples': ['abc', 'a1']})

        assert response.status_code == HTTPStatus.OK, response.get_json()
        assert [row['verdict'] for row in response.get_json()['result']] == ['match', 'mismatch']


def test_a_type_write_may_not_change_a_class(rest_api) -> None:
    """Sent as stored passes; changed is a 400 pointing to Field Protection"""
    stored = rest_api.get(f'/types/{SERVER}').get_json()['result']
    changed = json.loads(json.dumps(stored))
    next(field for field in changed['fields'] if field['name'] == 'iso')['protection'] = 'other'

    refused = rest_api.put(f'/types/{SERVER}', json=changed)

    assert refused.status_code == HTTPStatus.BAD_REQUEST, refused.get_json()
    assert 'Field Protection' in refused.get_json()['message']


def test_a_class_carried_by_a_field_cannot_be_deleted(rest_api) -> None:
    """The usage lists the field"""
    usage = rest_api.get(f'/access/field_classes/{CLASS_ID}/usage').get_json()['result']

    assert {'source': 'type', 'source_id': SERVER, 'name': 'iso'} in usage['fields']
    assert rest_api.delete(f'/access/field_classes/{CLASS_ID}').status_code == HTTPStatus.BAD_REQUEST
