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
Functional tests: the /access routes - field classes, scope roles, assignments

Over HTTP: each kind is created (201, the stored document), read, listed, updated (202, what the body leaves out
kept) and deleted (202, the document as it was); every write rule answers 400 - a field class's fixed name and a
taken one, unknown Types / classes, a taken role name (an update keeping its own), unknown group / role, a taken
assignment, a scope condition; the reads ask base.access.view, the writes their kind's edit right. And what holds a
document: a class a role grants and a role an assignment grants are not deleted, their usage names who; a deleted
user group takes its assignments along, a deleted Type leaves every role
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager
from cmdb.framework.access_rules import AccessRuleMessage
from cmdb.models.access_model import (
    ACCESS_RIGHTS_MIGRATION_REPORT_ID,
    MIGRATION_REPORT_COLLECTION,
    SCOPE_SHAPE_MSG,
    TYPE_ACL_MIGRATION_REPORT_ID,
    UNCONDITIONAL_SCOPE,
    CmdbAccessAssignment,
    CmdbFieldClass,
    CmdbScopeRole,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import AccessRouteMessage
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

CLASSES_URL: str = '/access/field_classes'
ROLES_URL: str = '/access/scope_roles'
ASSIGNMENTS_URL: str = '/access/assignments'
MIGRATION_REPORT_URL: str = '/access/migration_report'
TYPE_ID: int = 9501
MISSING_ID: int = 9599
NO_RIGHTS_GROUP_ID: int = 9511
NO_RIGHTS_USER_ID: int = 9512
VIEW_GROUP_ID: int = 9513
VIEW_USER_ID: int = 9514
EMPTY_GROUP_ID: int = 9515
CLASS: dict[str, Any] = {'name': 'compliance', 'label': 'Compliance'}
ROLE: dict[str, Any] = {'name': 'Operator', 'types': [TYPE_ID], 'operations': ['view', 'create']}
# Confirms a change opening a Type to every group (the Types these tests restrict are restricted by one assignment)
UNRESTRICT: dict[str, str] = {'unrestrict': 'true'}
ACCESS_COLLECTIONS: list[str] = [
    CmdbFieldClass.COLLECTION, CmdbScopeRole.COLLECTION, CmdbAccessAssignment.COLLECTION, MIGRATION_REPORT_COLLECTION,
]


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """A Type, a group without rights and a group with the view right, each with a user; the access rules empty"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_one({'public_id': TYPE_ID, 'name': 'fn-access-type', 'label': 'T',
                                              'fields': []})
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': NO_RIGHTS_GROUP_ID, 'name': 'fn-access-none', 'label': 'None', 'rights': []},
        {'public_id': VIEW_GROUP_ID, 'name': 'fn-access-view', 'label': 'View', 'rights': ['base.access.view']},
        {'public_id': EMPTY_GROUP_ID, 'name': 'fn-access-empty', 'label': 'Empty', 'rights': []},
    ])
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': NO_RIGHTS_USER_ID, 'user_name': 'fn-access-none', 'active': True,
         'group_ids': [NO_RIGHTS_GROUP_ID], 'registration_time': datetime.now(timezone.utc)},
        {'public_id': VIEW_USER_ID, 'user_name': 'fn-access-view', 'active': True, 'group_ids': [VIEW_GROUP_ID],
         'registration_time': datetime.now(timezone.utc)},
    ])

    yield database

    for collection in ACCESS_COLLECTIONS:
        database[collection].delete_many({})

    database[CmdbType.COLLECTION].delete_one({'public_id': TYPE_ID})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [NO_RIGHTS_GROUP_ID, VIEW_GROUP_ID,
                                                                          EMPTY_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [NO_RIGHTS_USER_ID, VIEW_USER_ID]}})


def _user(public_id: int, user_name: str, group_id: int) -> CmdbUser:
    """A stored user to send requests as"""
    return CmdbUser(public_id=public_id, user_name=user_name, active=True, group_ids=[group_id])


def _created(rest_api: Any, url: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST, expecting 201; the stored document"""
    response = rest_api.post(url, json=body)

    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return response.get_json()['raw']


def _message(response: Any) -> str:
    """A refusal's message"""
    return response.get_json()['message']


class TestFieldClasses:
    """/access/field_classes"""

    def test_the_lifecycle(self, rest_api) -> None:
        """Created with its default, read, listed, relabelled keeping name + description, deleted"""
        created: dict[str, Any] = _created(rest_api, CLASSES_URL, {**CLASS, 'description': 'Auditors only'})
        public_id: int = created['public_id']

        assert created == {**CLASS, 'description': 'Auditors only', 'public_id': public_id}
        assert rest_api.get(f'{CLASSES_URL}/{public_id}').get_json()['result'] == created
        assert rest_api.get(CLASSES_URL).get_json()['total'] == 1

        updated = rest_api.put(f'{CLASSES_URL}/{public_id}', json={'label': 'ISO'})
        assert updated.status_code == HTTPStatus.ACCEPTED
        assert updated.get_json()['result'] == {**created, 'label': 'ISO'}

        deleted = rest_api.delete(f'{CLASSES_URL}/{public_id}')
        assert (deleted.status_code, deleted.get_json()['raw']['label']) == (HTTPStatus.ACCEPTED, 'ISO')
        assert rest_api.get(f'{CLASSES_URL}/{public_id}').status_code == HTTPStatus.NOT_FOUND

    def test_the_name_stays(self, rest_api) -> None:
        """Renaming is refused; sending the stored name is fine"""
        public_id: int = _created(rest_api, CLASSES_URL, CLASS)['public_id']

        renamed = rest_api.put(f'{CLASSES_URL}/{public_id}', json={'name': 'audit'})
        assert renamed.status_code == HTTPStatus.BAD_REQUEST
        assert _message(renamed) == AccessRuleMessage.FIELD_CLASS_NAME_FIXED.value.format(public_id=public_id,
                                                                                          stored=CLASS['name'])
        assert rest_api.put(f'{CLASSES_URL}/{public_id}', json=CLASS).status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize('body', [{**CLASS, 'name': 'system'}, {**CLASS, 'name': 'No Slug'},
                                      {'name': 'x'}], ids=['reserved', 'no-slug', 'no-label'])
    def test_an_unusable_class_is_refused(self, rest_api, body: dict[str, Any]) -> None:
        """The schema"""
        assert rest_api.post(CLASSES_URL, json=body).status_code == HTTPStatus.BAD_REQUEST

    def test_a_taken_name_is_refused(self, rest_api) -> None:
        """The pre-check's message"""
        _created(rest_api, CLASSES_URL, CLASS)
        response = rest_api.post(CLASSES_URL, json=CLASS)

        assert (response.status_code, _message(response)) == (
            HTTPStatus.BAD_REQUEST, AccessRuleMessage.FIELD_CLASS_NAME_TAKEN.value.format(name=CLASS['name']))

    @pytest.mark.parametrize('method', ['get', 'put', 'delete'])
    def test_a_missing_class_is_a_404(self, rest_api, method: str) -> None:
        """Every route on one id"""
        kwargs: dict[str, Any] = {'json': {'label': 'x'}} if method == 'put' else {}

        assert getattr(rest_api, method)(f'{CLASSES_URL}/{MISSING_ID}', **kwargs).status_code == HTTPStatus.NOT_FOUND


class TestScopeRoles:
    """/access/scope_roles"""

    def test_the_lifecycle(self, rest_api) -> None:
        """Created with its defaults; a PUT of the operations keeps the rest"""
        class_name: str = _created(rest_api, CLASSES_URL, CLASS)['name']
        created: dict[str, Any] = _created(rest_api, ROLES_URL, {**ROLE, 'field_classes': [class_name]})

        assert created == {**ROLE, 'field_classes': [class_name], 'description': '', 'write_regular_fields': False,
                           'public_id': created['public_id']}

        updated = rest_api.put(f"{ROLES_URL}/{created['public_id']}", json={'operations': ['view']})
        assert updated.status_code == HTTPStatus.ACCEPTED
        assert updated.get_json()['result'] == {**created, 'operations': ['view']}

    def test_every_type_and_no_type_are_accepted(self, rest_api) -> None:
        """'*' and the empty list"""
        assert _created(rest_api, ROLES_URL, {**ROLE, 'types': '*'})['types'] == '*'
        assert _created(rest_api, ROLES_URL, {**ROLE, 'name': 'Nothing', 'types': [], 'operations': []})['types'] == []

    def test_unknown_types_and_classes_are_named_together(self, rest_api) -> None:
        """One 400, both problems"""
        response = rest_api.post(ROLES_URL, json={**ROLE, 'types': [TYPE_ID, MISSING_ID], 'field_classes': ['nope']})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[MISSING_ID]) in _message(response)
        assert AccessRuleMessage.UNKNOWN_FIELD_CLASSES.value.format(names=['nope']) in _message(response)

    def test_a_role_keeps_its_own_name_but_takes_no_other(self, rest_api) -> None:
        """Create clash, update clash, update keeping the name"""
        first: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        second: int = _created(rest_api, ROLES_URL, {**ROLE, 'name': 'Auditor'})['public_id']

        assert rest_api.post(ROLES_URL, json=ROLE).status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.put(f'{ROLES_URL}/{second}', json={'name': ROLE['name']}).status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.put(f'{ROLES_URL}/{first}', json={'name': ROLE['name']}).status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize('body', [{**ROLE, 'operations': ['READ']}, {**ROLE, 'types': 'all'},
                                      {**ROLE, 'field_classes': ['system']}], ids=['acl-name', 'types', 'reserved'])
    def test_an_unusable_role_is_refused(self, rest_api, body: dict[str, Any]) -> None:
        """The schema"""
        assert rest_api.post(ROLES_URL, json=body).status_code == HTTPStatus.BAD_REQUEST


