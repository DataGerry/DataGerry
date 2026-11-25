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
Unit tests for cmdb.framework.access_engine.type_acl_translation

Only activated ACLs (activated true, nothing else) are translated. Groups holding the same operations on the same
Types share one role; another Type set or operation set is another role, a repeated name gets a number. A gone
group, an empty or unreadable permission list grants nothing; a Type granting no existing group anything stays
restricted through one role without operations for the administrator group. The documents are numbered in order and
the translated roles decide as the ACL: READ view, UPDATE edit. Distinct ids, so a swapped key fails a test
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    TRANSLATED_DESCRIPTION,
    TranslatedRole,
    acl_is_activated,
    assignment_documents,
    build_grants,
    granted_operations,
    role_documents,
    translate_type_acls,
)
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
SWITCH_TYPE_ID: int = 13
FREE_TYPE_ID: int = 14
ADMIN_GROUP_ID: int = 25
OPERATORS_GROUP_ID: int = 21
AUDITORS_GROUP_ID: int = 22
GONE_GROUP_ID: int = 29
EXISTING_GROUP_IDS: list[int] = [ADMIN_GROUP_ID, OPERATORS_GROUP_ID, AUDITORS_GROUP_ID]
VIEW = ScopeOperation.VIEW
CREATE = ScopeOperation.CREATE
EDIT = ScopeOperation.EDIT
DELETE = ScopeOperation.DELETE


def _type(public_id: Any, includes: dict[int | str, Any] | None = None, activated: Any = True) -> dict[str, Any]:
    """A stored Type with an ACL"""
    groups: dict[str, Any] = {str(group_id): values for group_id, values in (includes or {}).items()}

    acl: dict[str, Any] = {'activated': activated, 'groups': {'includes': groups}}

    return {'public_id': public_id, 'name': f'type-{public_id}', 'acl': acl}


def _translate(*types: dict[str, Any]) -> tuple[TranslatedRole, ...]:
    """The translation with the three existing groups"""
    return translate_type_acls(types, EXISTING_GROUP_IDS, ADMIN_GROUP_ID)


def _name(operations: str, count: int, suffix: str = '') -> str:
    """A translated role's name"""
    return f"{operations} on {count} {'Type' if count == 1 else 'Types'} (translated from the type ACL){suffix}"


class TestActivated:
    """acl_is_activated"""

    @pytest.mark.parametrize('document, expected', [
        (_type(SERVER_TYPE_ID), True),
        (_type(SERVER_TYPE_ID, activated=False), False),
        (_type(SERVER_TYPE_ID, activated='true'), False),
        (_type(SERVER_TYPE_ID, activated=1), False),
        ({'public_id': SERVER_TYPE_ID, 'acl': {'groups': {}}}, False),
        ({'public_id': SERVER_TYPE_ID}, False),
        ({'public_id': SERVER_TYPE_ID, 'acl': None}, False),
    ], ids=['true', 'false', 'string', 'one', 'no-key', 'no-acl', 'null-acl'])
    def test_only_true_switches_it_on(self, document: dict[str, Any], expected: bool) -> None:
        """The reading every ACL check has"""
        assert acl_is_activated(document) is expected


def test_granted_operations() -> None:
    """Each value its operation; an unknown value grants nothing"""
    assert granted_operations(['READ', 'UPDATE', 'CREATE', 'DELETE']) == frozenset({VIEW, EDIT, CREATE, DELETE})
    assert granted_operations(['READ_ALL', 'read']) == frozenset()


