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
Functional tests of ``POST /access/assignments/simulate`` (phase 11)

Seeded: a server Type (size, host) and a router Type; eight servers and two routers; a person linked to one user of the
simulated group. Pinned: the count per Type, the total and ten samples with their summary; the caller's own view
limiting it (a delegate seeing only some servers - D2); a token scope counted per member, a member without a linked
person warned (D3); a change answering gained / lost (D4); the members named only for a caller who may view users
(D5); each warning (D6); the Types a first assignment newly restricts; the 400s of a save, the 404 of a gone
assignment, the 403 without ``base.access.view``, and the 503 past the time budget. Nothing is written
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.manager import ObjectsManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE: str = '/access/assignments/simulate'
GROUP_ID, DELEGATE_GROUP_ID = 94901, 94902
MEMBER_IDS: list[int] = [94911, 94912]
DELEGATE_ID: int = 94913
SERVER_TYPE_ID, ROUTER_TYPE_ID, PERSON_TYPE_ID = 94921, 94922, 94923
ROLE_ID, BOTH_ROLE_ID, DELEGATE_ROLE_ID, ADMIN_ROLE_ID = 94931, 94932, 94933, 94934
STORED_ID, DELEGATE_ASSIGNMENT_ID, ADMIN_ASSIGNMENT_ID = 94941, 94942, 94943
SERVERS: dict[int, int] = {94950 + index: index * 4 for index in range(1, 9)}
ROUTERS: list[int] = [94961, 94962]
PERSON_ID: int = 94971
ADMIN_GROUP_ID: int = 1
OPERATIONS: list[str] = ['view', 'create', 'edit', 'delete']
BIG: list[dict[str, Any]] = [{'field': 'size', 'op': 'gte', 'value': 16}]


def _type(type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A Type"""
    return {'public_id': type_id, 'name': f'simulate-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'fields': fields, 'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']},
                                              'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                                            'fields': [field['name'] for field in fields]}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


SERVER_FIELDS: list[dict[str, Any]] = [{'type': 'text', 'name': 'host', 'label': 'Host'},
                                       {'type': 'number', 'name': 'size', 'label': 'Size'},
                                       {'type': 'person', 'name': 'owner', 'label': 'Owner', 'selectable': ['PERSON']}]


def _server(public_id: int, size: int) -> dict[str, Any]:
    """A server; the first one owned by the linked person"""
    return {'public_id': public_id, 'type_id': SERVER_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
            'fields': [{'name': 'host', 'value': f'srv{public_id}', 'type': 'text'},
                       {'name': 'size', 'value': size, 'type': 'number'},
                       {'name': 'owner', 'value': PERSON_ID if public_id == min(SERVERS) else None,
                        'type': 'person'}]}


def _role(role_id: int, types: Any, operations: list[str] = OPERATIONS) -> dict[str, Any]:
    """A scope role"""
    return {'public_id': role_id, 'name': f'simulate-{role_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int, scope: Any) -> dict[str, Any]:
    """An assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': scope, 'description': ''}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The groups, users, Types, roles, the stored assignment, the delegate's own one and the objects; removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': GROUP_ID, 'name': 'simulated', 'label': 'G', 'rights': ['base.framework.*']},
        {'public_id': DELEGATE_GROUP_ID, 'name': 'simulate-delegate', 'label': 'D',
         'rights': ['base.framework.*', 'base.access.view']}])
    database[CmdbUser.COLLECTION].insert_many([
        *[{'public_id': user_id, 'user_name': f'member-{user_id}', 'active': True, 'group_ids': [GROUP_ID],
           'registration_time': datetime.now(timezone.utc)} for user_id in MEMBER_IDS],
        {'public_id': DELEGATE_ID, 'user_name': 'simulate-delegate', 'active': True, 'group_ids': [DELEGATE_GROUP_ID],
         'registration_time': datetime.now(timezone.utc)}])
    database[CmdbType.COLLECTION].insert_many([_type(SERVER_TYPE_ID, SERVER_FIELDS),
                                               _type(ROUTER_TYPE_ID, SERVER_FIELDS[:1]),
                                               _type(PERSON_TYPE_ID, SERVER_FIELDS[:1])])
    database[CmdbScopeRole.COLLECTION].insert_many([
        _role(ROLE_ID, [SERVER_TYPE_ID]), _role(BOTH_ROLE_ID, [SERVER_TYPE_ID, ROUTER_TYPE_ID]),
        _role(DELEGATE_ROLE_ID, [SERVER_TYPE_ID], ['view']),
        _role(ADMIN_ROLE_ID, [SERVER_TYPE_ID])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(STORED_ID, GROUP_ID, ROLE_ID, [{'field': 'size', 'op': 'gte', 'value': 24}]),
        _assignment(DELEGATE_ASSIGNMENT_ID, DELEGATE_GROUP_ID, DELEGATE_ROLE_ID,
                    [{'field': 'size', 'op': 'lte', 'value': 20}]),
        _assignment(ADMIN_ASSIGNMENT_ID, ADMIN_GROUP_ID, ADMIN_ROLE_ID, '*')])
    database[CmdbObject.COLLECTION].insert_many([
        *[_server(public_id, size) for public_id, size in SERVERS.items()],
        *[{**_server(public_id, 0), 'type_id': ROUTER_TYPE_ID} for public_id in ROUTERS],
        {**_server(PERSON_ID, 0), 'type_id': PERSON_TYPE_ID,
         'system_ref': {'kind': 'user', 'id': MEMBER_IDS[0]}}])

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [GROUP_ID, DELEGATE_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [*MEMBER_IDS, DELEGATE_ID]}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVER_TYPE_ID, ROUTER_TYPE_ID,
                                                                     PERSON_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [SERVER_TYPE_ID, ROUTER_TYPE_ID,
                                                                     PERSON_TYPE_ID]}})


