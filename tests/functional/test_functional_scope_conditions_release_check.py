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
The release check of scope conditions (phase 9, R33): a conditional assignment decides through the real routes

A user group holds a scope role on a Type through one assignment with a condition (``size >= 10``); the
administrators hold every operation on the Type unconditionally (else the lock guard refuses the conditional one).
Objects of the Type in and out of the condition. Pinned as the user: the list answers only the matching objects, a
single read of another one is a 403, a create in the scope passes and out of it is a 403, an edit moving an object
out is a 403, the render answers ``allowed_operations`` per object, the Type's history is hidden; a webhook of the user
receives an edit only while the object stays in the scope. As an administrator:
the assignment routes store a condition list cast, ``/check`` judges without writing, the catalogue answers, a
conditional assignment on an open Type is the lock guard's 400. A list under ten conditional assignments is timed
"""
import json
import time
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
from cmdb.framework.scope_compiler import ScopeMessage
from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 98901
USER_ID: int = 98911
TYPE_ID: int = 98921
OPEN_TYPE_ID: int = 98922
ROLE_ID: int = 98931
ADMIN_ROLE_ID: int = 98932
OPEN_ROLE_ID: int = 98933
ASSIGNMENT_ID: int = 98941
ADMIN_ASSIGNMENT_ID: int = 98942
VIEW_ROLE_ID: int = 98934
VIEW_ASSIGNMENT_ID: int = 98943
IN_ID: int = 98951
OUT_ID: int = 98952
HOOK_OBJECT_ID: int = 98953
CREATED_FIRST_ID: int = 98954
LOG_ID: int = 98961
NODE_ID: int = 98962
HOOK_ID: int = 98971
TIMED_OBJECTS_FROM: int = 99000
TIMED_OBJECTS: int = 500
TIMED_ASSIGNMENTS: int = 10
TIMED_BUDGET_SECONDS: float = 5.0
ADMIN_GROUP_ID: int = 1
THRESHOLD: int = 10
IN_SIZE: int = 16
OUT_SIZE: int = 4
SCOPE: list[dict[str, Any]] = [{'field': 'size', 'op': 'gte', 'value': THRESHOLD}]
OPERATIONS: list[str] = ['view', 'create', 'edit', 'delete']
GROUP_RIGHTS: list[str] = ['base.framework.*', 'base.access.view']
HOOK_URL: str = 'http://scope-conditions.test/hook'


def _type(type_id: int) -> dict[str, Any]:
    """A Type with a text and a number field"""
    return {'public_id': type_id, 'name': f'scope-release-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'fields': [{'type': 'text', 'name': 'host', 'label': 'Host'},
                       {'type': 'number', 'name': 'size', 'label': 'Size'}],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                          'fields': ['host', 'size']}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _object(public_id: int, size: int, type_id: int = TYPE_ID) -> dict[str, Any]:
    """A stored object of the Type"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
            'fields': [{'name': 'host', 'value': f'h{public_id}', 'type': 'text'},
                       {'name': 'size', 'value': size, 'type': 'number'}]}