class TestTranslation:
    """translate_type_acls"""

    def test_an_absent_or_deactivated_acl_is_not_translated(self) -> None:
        """Nothing restricts those Types"""
        assert not _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}, activated=False),
                              {'public_id': FREE_TYPE_ID, 'name': 'free'})

    def test_one_group_one_role(self) -> None:
        """READ + UPDATE read as view + edit"""
        assert _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['UPDATE', 'READ']})) == (
            TranslatedRole(_name('view, edit', 1), (SERVER_TYPE_ID,), (VIEW, EDIT), (OPERATORS_GROUP_ID,)),)

    def test_groups_holding_the_same_row_share_a_role(self) -> None:
        """Both view servers and routers"""
        roles = _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ'], AUDITORS_GROUP_ID: ['READ']}),
                           _type(ROUTER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ'], AUDITORS_GROUP_ID: ['READ']}))

        assert roles == (TranslatedRole(_name('view', 2), (SERVER_TYPE_ID, ROUTER_TYPE_ID), (VIEW,),
                                        (OPERATORS_GROUP_ID, AUDITORS_GROUP_ID)),)

    def test_another_type_set_is_another_role_with_a_numbered_name(self) -> None:
        """Operators view servers, auditors routers - same operations, same count, different Types"""
        roles = _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}),
                           _type(ROUTER_TYPE_ID, {AUDITORS_GROUP_ID: ['READ']}))

        assert roles == (
            TranslatedRole(_name('view', 1), (SERVER_TYPE_ID,), (VIEW,), (OPERATORS_GROUP_ID,)),
            TranslatedRole(_name('view', 1, ' #2'), (ROUTER_TYPE_ID,), (VIEW,), (AUDITORS_GROUP_ID,)),
        )

    def test_roles_are_ordered_by_operations_then_types(self) -> None:
        """Delete-only after view-only, although its Type id is the lower one"""
        roles = _translate(_type(SERVER_TYPE_ID, {AUDITORS_GROUP_ID: ['DELETE']}),
                           _type(ROUTER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}))

        assert [role.operations for role in roles] == [(VIEW,), (DELETE,)]

    def test_a_gone_group_is_dropped(self) -> None:
        """E7 - the operators keep their role"""
        roles = _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ'], GONE_GROUP_ID: ['READ', 'UPDATE']}))

        assert [role.group_ids for role in roles] == [(OPERATORS_GROUP_ID,)]

    @pytest.mark.parametrize('includes', [{}, {GONE_GROUP_ID: ['READ']}, {OPERATORS_GROUP_ID: []},
                                          {OPERATORS_GROUP_ID: ['READ_ALL']}, {'admin': ['READ']}],
                             ids=['nobody', 'gone-group', 'empty-list', 'unknown-value', 'no-group-key'])
    def test_a_type_granting_nobody_stays_restricted_for_the_admin_group(self, includes: dict[Any, Any]) -> None:
        """A15: no operations, assigned to the administrators"""
        assert _translate(_type(SERVER_TYPE_ID, includes)) == (
            TranslatedRole(_name('No access', 1), (SERVER_TYPE_ID,), (), (ADMIN_GROUP_ID,)),)

    def test_every_type_granting_nobody_shares_one_role(self) -> None:
        """Ordered first - no operations"""
        roles = _translate(_type(ROUTER_TYPE_ID), _type(SERVER_TYPE_ID), _type(SWITCH_TYPE_ID,
                                                                               {OPERATORS_GROUP_ID: ['READ']}))

        assert roles[0] == TranslatedRole(_name('No access', 2), (SERVER_TYPE_ID, ROUTER_TYPE_ID), (),
                                          (ADMIN_GROUP_ID,))

    @pytest.mark.parametrize('public_id', ['11', True, None], ids=['string', 'bool', 'none'])
    def test_a_type_without_an_integer_id_is_passed_over(self, public_id: Any) -> None:
        """Nothing to name"""
        assert not _translate(_type(public_id, {OPERATORS_GROUP_ID: ['READ']}))