def _simulate(rest_api: Any, scope: Any, role_id: int = ROLE_ID, **extra: Any) -> Any:
    """One simulation as the administrator, or as whoever ``user`` names"""
    user: Any = extra.pop('user', None)
    kwargs: dict[str, Any] = {'user': user} if user else {}

    return rest_api.post(ROUTE, json={'group_id': GROUP_ID, 'role_id': role_id, 'scope': scope, **extra}, **kwargs)


def _codes(answer: dict[str, Any]) -> list[str]:
    """The warnings' codes"""
    return [warning['code'] for warning in answer['warnings']]


def _big_ids() -> list[int]:
    """The servers of size 16 or more"""
    return sorted(public_id for public_id, size in SERVERS.items() if size >= 16)


def test_counts_per_type_samples_and_members(rest_api, db: Any) -> None:
    """Within the administrator's view: every server; nothing written"""
    before: int = db[CmdbAccessAssignment.COLLECTION].count_documents({})

    response = _simulate(rest_api, BIG)

    assert response.status_code == HTTPStatus.OK, response.get_json()
    answer: dict[str, Any] = response.get_json()['result']
    assert (answer['total'], answer['by_type']) == (len(_big_ids()), [{'type_id': SERVER_TYPE_ID,
                                                                       'count': len(_big_ids())}])
    assert [sample['public_id'] for sample in answer['samples']] == _big_ids()
    assert answer['samples'][0]['summary'] and answer['within_callers_view'] is True
    assert answer['members'] == {'member_count': 2, 'members': [
        {'user_id': user_id, 'user_name': f'member-{user_id}'} for user_id in MEMBER_IDS]}
    assert answer['scope'] == BIG and not answer['warnings']
    assert db[CmdbAccessAssignment.COLLECTION].count_documents({}) == before


def test_a_delegate_counts_only_what_it_sees_and_no_names(rest_api) -> None:
    """D2 + D5: the delegate views the servers of size 20 or less, and may not view users"""
    delegate = CmdbUser(public_id=DELEGATE_ID, user_name='simulate-delegate', active=True,
                        group_ids=[DELEGATE_GROUP_ID])

    answer: dict[str, Any] = _simulate(rest_api, BIG, user=delegate).get_json()['result']

    assert [sample['public_id'] for sample in answer['samples']] == [
        public_id for public_id in _big_ids() if SERVERS[public_id] <= 20]
    assert answer['members'] == {'member_count': 2}