class TestAssignments:
    """/access/assignments"""

    def test_the_lifecycle(self, rest_api) -> None:
        """Created; listed by group; a PUT of the description keeps the rest; deleted"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        body: dict[str, Any] = {'group_id': NO_RIGHTS_GROUP_ID, 'role_id': role_id, 'scope': '*'}
        created: dict[str, Any] = _created(rest_api, ASSIGNMENTS_URL, body)

        assert created == {**body, 'description': '', 'public_id': created['public_id']}
        listed = rest_api.get(f'{ASSIGNMENTS_URL}?filter={{"group_id": {NO_RIGHTS_GROUP_ID}}}').get_json()
        assert [item['public_id'] for item in listed['results']] == [created['public_id']]

        updated = rest_api.put(f"{ASSIGNMENTS_URL}/{created['public_id']}", json={'description': 'Fulda'})
        assert updated.get_json()['result'] == {**created, 'description': 'Fulda'}
        # The only assignment restricting the Type - its delete opens the Type and is confirmed
        assert rest_api.delete(f"{ASSIGNMENTS_URL}/{created['public_id']}",
                               query_string=UNRESTRICT).status_code == HTTPStatus.ACCEPTED

    def test_one_group_role_and_scope_once(self, rest_api) -> None:
        """The second is refused; the same group with another role is fine"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        other_role: int = _created(rest_api, ROLES_URL, {**ROLE, 'name': 'Auditor'})['public_id']
        body: dict[str, Any] = {'group_id': NO_RIGHTS_GROUP_ID, 'role_id': role_id, 'scope': '*'}
        _created(rest_api, ASSIGNMENTS_URL, body)

        response = rest_api.post(ASSIGNMENTS_URL, json=body)
        taken: str = AccessRuleMessage.ASSIGNMENT_TAKEN.value.format(group_id=NO_RIGHTS_GROUP_ID, role_id=role_id)
        assert (response.status_code, _message(response)) == (HTTPStatus.BAD_REQUEST, taken)
        _created(rest_api, ASSIGNMENTS_URL, {**body, 'role_id': other_role})

    def test_an_unknown_group_and_role_are_named_together(self, rest_api) -> None:
        """One 400, both problems"""
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': MISSING_ID, 'role_id': MISSING_ID, 'scope': '*'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert AccessRuleMessage.UNKNOWN_GROUP.value.format(group_id=MISSING_ID) in _message(response)
        assert AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=MISSING_ID) in _message(response)

    def test_a_scope_neither_every_object_nor_a_list_is_refused(self, rest_api) -> None:
        """The schema judges the type; the conditions of a list are the write rules' (phase 9, R29)"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': NO_RIGHTS_GROUP_ID, 'role_id': role_id,
                                                        'scope': {'location': {'within': 1}}})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert SCOPE_SHAPE_MSG.format(unconditional=UNCONDITIONAL_SCOPE) in _message(response)


class TestRights:
    """Reads ask base.access.view, writes their kind's edit right."""

    @pytest.mark.parametrize('url', [CLASSES_URL, ROLES_URL, ASSIGNMENTS_URL, MIGRATION_REPORT_URL])
    def test_without_the_view_right_nothing_is_read(self, rest_api, url: str) -> None:
        """403 naming the right"""
        response = rest_api.get(url, user=_user(NO_RIGHTS_USER_ID, 'fn-access-none', NO_RIGHTS_GROUP_ID))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert 'base.access.view' in _message(response)

    @pytest.mark.parametrize('url, body, right', [
        (CLASSES_URL, CLASS, 'base.access.fieldclass.edit'),
        (ROLES_URL, ROLE, 'base.access.scoperole.edit'),
        (ASSIGNMENTS_URL, {'group_id': NO_RIGHTS_GROUP_ID, 'role_id': 1, 'scope': '*'}, 'base.access.assignment.edit'),
    ], ids=['class', 'role', 'assignment'])
    def test_the_view_right_reads_but_does_not_write(self, rest_api, url: str, body: dict[str, Any],
                                                     right: str) -> None:
        """200 for the list, 403 naming the edit right for the create"""
        viewer: CmdbUser = _user(VIEW_USER_ID, 'fn-access-view', VIEW_GROUP_ID)

        assert rest_api.get(url, user=viewer).status_code == HTTPStatus.OK
        refused = rest_api.post(url, json=body, user=viewer)
        assert (refused.status_code, right in _message(refused)) == (HTTPStatus.FORBIDDEN, True)


