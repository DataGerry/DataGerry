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
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for the CmdbUserGroup usage census (group_usage_helper)

Stub managers answer the member counts and the auth section, and a ``GroupDeleteEffect`` stands for the access
rules, so each part of the census - members, the LDAP settings, the assignments and the Types their removal locks or
opens - its refusal message and its answer shape are tested without a database
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.users_manager import UsersManager
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import GroupDeleteEffect
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.group_usage_helper import (
    GroupUsage,
    abort_if_group_in_use,
    add_access_usage,
    read_group_usage,
)
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_IN_USE_MSG,
    GROUP_USE_LDAP_DEFAULT,
    GROUP_USE_LDAP_MAPPING,
    GROUP_USE_SEPARATOR,
    GroupUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

GROUP: int = 5
OTHER_GROUP: int = 7
MEMBERS: int = 3
SOLE_MEMBERS: int = 1
LOCKED_TYPE: int = 21
OPENED_TYPE: int = 22
FIRST_ASSIGNMENT: int = 31
SECOND_ASSIGNMENT: int = 32
GROUP_DN: str = 'cn=admins,dc=example,dc=com'
OTHER_DN: str = 'cn=staff,dc=example,dc=com'


def _auth(default_group: Any, mapping: list[tuple[str, Any]] | None = None) -> dict[str, Any]:
    """A stored auth section with one LDAP entry."""
    rows = [{'group_dn': dn, 'group_id': group_id} for dn, group_id in mapping or []]

    return {'providers': [{'class_name': 'LdapAuthenticationProvider',
                           'config': {'default_group': default_group, 'groups': {'mapping': rows}}}]}


def _managers(auth: Any = None) -> tuple[MagicMock, MagicMock]:
    """Stub users and settings managers."""
    users, settings = MagicMock(), MagicMock()
    users.sole_member_criteria = UsersManager.sole_member_criteria
    users.count_documents.side_effect = lambda criteria: SOLE_MEMBERS if criteria == {'group_ids': [GROUP]} else MEMBERS
    settings.get_all_values_from_section.return_value = auth or {}

    return users, settings


def _with_effect(locked: list[int], opened: list[int],
                 assignment_ids: list[int] | None = None) -> GroupUsage:
    """An unused group's census with the given access effect added."""
    usage = read_group_usage(GROUP, _managers())
    add_access_usage(usage, GroupDeleteEffect(assignment_ids or [], locked, opened))

    return usage


class TestReadGroupUsage:
    """read_group_usage"""

    def test_an_unused_group(self) -> None:
        """Members only - nothing blocks, the access part empty"""
        usage = read_group_usage(GROUP, _managers())

        assert usage.to_json() == {
            GroupUsageKey.MEMBERS.value: MEMBERS, GroupUsageKey.SOLE_MEMBERS.value: SOLE_MEMBERS,
            GroupUsageKey.LDAP_DEFAULT_GROUP.value: False, GroupUsageKey.LDAP_GROUP_MAPPINGS.value: [],
            GroupUsageKey.LOCKED_TYPE_IDS.value: [], GroupUsageKey.OPENED_TYPE_IDS.value: [],
            GroupUsageKey.ASSIGNMENT_IDS.value: [], GroupUsageKey.BLOCKS_DELETE.value: False,
        }

    def test_the_members_and_the_sole_members_are_counted(self) -> None:
        """Two counts: every member, and those whose only group it is"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        assert [call.args[0] for call in managers[0].count_documents.call_args_list] == [
            {'group_ids': GROUP}, {'group_ids': [GROUP]},
        ]

    def test_the_ldap_default_group(self) -> None:
        """Blocks"""
        usage = read_group_usage(GROUP, _managers(auth=_auth(GROUP)))

        assert usage.ldap_default_group and usage.blocks_delete

    def test_the_ldap_mapping_rows_naming_it(self) -> None:
        """Only the rows of this group; a digit string counts"""
        auth = _auth(OTHER_GROUP, [(GROUP_DN, GROUP), (OTHER_DN, OTHER_GROUP), ('cn=x', str(GROUP))])

        usage = read_group_usage(GROUP, _managers(auth=auth))

        assert usage.ldap_group_mappings == [GROUP_DN, 'cn=x']
        assert not usage.ldap_default_group and usage.blocks_delete

    def test_a_missing_auth_section_reads_as_empty(self) -> None:
        """The section is read with an empty default"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        managers[1].get_all_values_from_section.assert_called_once_with('auth', default={})


class TestAddAccessUsage:
    """add_access_usage and what it means for blocks_delete"""

    def test_the_effect_joins_the_census_under_its_own_keys(self) -> None:
        """Assignments, locked and opened each in their key - distinct values, no swap"""
        answer = _with_effect([LOCKED_TYPE], [OPENED_TYPE], [FIRST_ASSIGNMENT, SECOND_ASSIGNMENT]).to_json()

        assert (answer[GroupUsageKey.ASSIGNMENT_IDS.value], answer[GroupUsageKey.LOCKED_TYPE_IDS.value],
                answer[GroupUsageKey.OPENED_TYPE_IDS.value]) == (
            [FIRST_ASSIGNMENT, SECOND_ASSIGNMENT], [LOCKED_TYPE], [OPENED_TYPE])

    def test_a_locked_type_blocks(self) -> None:
        """Refused whatever is confirmed"""
        assert _with_effect([LOCKED_TYPE], []).blocks_delete

    def test_an_opened_type_does_not_block(self) -> None:
        """unrestrict=true lets the delete pass"""
        assert not _with_effect([], [OPENED_TYPE], [FIRST_ASSIGNMENT]).blocks_delete

    def test_the_census_keeps_its_own_lists(self) -> None:
        """A later change of the effect's lists does not reach the census"""
        effect = GroupDeleteEffect([FIRST_ASSIGNMENT], [LOCKED_TYPE], [OPENED_TYPE])
        usage = read_group_usage(GROUP, _managers())
        add_access_usage(usage, effect)

        effect.assignment_ids.append(SECOND_ASSIGNMENT)
        effect.locked.clear()
        effect.opened.clear()

        assert (usage.assignment_ids, usage.locked_type_ids, usage.opened_type_ids) == (
            [FIRST_ASSIGNMENT], [LOCKED_TYPE], [OPENED_TYPE])


class TestRefusal:
    """GroupUsage.holders and abort_if_group_in_use"""

    def test_every_ldap_holder_is_named_in_order(self) -> None:
        """Default, then mappings"""
        usage = GroupUsage(ldap_default_group=True, ldap_group_mappings=[GROUP_DN])

        with pytest.raises(HTTPException) as exc_info:
            abort_if_group_in_use(usage, GROUP)

        holders = GROUP_USE_SEPARATOR.join([GROUP_USE_LDAP_DEFAULT,
                                           GROUP_USE_LDAP_MAPPING.format(group_dns=[GROUP_DN])])
        assert exc_info.value.code == 400
        assert exc_info.value.description == GROUP_IN_USE_MSG.format(public_id=GROUP, holders=holders)

    def test_members_assignments_and_types_do_not_refuse_here(self) -> None:
        """Members are the action's; locked / opened Types the access guard's, with its own messages"""
        abort_if_group_in_use(GroupUsage(members=MEMBERS, assignment_ids=[FIRST_ASSIGNMENT],
                                         locked_type_ids=[LOCKED_TYPE], opened_type_ids=[OPENED_TYPE]), GROUP)

    def test_the_holders_name_no_type(self) -> None:
        """A locked Type is no LDAP holder"""
        assert not GroupUsage(locked_type_ids=[LOCKED_TYPE]).holders()
