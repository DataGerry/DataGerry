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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Functional tests: the stored scope conditions stay valid (phase 9 step 3, ruled R11), through the real REST app

A conditional assignment is seeded directly; the administrators hold every operation on the Types through an
unconditional one. Its role covers a
Type; its conditions compare a field of the Type and one from a global template. Pinned: a Type update removing or
retyping a compared field is a 400 naming the field and the assignment, nothing written; keeping them passes; a
template update retyping its compared field is refused; a role update adding a Type that carries a compared field with
another kind is refused, adding one without it passes
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.framework.scope_compiler import ScopeMessage
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9961
OTHER_TYPE_ID: int = 9962
PLAIN_TYPE_ID: int = 9963
TEMPLATE_ID: int = 9964
ROLE_ID: int = 9965
ASSIGNMENT_ID: int = 9966
GROUP_ID: int = 9967
ADMIN_ROLE_ID: int = 9968
TEMPLATE_NAME: str = 'fn-scope-template'
SCOPE: list[dict[str, Any]] = [{'field': 'badge', 'op': 'exists'}, {'field': 'host', 'op': 'equals', 'value': 'a'}]


def _type(type_id: int, host_kind: str = 'text', with_template: bool = True) -> dict[str, Any]:
    """A Type carrying host (and the template's badge)"""
    fields: list[dict[str, Any]] = [{'type': host_kind, 'name': 'host', 'label': 'Host'},
                                    {'type': 'number', 'name': 'size', 'label': 'Size'}]
    sections: list[dict[str, Any]] = [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host', 'size']}]

    if with_template:
        fields.append({'type': 'text', 'name': 'badge', 'label': 'Badge'})
        sections.append({'type': SectionType.SECTION.value, 'name': TEMPLATE_NAME, 'label': 'Badge',
                         'fields': ['badge']})

    return {'public_id': type_id, 'name': f'fn-scope-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'fields': fields, 'global_template_ids': [TEMPLATE_NAME] if with_template else [],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': []}, 'sections': sections},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types, the global template, the role on TYPE_ID and its conditional assignment"""
    database = database_manager.connector.client[database_name]
    database[CmdbSectionTemplate.COLLECTION].insert_one({
        'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Badge', 'type': SectionType.SECTION.value,
        'is_global': True, 'predefined': False, 'fields': [{'type': 'text', 'name': 'badge', 'label': 'Badge'}]})
    database[CmdbType.COLLECTION].insert_many([_type(TYPE_ID), _type(OTHER_TYPE_ID, host_kind='number'),
                                               _type(PLAIN_TYPE_ID, with_template=False)])
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': ROLE_ID, 'name': 'fn-scope-role', 'description': '',
                                                   'types': [TYPE_ID], 'operations': ['view'],
                                                   'write_regular_fields': False, 'field_classes': []})
    # The administrators keep every operation on the three Types: a conditional assignment restricts its Types, and
    # only an unconditional view keeps a Type readable (R27)
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': ADMIN_ROLE_ID, 'name': 'fn-scope-admin',
                                                   'description': '', 'types': [TYPE_ID, OTHER_TYPE_ID, PLAIN_TYPE_ID],
                                                   'operations': ['view', 'create', 'edit', 'delete'],
                                                   'write_regular_fields': True, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': ASSIGNMENT_ID, 'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': SCOPE, 'description': ''},
        {'public_id': ASSIGNMENT_ID + 10, 'group_id': 1, 'role_id': ADMIN_ROLE_ID, 'scope': '*', 'description': ''},
    ])

    yield database

    database[CmdbSectionTemplate.COLLECTION].delete_many({'public_id': TEMPLATE_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, OTHER_TYPE_ID, PLAIN_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _type_body(rest_api: Any, host_kind: str | None) -> dict[str, Any]:
    """The stored Type as a PUT body: host retyped, or removed when None"""
    body: dict[str, Any] = rest_api.get(f'/types/{TYPE_ID}').get_json()['result']
    body.pop('allowed_operations', None)

    if host_kind is None:
        body['fields'] = [field for field in body['fields'] if field['name'] != 'host']
        body['render_meta']['sections'][0]['fields'] = ['size']
    else:
        next(field for field in body['fields'] if field['name'] == 'host')['type'] = host_kind

    return body


def _stale(field: str) -> str:
    """The Type update's refusal"""
    return ScopeMessage.STALE_ON_TYPE.value.format(field=field, type_id=TYPE_ID, assignment_ids=[ASSIGNMENT_ID])


@pytest.mark.parametrize('host_kind', [None, 'number'], ids=['removed', 'retyped'])
def test_a_type_update_dropping_a_compared_field_is_refused(rest_api, db: Any, host_kind: str | None) -> None:
    """Nothing written"""
    response = rest_api.put(f'/types/{TYPE_ID}', json=_type_body(rest_api, host_kind))

    assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _stale('host'))
    assert db[CmdbType.COLLECTION].find_one({'public_id': TYPE_ID})['fields'][0]['type'] == 'text'


def test_a_type_update_keeping_the_compared_fields_passes(rest_api) -> None:
    """Another change"""
    body: dict[str, Any] = _type_body(rest_api, 'text')
    body['label'] = 'Renamed'

    assert rest_api.put(f'/types/{TYPE_ID}', json=body).status_code == HTTPStatus.ACCEPTED


def test_a_template_update_retyping_a_compared_field_is_refused(rest_api, db: Any) -> None:
    """The template's badge becomes a number - the Type carrying it is named"""
    response = rest_api.put('/section_templates/', query_string={
        'public_id': str(TEMPLATE_ID), 'name': TEMPLATE_NAME, 'label': 'Badge', 'type': SectionType.SECTION.value,
        'is_global': 'true', 'predefined': 'false',
        'fields': json.dumps([{'type': 'number', 'name': 'badge', 'label': 'Badge'}])})

    assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _stale('badge'))
    assert db[CmdbSectionTemplate.COLLECTION].find_one({'public_id': TEMPLATE_ID})['fields'][0]['type'] == 'text'


def test_a_role_update_adding_a_type_with_another_kind_is_refused(rest_api) -> None:
    """host is a number there"""
    response = rest_api.put(f'/access/scope_roles/{ROLE_ID}', json={'types': [TYPE_ID, OTHER_TYPE_ID]})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == ScopeMessage.STALE_ON_ROLE.value.format(
        role_id=ROLE_ID, assignment_id=ASSIGNMENT_ID,
        problems=ScopeMessage.KINDS_DISAGREE.value.format(field='host', kinds=['number', 'text']))


def test_a_role_update_adding_a_type_without_a_field_passes(rest_api) -> None:
    """The plain Type carries no badge - its objects never match that condition"""
    assert rest_api.put(f'/access/scope_roles/{ROLE_ID}',
                        json={'types': [TYPE_ID, PLAIN_TYPE_ID]}).status_code == HTTPStatus.ACCEPTED


def test_a_condition_on_a_field_the_role_does_not_carry_is_refused_on_save(rest_api) -> None:
    """The save judges the conditions against the role's Types (phase 9, R29) - the guard's own resolution"""
    response = rest_api.post('/access/assignments', json={'group_id': 1, 'role_id': ROLE_ID,
                                                          'scope': [{'field': 'gone', 'op': 'exists'}]})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == ScopeMessage.NO_CARRIER.value.format(field='gone')
