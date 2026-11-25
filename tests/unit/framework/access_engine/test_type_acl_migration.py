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
Unit tests for cmdb.framework.access_engine.type_acl_migration - the migration's self-check and its report

The self-check must find nothing on a faithful translation (also over generated scenarios) and name exactly the Type
where a tampered translation, or an ACL the translation reads otherwise, decides differently
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    acl_allows,
    acl_differences,
    assignment_documents,
    inactive_type_ids,
    pending_report,
    role_documents,
    translate_type_acls,
    type_entries,
    type_id_of,
)
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_acl_scenarios import EXISTING_GROUP_IDS as SCENARIO_GROUP_IDS, scenario
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
LOCKED_TYPE_ID: int = 14
ADMIN_GROUP_ID: int = 1
OPERATORS_GROUP_ID: int = 21
AUDITORS_GROUP_ID: int = 22
GONE_GROUP_ID: int = 29
EXISTING_GROUP_IDS: list[int] = [ADMIN_GROUP_ID, OPERATORS_GROUP_ID, AUDITORS_GROUP_ID]
FIRST_ROLE_ID: int = 101
FIRST_ASSIGNMENT_ID: int = 201
SCENARIO_TYPE_IDS: list[int] = [9901, 9902, 9903, 9904, 9905]
SCENARIO_COUNT: int = 40
STARTED_AT: datetime = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


def _type(public_id: Any, includes: dict[int, list[str]] | None = None, activated: Any = True) -> dict[str, Any]:
    """A stored Type with an ACL"""
    return {'public_id': public_id,
            'acl': {'activated': activated,
                    'groups': {'includes': {str(group): values for group, values in (includes or {}).items()}}}}


TYPES: list[dict[str, Any]] = [
    _type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ', 'UPDATE'], GONE_GROUP_ID: ['READ']}),
    _type(ROUTER_TYPE_ID, {AUDITORS_GROUP_ID: ['READ']}),
    _type(FREE_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}, activated=False),
    _type(LOCKED_TYPE_ID, {GONE_GROUP_ID: ['READ']}),
]