class TestTakenNames:
    """translate_type_acls(taken_names=...) - a name an administrator already stored is never taken"""

    @staticmethod
    def _names(*taken: str) -> list[str]:
        """The names of two view roles on one Type each, against the taken names"""
        roles = translate_type_acls([_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}),
                                     _type(ROUTER_TYPE_ID, {AUDITORS_GROUP_ID: ['READ']})],
                                    EXISTING_GROUP_IDS, ADMIN_GROUP_ID, taken)

        return [role.name for role in roles]

    def test_nothing_taken_numbers_from_the_second(self) -> None:
        """The default"""
        assert self._names() == [_name('view', 1), _name('view', 1, ' #2')]

    def test_a_taken_base_name_numbers_on(self) -> None:
        """The first role takes #2, the second #3"""
        assert self._names(_name('view', 1)) == [_name('view', 1, ' #2'), _name('view', 1, ' #3')]

    def test_every_taken_number_is_skipped(self) -> None:
        """A gap is filled in order, never a taken one"""
        assert self._names(_name('view', 1), _name('view', 1, ' #3')) == [
            _name('view', 1, ' #2'), _name('view', 1, ' #4')]

    def test_another_base_is_not_touched(self) -> None:
        """A taken name of other operations changes nothing here"""
        assert self._names(_name('edit', 1)) == [_name('view', 1), _name('view', 1, ' #2')]


class TestDocuments:
    """role_documents + assignment_documents"""

    ROLES: tuple[TranslatedRole, ...] = (
        TranslatedRole('first', (SERVER_TYPE_ID,), (VIEW, EDIT), (OPERATORS_GROUP_ID, AUDITORS_GROUP_ID)),
        TranslatedRole('second', (ROUTER_TYPE_ID, SWITCH_TYPE_ID), (), (ADMIN_GROUP_ID,)),
    )

    def test_the_role_documents(self) -> None:
        """Numbered in order; regular fields written, no class"""
        assert role_documents(self.ROLES, 71) == [
            {'public_id': 71, 'name': 'first', 'description': TRANSLATED_DESCRIPTION, 'types': [SERVER_TYPE_ID],
             'operations': ['view', 'edit'], 'write_regular_fields': True, 'field_classes': []},
            {'public_id': 72, 'name': 'second', 'description': TRANSLATED_DESCRIPTION,
             'types': [ROUTER_TYPE_ID, SWITCH_TYPE_ID], 'operations': [], 'write_regular_fields': True,
             'field_classes': []},
        ]

    def test_the_assignment_documents(self) -> None:
        """Each role to each of its groups, unconditional"""
        assert assignment_documents(self.ROLES, 71, 81) == [
            {'public_id': 81, 'group_id': OPERATORS_GROUP_ID, 'role_id': 71, 'scope': '*',
             'description': TRANSLATED_DESCRIPTION},
            {'public_id': 82, 'group_id': AUDITORS_GROUP_ID, 'role_id': 71, 'scope': '*',
             'description': TRANSLATED_DESCRIPTION},
            {'public_id': 83, 'group_id': ADMIN_GROUP_ID, 'role_id': 72, 'scope': '*',
             'description': TRANSLATED_DESCRIPTION},
        ]


def test_the_translated_roles_decide_as_the_acl() -> None:
    """Operators view + edit servers, auditors view routers; switches grant nobody; the free Type is open"""
    roles = _translate(_type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ', 'UPDATE']}),
                       _type(ROUTER_TYPE_ID, {AUDITORS_GROUP_ID: ['READ']}),
                       _type(SWITCH_TYPE_ID, {GONE_GROUP_ID: ['READ']}))
    stored_roles: list[dict[str, Any]] = role_documents(roles, 1)
    assignments: list[dict[str, Any]] = assignment_documents(roles, 1, 1)
    operators = build_grants(assignments, stored_roles, [OPERATORS_GROUP_ID])
    admins = build_grants(assignments, stored_roles, [ADMIN_GROUP_ID])

    assert operators.allows(EDIT, SERVER_TYPE_ID) and not operators.allows(DELETE, SERVER_TYPE_ID)
    assert not operators.allows(VIEW, ROUTER_TYPE_ID)
    assert not admins.allows(VIEW, SWITCH_TYPE_ID) and not admins.allows(VIEW, SERVER_TYPE_ID)
    assert admins.allows(DELETE, FREE_TYPE_ID)