def _role(role_id: int, types: list[int]) -> dict[str, Any]:
    """Every operation, writing regular fields"""
    return {'public_id': role_id, 'name': f'scope-release-{role_id}', 'description': '', 'types': types,
            'operations': OPERATIONS, 'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int, scope: Any) -> dict[str, Any]:
    """An assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': scope, 'description': ''}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The group, its user, the Types, the roles, both assignments, the objects and a log; all removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': GROUP_ID, 'name': 'scope-release', 'label': 'G',
                                                   'rights': GROUP_RIGHTS})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': 'scope-release', 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbType.COLLECTION].insert_many([_type(TYPE_ID), _type(OPEN_TYPE_ID)])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(ROLE_ID, [TYPE_ID]), _role(ADMIN_ROLE_ID, [TYPE_ID]),
                                                    _role(OPEN_ROLE_ID, [OPEN_TYPE_ID])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(ASSIGNMENT_ID, GROUP_ID, ROLE_ID, SCOPE),
        _assignment(ADMIN_ASSIGNMENT_ID, ADMIN_GROUP_ID, ADMIN_ROLE_ID, '*')])
    database[CmdbObject.COLLECTION].insert_many([_object(IN_ID, IN_SIZE), _object(OUT_ID, OUT_SIZE),
                                                 _object(HOOK_OBJECT_ID, IN_SIZE)])
    database[CmdbMetaLog.COLLECTION].insert_one({
        'public_id': LOG_ID, 'log_type': 'CmdbObjectLog', 'object_id': IN_ID, 'type_id': TYPE_ID, 'action': 1,
        'action_name': 'EDIT', 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin', 'comment': '',
        'changes': [], 'render_state': b'{}', 'log_time': None})

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_many({'public_id': USER_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, OPEN_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [TYPE_ID, OPEN_TYPE_ID]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$gte': IN_ID}})
    database[CmdbWebhook.COLLECTION].delete_many({'public_id': HOOK_ID})
    database[CmdbWebhookEvent.COLLECTION].delete_many({'webhook_id': HOOK_ID})


def _user() -> dict[str, Any]:
    """The request kwargs sending it as the group's user"""
    return {'user': CmdbUser(public_id=USER_ID, user_name='scope-release', active=True, group_ids=[GROUP_ID])}


def _listed(rest_api: Any, **kwargs: Any) -> list[int]:
    """The ids GET /objects/ answers for the Type"""
    response = rest_api.get('/objects/', query_string={'filter': json.dumps({'type_id': TYPE_ID}), 'view': 'native',
                                                       'limit': 0}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return sorted(document['public_id'] for document in response.get_json()['results'])


def _body(public_id: int, size: int) -> dict[str, Any]:
    """A whole-object write body"""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': USER_ID, 'version': '1.0.0',
            'fields': [{'name': 'host', 'value': f'h{public_id}'}, {'name': 'size', 'value': size}]}


class TestTheUserSeesTheMatchingObjects:
    """Lists, single reads, the render"""

    def test_the_list_answers_only_the_matching_objects(self, rest_api) -> None:
        """The administrators see all three"""
        assert _listed(rest_api, **_user()) == [IN_ID, HOOK_OBJECT_ID]
        assert _listed(rest_api) == [IN_ID, OUT_ID, HOOK_OBJECT_ID]

    def test_a_single_read_outside_the_scope_is_a_403(self, rest_api) -> None:
        """Inside it a 200"""
        assert rest_api.get(f'/objects/{IN_ID}', **_user()).status_code == HTTPStatus.OK
        assert rest_api.get(f'/objects/{OUT_ID}', **_user()).status_code == HTTPStatus.FORBIDDEN

    def test_the_render_answers_the_operations_per_object(self, rest_api, db: Any) -> None:
        """The group also views every object: the one outside the condition renders view only; the Type answers every
        operation ("on some objects")"""
        db[CmdbScopeRole.COLLECTION].insert_one({**_role(VIEW_ROLE_ID, [TYPE_ID]), 'operations': ['view']})
        db[CmdbAccessAssignment.COLLECTION].insert_one(_assignment(VIEW_ASSIGNMENT_ID, GROUP_ID, VIEW_ROLE_ID, '*'))

        def operations(object_id: int) -> list[str]:
            response = rest_api.get(f'/objects/{object_id}', **_user())
            assert response.status_code == HTTPStatus.OK

            return response.get_json()['type_information']['allowed_operations']

        assert operations(IN_ID) == OPERATIONS
        assert operations(OUT_ID) == ['view', 'create']
        assert rest_api.get(f'/types/{TYPE_ID}', **_user()).get_json()['result']['allowed_operations'] == OPERATIONS

    def test_the_types_history_is_hidden(self, rest_api) -> None:
        """A log stamps the Type, not the object's state"""
        response = rest_api.get(f'/logs/object/{IN_ID}', **_user())

        assert response.status_code == HTTPStatus.OK
        assert LOG_ID not in [log['public_id'] for log in response.get_json()['results']]
        assert LOG_ID in [log['public_id'] for log in rest_api.get(f'/logs/object/{IN_ID}').get_json()['results']]

    def test_a_log_is_never_judged_as_an_object(self, rest_api, db: Any) -> None:
        """A within condition names the location by its id - a log carrying that id stays hidden"""
        db[CmdbAccessAssignment.COLLECTION].update_one({'public_id': ASSIGNMENT_ID},
                                                       {'$set': {'scope': [{'within': IN_ID}]}})
        db[CmdbLocation.COLLECTION].insert_one({
            'public_id': NODE_ID, 'name': 'scope-release', 'parent': RootLocationDefault.PUBLIC_ID, 'object_id': IN_ID,
            'type_id': TYPE_ID, 'type_label': 'T', 'type_icon': 'fa-cube', 'type_selectable': True})
        db[CmdbMetaLog.COLLECTION].update_one({'public_id': LOG_ID}, {'$set': {'public_id': IN_ID}})

        try:
            response = rest_api.get(f'/logs/object/{IN_ID}', **_user())

            assert response.status_code == HTTPStatus.OK
            assert response.get_json()['results'] == []
        finally:
            db[CmdbLocation.COLLECTION].delete_many({'public_id': NODE_ID})


class TestTheUserWritesInsideTheScope:
    """Create and edit judge the written state"""

    def test_a_create_inside_passes_and_outside_is_a_403(self, rest_api, db: Any) -> None:
        """Nothing stored for the refused one"""
        inside = rest_api.post('/objects/', json=_body(CREATED_FIRST_ID, IN_SIZE), **_user())
        outside = rest_api.post('/objects/', json=_body(CREATED_FIRST_ID + 1, OUT_SIZE), **_user())

        assert inside.status_code == HTTPStatus.OK, inside.get_json()
        assert outside.status_code == HTTPStatus.FORBIDDEN
        assert db[CmdbObject.COLLECTION].count_documents({'public_id': CREATED_FIRST_ID + 1}) == 0

    def test_an_edit_moving_an_object_out_is_a_403(self, rest_api, db: Any) -> None:
        """An edit staying inside passes"""
        assert rest_api.put(f'/objects/{IN_ID}', json=_body(IN_ID, OUT_SIZE),
                            **_user()).status_code == HTTPStatus.FORBIDDEN
        assert rest_api.put(f'/objects/{IN_ID}', json=_body(IN_ID, IN_SIZE + 1),
                            **_user()).status_code == HTTPStatus.ACCEPTED
        assert db[CmdbObject.COLLECTION].find_one({'public_id': IN_ID})['fields'][1]['value'] == IN_SIZE + 1


def test_a_webhook_receives_only_objects_inside_its_owners_scope(
        rest_api, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The administrator edits: staying inside is delivered, moving out is not (before AND after judged)"""
    db[CmdbWebhook.COLLECTION].insert_one({'public_id': HOOK_ID, 'name': 'scope-release', 'url': HOOK_URL,
                                           'event_types': ['UPDATE'], 'active': True, 'owner_id': USER_ID})
    posted: list[str] = []

    def _post(url: str, **_kwargs: Any) -> Any:
        posted.append(url)
        return SimpleNamespace(status_code=HTTPStatus.OK)

    monkeypatch.setattr(webhook_helper.DISPATCH_EXECUTOR, 'submit', lambda fn, *args, **kwargs: fn(*args, **kwargs))
    monkeypatch.setattr(webhook_helper, 'refused_destination_reason', lambda *_a, **_k: None)
    monkeypatch.setattr(webhook_helper.requests, 'post', _post)

    assert rest_api.put(f'/objects/{HOOK_OBJECT_ID}', json=_body(HOOK_OBJECT_ID, IN_SIZE + 1)).status_code == \
        HTTPStatus.ACCEPTED
    assert posted == [HOOK_URL]

    assert rest_api.put(f'/objects/{HOOK_OBJECT_ID}', json=_body(HOOK_OBJECT_ID, OUT_SIZE)).status_code == \
        HTTPStatus.ACCEPTED
    assert posted == [HOOK_URL]


class TestTheAssignmentRoutes:
    """As the administrator"""

    def test_a_condition_list_is_stored_cast(self, rest_api, db: Any) -> None:
        """The value cast to the field's kind, the list canonical"""
        response = rest_api.post('/access/assignments', json={
            'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': [{'op': 'in', 'value': ['16', 4], 'field': 'size'}]})

        assert response.status_code == HTTPStatus.CREATED, response.get_json()
        stored = db[CmdbAccessAssignment.COLLECTION].find_one({'public_id': response.get_json()['result_id']})
        assert stored['scope'] == [{'field': 'size', 'op': 'in', 'value': [4, 16]}]

    def test_every_problem_is_one_400(self, rest_api, db: Any) -> None:
        """Nothing written"""
        response = rest_api.post('/access/assignments', json={
            'group_id': GROUP_ID, 'role_id': ROLE_ID,
            'scope': [{'field': 'gone', 'op': 'exists'}, {'field': 'host', 'op': 'gt', 'value': 3}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == ' '.join([
            ScopeMessage.NO_CARRIER.value.format(field='gone'),
            ScopeMessage.OPERATOR_NOT_FOR_KIND.value.format(field='host', kind='text', op='gt')])
        assert db[CmdbAccessAssignment.COLLECTION].count_documents({}) == 2

    def test_the_check_answers_the_stored_form_and_writes_nothing(self, rest_api, db: Any) -> None:
        """And the save's refusal"""
        response = rest_api.post('/access/assignments/check',
                                 json={'role_id': ROLE_ID, 'scope': [{'field': 'size', 'op': 'gte', 'value': '8'}]})

        assert response.status_code == HTTPStatus.OK, response.get_json()
        assert response.get_json()['result'] == {'role_id': ROLE_ID,
                                                 'scope': [{'field': 'size', 'op': 'gte', 'value': 8}]}
        assert db[CmdbAccessAssignment.COLLECTION].count_documents({}) == 2

        missing = rest_api.post('/access/assignments/check', json={'role_id': ROLE_ID + 99, 'scope': '*'})
        refusal: str = AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=ROLE_ID + 99)
        assert (missing.status_code, missing.get_json()['message']) == (HTTPStatus.BAD_REQUEST, refusal)

    def test_the_catalogue_answers(self, rest_api) -> None:
        """For a viewer of the access rules too"""
        response = rest_api.get('/access/scope_catalogue', **_user())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['kind_operators']['number'][-2:] == ['exists', 'is_empty']

    def test_a_conditional_assignment_on_an_open_type_is_the_lock_guards_400(self, rest_api) -> None:
        """Nobody would view all its objects"""
        response = rest_api.post('/access/assignments', json={'group_id': GROUP_ID, 'role_id': OPEN_ROLE_ID,
                                                              'scope': SCOPE})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == AccessRuleMessage.TYPES_LOCKED.value.format(ids=[OPEN_TYPE_ID])


def test_a_list_under_ten_conditional_assignments_is_timed(rest_api, db: Any) -> None:
    """A basic timing (R33) - load tests are phase 16"""
    db[CmdbObject.COLLECTION].insert_many([_object(TIMED_OBJECTS_FROM + offset, offset % (2 * THRESHOLD))
                                           for offset in range(TIMED_OBJECTS)])
    db[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(ASSIGNMENT_ID + 100 + offset, GROUP_ID, ROLE_ID,
                    [{'field': 'size', 'op': 'equals', 'value': offset}, {'field': 'host', 'op': 'exists'}])
        for offset in range(TIMED_ASSIGNMENTS - 1)])

    started: float = time.perf_counter()
    listed: list[int] = _listed(rest_api, **_user())
    elapsed: float = time.perf_counter() - started

    # size >= THRESHOLD, or one of the sizes 0 .. TIMED_ASSIGNMENTS - 2 the extra assignments name (OUT_SIZE among them)
    expected = [IN_ID, OUT_ID, HOOK_OBJECT_ID] + [TIMED_OBJECTS_FROM + offset for offset in range(TIMED_OBJECTS)
                                                  if offset % (2 * THRESHOLD) >= THRESHOLD
                                                  or offset % (2 * THRESHOLD) < TIMED_ASSIGNMENTS - 1]
    assert listed == sorted(expected)
    assert elapsed < TIMED_BUDGET_SECONDS, elapsed
    print(f'\n[scope timing] {TIMED_ASSIGNMENTS} conditional assignments, {TIMED_OBJECTS + 3} objects: '
          f'{elapsed * 1000:.0f} ms')