def _documents(types: list[dict[str, Any]], group_ids: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The translation numbered: (roles, assignments)"""
    roles = translate_type_acls(types, group_ids, ADMIN_GROUP_ID)

    return (role_documents(roles, FIRST_ROLE_ID),
            assignment_documents(roles, FIRST_ROLE_ID, FIRST_ASSIGNMENT_ID))


def _role_of(roles: list[dict[str, Any]], type_id: int) -> dict[str, Any]:
    """The one role naming the Type"""
    return next(role for role in roles if type_id in role['types'])


class TestTypeIdOf:
    """type_id_of"""

    @pytest.mark.parametrize('public_id, expected', [(7, 7), (True, None), ('7', None), (None, None)],
                             ids=['int', 'bool', 'string', 'none'])
    def test_only_an_int(self, public_id: Any, expected: int | None) -> None:
        """A bool is no id"""
        assert type_id_of({'public_id': public_id}) == expected


class TestAclAllows:
    """acl_allows - the stored ACL's frozen reading"""

    def test_an_activated_acl_grants_its_groups(self) -> None:
        """READ granted, DELETE not; no groups nothing"""
        assert acl_allows(TYPES[0], [OPERATORS_GROUP_ID], AccessControlPermission.READ)
        assert not acl_allows(TYPES[0], [OPERATORS_GROUP_ID], AccessControlPermission.DELETE)
        assert not acl_allows(TYPES[0], [], AccessControlPermission.READ)

    @pytest.mark.parametrize('acl', [None, 'garbage', {'activated': False}], ids=['none', 'not-a-dict', 'off'])
    def test_no_activated_acl_grants_everyone(self, acl: Any) -> None:
        """Opt-in"""
        assert acl_allows({'public_id': SERVER_TYPE_ID, 'acl': acl}, [], AccessControlPermission.DELETE)


class TestAclDifferences:
    """acl_differences"""

    def test_a_faithful_translation_differs_nowhere(self) -> None:
        """The gone group dropped, the locked Type kept restricted"""
        assert acl_differences(TYPES, EXISTING_GROUP_IDS, *_documents(TYPES, EXISTING_GROUP_IDS)) == []

    @pytest.mark.parametrize('number', range(SCENARIO_COUNT))
    def test_generated_scenarios_differ_nowhere(self, number: int) -> None:
        """Every shape the equivalence tests generate"""
        types = scenario(number, SCENARIO_TYPE_IDS)

        assert acl_differences(types, SCENARIO_GROUP_IDS, *_documents(types, SCENARIO_GROUP_IDS)) == []

    def test_a_missing_operation_is_named(self) -> None:
        """The server role loses edit - only that Type differs"""
        roles, assignments = _documents(TYPES, EXISTING_GROUP_IDS)
        _role_of(roles, SERVER_TYPE_ID)['operations'] = ['view']

        assert acl_differences(TYPES, EXISTING_GROUP_IDS, roles, assignments) == [SERVER_TYPE_ID]

    def test_a_missing_assignment_is_named(self) -> None:
        """The auditors lose their router role - the Type stays restricted, nobody views it"""
        roles, assignments = _documents(TYPES, EXISTING_GROUP_IDS)
        router_role: int = _role_of(roles, ROUTER_TYPE_ID)['public_id']
        kept = [assignment for assignment in assignments if assignment['role_id'] != router_role]

        assert acl_differences(TYPES, EXISTING_GROUP_IDS, roles, kept) == [ROUTER_TYPE_ID]

    def test_an_acl_the_translation_reads_otherwise_is_named(self) -> None:
        """activated: 1 - on for the ACL, off for the translation"""
        types = [*TYPES, _type(99, {OPERATORS_GROUP_ID: ['READ']}, activated=1)]

        assert acl_differences(types, EXISTING_GROUP_IDS, *_documents(types, EXISTING_GROUP_IDS)) == [99]

    def test_a_type_without_an_int_id_is_passed_over(self) -> None:
        """It cannot be decided by id"""
        types = [*TYPES, _type('x', {OPERATORS_GROUP_ID: ['READ']}, activated=1)]

        assert acl_differences(types, EXISTING_GROUP_IDS, *_documents(types, EXISTING_GROUP_IDS)) == []

    def test_without_groups_a_missing_restriction_is_named(self) -> None:
        """No group to ask - the user in no group still sees the activated ACLs left open"""
        assert acl_differences(TYPES, [], [], []) == [SERVER_TYPE_ID, ROUTER_TYPE_ID, LOCKED_TYPE_ID]

    def test_no_groups_judges_the_groupless_user_only(self) -> None:
        """A staging database: every activated ACL grants nobody, so does the translation"""
        assert acl_differences(TYPES, [], *_documents(TYPES, [])) == []


class TestReport:
    """type_entries, inactive_type_ids, pending_report"""

    def test_one_entry_per_activated_type_with_its_roles_and_dropped_groups(self) -> None:
        """Distinct ids per key - no swap"""
        roles, assignments = _documents(TYPES, EXISTING_GROUP_IDS)
        entries = {entry['type_id']: entry for entry in type_entries(TYPES, EXISTING_GROUP_IDS, roles, assignments)}
        server_role: dict[str, Any] = _role_of(roles, SERVER_TYPE_ID)
        locked_role: dict[str, Any] = _role_of(roles, LOCKED_TYPE_ID)

        assert sorted(entries) == [SERVER_TYPE_ID, ROUTER_TYPE_ID, LOCKED_TYPE_ID]
        assert entries[SERVER_TYPE_ID] == {
            'type_id': SERVER_TYPE_ID, 'acl': TYPES[0]['acl'], 'role_ids': [server_role['public_id']],
            'assignment_ids': [assignment['public_id'] for assignment in assignments
                               if assignment['role_id'] == server_role['public_id']],
            'dropped_group_ids': [GONE_GROUP_ID],
        }
        assert entries[LOCKED_TYPE_ID]['role_ids'] == [locked_role['public_id']]
        assert locked_role['operations'] == []
        assert entries[ROUTER_TYPE_ID]['dropped_group_ids'] == []

    def test_the_inactive_types(self) -> None:
        """Absent or off - ascending"""
        types = [*TYPES, {'public_id': 5}]

        assert inactive_type_ids(types) == [5, FREE_TYPE_ID]

    def test_the_pending_report(self) -> None:
        """Pending, the planned documents in it"""
        roles, assignments = _documents(TYPES, EXISTING_GROUP_IDS)

        report = pending_report(TYPES, EXISTING_GROUP_IDS, (roles, assignments), STARTED_AT)

        assert (report['status'], report['started_at'], report['existing_group_ids'], report['inactive_type_ids'],
                report['roles'], report['assignments']) == (
            'pending', STARTED_AT, sorted(EXISTING_GROUP_IDS), [FREE_TYPE_ID], roles, assignments)
        assert len(report['types']) == 3 and 'completed_at' not in report