class TestMigrationReport:
    """GET /access/migration_report"""

    def test_no_migration_ran_is_a_404(self, rest_api) -> None:
        """Neither migration wrote a report here"""
        response = rest_api.get(MIGRATION_REPORT_URL)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert _message(response) == AccessRouteMessage.NO_MIGRATION_REPORT.value

    def test_the_stored_report_without_its_id(self, rest_api, db: Any) -> None:
        """As stored - the viewer reads it"""
        report: dict[str, Any] = {'status': 'complete', 'existing_group_ids': [1], 'types': [
            {'type_id': TYPE_ID, 'acl': {'activated': True}, 'role_ids': [5], 'assignment_ids': [6],
             'dropped_group_ids': [9]}], 'inactive_type_ids': [], 'roles': [], 'assignments': []}
        db[MIGRATION_REPORT_COLLECTION].insert_one({'_id': TYPE_ACL_MIGRATION_REPORT_ID, **report,
                                                    'started_at': datetime.now(timezone.utc)})

        response = rest_api.get(MIGRATION_REPORT_URL, user=_user(VIEW_USER_ID, 'fn-access-view', VIEW_GROUP_ID))
        result: dict[str, Any] = response.get_json()['result']

        assert response.status_code == HTTPStatus.OK
        assert {key: value for key, value in result.items() if key not in ('started_at', 'rights')} == report
        assert result['rights'] is None
        assert '_id' not in result
        assert result['started_at']

    def test_the_rights_report_alone_is_answered_under_rights(self, rest_api, db: Any) -> None:
        """No type ACL translated, groups given rights: no 404, only the rights key"""
        rights: dict[str, Any] = {'groups': [{'group_id': VIEW_GROUP_ID, 'granted': ['base.access.view']}]}
        db[MIGRATION_REPORT_COLLECTION].insert_one({'_id': ACCESS_RIGHTS_MIGRATION_REPORT_ID, **rights})

        response = rest_api.get(MIGRATION_REPORT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'] == {'rights': rights}

    def test_both_reports_in_one_answer(self, rest_api, db: Any) -> None:
        """The type ACL report's keys beside rights"""
        rights: dict[str, Any] = {'groups': [{'group_id': VIEW_GROUP_ID, 'granted': ['base.access.view']}]}
        db[MIGRATION_REPORT_COLLECTION].insert_many([
            {'_id': TYPE_ACL_MIGRATION_REPORT_ID, 'status': 'complete', 'types': []},
            {'_id': ACCESS_RIGHTS_MIGRATION_REPORT_ID, **rights},
        ])

        response = rest_api.get(MIGRATION_REPORT_URL)

        assert response.get_json()['result'] == {'status': 'complete', 'types': [], 'rights': rights}


class TestReferenceRules:
    """What keeps a document from being deleted, and what goes with a group or a Type."""

    def test_a_granted_class_stays_and_its_usage_names_the_role(self, rest_api) -> None:
        """400 naming the role; free again once the role no longer grants it"""
        class_id: int = _created(rest_api, CLASSES_URL, CLASS)['public_id']
        role: dict[str, Any] = _created(rest_api, ROLES_URL, {**ROLE, 'field_classes': [CLASS['name']]})

        usage = rest_api.get(f'{CLASSES_URL}/{class_id}/usage')
        assert usage.get_json()['result'] == {'scope_roles': [role]}

        refused = rest_api.delete(f'{CLASSES_URL}/{class_id}')
        assert (refused.status_code, _message(refused)) == (HTTPStatus.BAD_REQUEST, AccessRuleMessage.FIELD_CLASS_IN_USE
                                                            .value.format(name=CLASS['name'],
                                                                          role_ids=[role['public_id']]))

        rest_api.put(f"{ROLES_URL}/{role['public_id']}", json={'field_classes': []})
        assert rest_api.get(f'{CLASSES_URL}/{class_id}/usage').get_json()['result'] == {'scope_roles': []}
        assert rest_api.delete(f'{CLASSES_URL}/{class_id}').status_code == HTTPStatus.ACCEPTED

    def test_an_assigned_role_stays_and_its_usage_names_the_assignment(self, rest_api) -> None:
        """400 naming the assignment; free again once it is deleted"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        assignment: dict[str, Any] = _created(rest_api, ASSIGNMENTS_URL, {'group_id': NO_RIGHTS_GROUP_ID,
                                                                          'role_id': role_id, 'scope': '*'})

        assert rest_api.get(f'{ROLES_URL}/{role_id}/usage').get_json()['result'] == {'assignments': [assignment]}
        refused = rest_api.delete(f'{ROLES_URL}/{role_id}')
        assert (refused.status_code, _message(refused)) == (HTTPStatus.BAD_REQUEST, AccessRuleMessage.SCOPE_ROLE_IN_USE
                                                            .value.format(role_id=role_id,
                                                                          assignment_ids=[assignment['public_id']]))

        rest_api.delete(f"{ASSIGNMENTS_URL}/{assignment['public_id']}", query_string=UNRESTRICT)
        assert rest_api.delete(f'{ROLES_URL}/{role_id}').status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize('url', [CLASSES_URL, ROLES_URL])
    def test_the_usage_of_a_missing_document_is_a_404(self, rest_api, url: str) -> None:
        """Nothing to tell"""
        assert rest_api.get(f'{url}/{MISSING_ID}/usage').status_code == HTTPStatus.NOT_FOUND

    def test_a_deleted_group_takes_its_assignments(self, rest_api, db: Any) -> None:
        """Counted in the answer; another group's assignment stays"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        _created(rest_api, ASSIGNMENTS_URL, {'group_id': EMPTY_GROUP_ID, 'role_id': role_id, 'scope': '*'})
        kept: int = _created(rest_api, ASSIGNMENTS_URL, {'group_id': NO_RIGHTS_GROUP_ID, 'role_id': role_id,
                                                         'scope': '*'})['public_id']

        response = rest_api.delete(f'/groups/{EMPTY_GROUP_ID}')

        assert (response.status_code, response.get_json()['assignments_deleted']) == (HTTPStatus.ACCEPTED, 1)
        assert [item['public_id'] for item in db[CmdbAccessAssignment.COLLECTION].find()] == [kept]

    def test_a_group_without_assignments_answers_none_deleted(self, rest_api) -> None:
        """The count is there and 0"""
        response = rest_api.delete(f'/groups/{EMPTY_GROUP_ID}')

        assert (response.status_code, response.get_json()['assignments_deleted']) == (HTTPStatus.ACCEPTED, 0)

    def test_a_deleted_type_leaves_every_role(self, rest_api) -> None:
        """The listing role keeps its other Types - here none; the every-Type role is untouched"""
        listing: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        every: int = _created(rest_api, ROLES_URL, {**ROLE, 'name': 'Every', 'types': '*'})['public_id']

        assert rest_api.delete(f'/types/{TYPE_ID}').status_code == HTTPStatus.ACCEPTED

        assert rest_api.get(f'{ROLES_URL}/{listing}').get_json()['result']['types'] == []
        assert rest_api.get(f'{ROLES_URL}/{every}').get_json()['result']['types'] == '*'


class TestStaleReferences:
    """An update judges only the references it sends."""

    def test_a_role_with_a_gone_type_still_takes_other_changes(self, rest_api, db: Any) -> None:
        """A Type id left behind (a failed clean-up) blocks only a body sending it again"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        db[CmdbScopeRole.COLLECTION].update_one({'public_id': role_id}, {'$push': {'types': MISSING_ID}})

        assert rest_api.put(f'{ROLES_URL}/{role_id}', json={'description': 'still editable'}).status_code == \
            HTTPStatus.ACCEPTED
        resent = rest_api.put(f'{ROLES_URL}/{role_id}', json={'types': [TYPE_ID, MISSING_ID]})
        assert (resent.status_code, AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[MISSING_ID]) in
                _message(resent)) == (HTTPStatus.BAD_REQUEST, True)
        assert rest_api.put(f'{ROLES_URL}/{role_id}', json={'types': [TYPE_ID]}).status_code == HTTPStatus.ACCEPTED


class TestGroupUsageAndUndo:
    """The group's usage lists its assignments; a failed group delete puts them back."""

    def test_the_group_usage_names_its_assignments(self, rest_api) -> None:
        """Ascending; they never block the delete"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        first: int = _created(rest_api, ASSIGNMENTS_URL, {'group_id': EMPTY_GROUP_ID, 'role_id': role_id,
                                                          'scope': '*'})['public_id']

        usage: dict[str, Any] = rest_api.get(f'/groups/{EMPTY_GROUP_ID}/usage').get_json()['result']

        assert (usage['assignment_ids'], usage['blocks_delete']) == ([first], False)

    def test_a_failed_group_delete_restores_its_assignments(self, rest_api, db: Any,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """The assignments went before the group would not: 500, and they are back exactly"""
        role_id: int = _created(rest_api, ROLES_URL, ROLE)['public_id']
        _created(rest_api, ASSIGNMENTS_URL, {'group_id': EMPTY_GROUP_ID, 'role_id': role_id, 'scope': '*'})
        before: list[dict[str, Any]] = list(db[CmdbAccessAssignment.COLLECTION].find())

        def _down(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError('down')

        monkeypatch.setattr(GroupsManager, 'delete_group', _down)

        assert rest_api.delete(f'/groups/{EMPTY_GROUP_ID}',
                               query_string=UNRESTRICT).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert list(db[CmdbAccessAssignment.COLLECTION].find()) == before