def test_a_change_answers_gained_and_lost(rest_api) -> None:
    """D4: from size >= 24 to size >= 16 gains 16 and 20, loses nothing"""
    answer: dict[str, Any] = _simulate(rest_api, BIG, assignment_id=STORED_ID).get_json()['result']

    assert answer['gained']['count'] == 2
    assert [sample['public_id'] for sample in answer['gained']['samples']] == [
        public_id for public_id in _big_ids() if SERVERS[public_id] < 24]
    assert answer['lost'] == {'count': 0, 'samples': []}


def test_a_token_scope_is_counted_per_member(rest_api) -> None:
    """D3: the member with a linked person reaches its server; the other is warned"""
    answer: dict[str, Any] = _simulate(rest_api, [{'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}}])
    answer = answer.get_json()['result']

    assert answer['members']['simulated_members'] == [{'user_id': MEMBER_IDS[0], 'count': 1},
                                                      {'user_id': MEMBER_IDS[1], 'count': 0}]
    assert answer['total'] == 1
    assert 'unresolved_token' in _codes(answer)


@pytest.mark.parametrize('scope, code', [
    ([{'field': 'host', 'op': 'contains', 'value': 'srv'}], 'unindexed_contains'),
    ([{'field': 'size', 'op': 'not_equals', 'value': 4}], 'poorly_indexed'),
    ([{'field': 'size', 'op': 'gte', 'value': 1000}], 'empty'),
    ([{'field': 'size', 'op': 'gte', 'value': 0}], 'every_object'),
], ids=['contains', 'negation', 'empty', 'every-object'])
def test_each_condition_warning(rest_api, scope: list[dict[str, Any]], code: str) -> None:
    """Each named"""
    assert code in _codes(_simulate(rest_api, scope).get_json()['result'])


def test_a_first_assignment_on_a_type_newly_restricts_it(rest_api) -> None:
    """The router Type is open (no assignment names it): assigning it restricts it for every other group"""
    answer: dict[str, Any] = _simulate(rest_api, '*', role_id=BOTH_ROLE_ID).get_json()['result']

    assert answer['newly_restricted_types'] == [ROUTER_TYPE_ID]
    assert 'newly_restricted' in _codes(answer)
    assert answer['total'] == len(SERVERS) + len(ROUTERS)


@pytest.mark.parametrize('body, status', [
    ({'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': [{'field': 'gone', 'op': 'exists'}]}, HTTPStatus.BAD_REQUEST),
    ({'group_id': 1, 'role_id': 99999, 'scope': '*'}, HTTPStatus.BAD_REQUEST),
    ({'group_id': 99999, 'role_id': ROLE_ID, 'scope': '*'}, HTTPStatus.BAD_REQUEST),
    ({'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': '*', 'assignment_id': 99999}, HTTPStatus.NOT_FOUND),
    ({'role_id': ROLE_ID, 'scope': '*'}, HTTPStatus.BAD_REQUEST),
], ids=['bad-field', 'gone-role', 'gone-group', 'gone-assignment', 'no-group'])
def test_the_refusals(rest_api, body: dict[str, Any], status: HTTPStatus) -> None:
    """As a save, plus the 404"""
    assert rest_api.post(ROUTE, json=body).status_code == status


def test_without_the_view_right_it_is_a_403(rest_api) -> None:
    """base.access.view"""
    member = CmdbUser(public_id=MEMBER_IDS[0], user_name='member', active=True, group_ids=[GROUP_ID])

    assert _simulate(rest_api, '*', user=member).status_code == HTTPStatus.FORBIDDEN


def test_past_the_time_budget_it_is_the_shared_503(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """P1"""
    def _too_slow(*_args: Any, **_kwargs: Any) -> Any:
        timeout = DocumentQueryTimeLimitError('stopped', QUERY_TIME_LIMIT_MS)
        raise BaseManagerIterationError(timeout) from timeout

    monkeypatch.setattr(ObjectsManager, 'aggregate_within_time_limit', _too_slow)

    assert _simulate(rest_api, BIG).status_code == HTTPStatus.SERVICE_UNAVAILABLE
