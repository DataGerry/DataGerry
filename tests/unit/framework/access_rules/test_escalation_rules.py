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
Unit tests for cmdb.framework.access_rules.escalation_rules

A role reaching one of the caller's own groups may grant only what the caller holds: each operation on each of its
restricted Types (an unrestricted Type is everyone's), every restricted Type for a role on every Type, and writing
fields where it grants create / edit with write_regular_fields. A role for groups the caller is not in is not judged
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import AccessGrants, TypeSet, build_grants
from cmdb.framework.access_rules import (
    AccessRuleMessage,
    ReachPart,
    beyond_reach,
    delegation_problem,
    own_reach_problem,
    types_beyond,
)
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
CALLER_GROUP_ID: int = 21
OTHER_GROUP_ID: int = 22
NEW_ROLE_ID: int = 39

# The caller views and edits servers without writing fields (31); routers are restricted by another group's role (32)
CALLER_GRANTS: AccessGrants = build_grants(
    [{'public_id': 41, 'group_id': CALLER_GROUP_ID, 'role_id': 31, 'scope': '*'}],
    [{'public_id': 31, 'types': [SERVER_TYPE_ID], 'operations': ['view', 'edit'], 'write_regular_fields': False},
     {'public_id': 32, 'types': [ROUTER_TYPE_ID], 'operations': ['view'], 'write_regular_fields': True}],
    [CALLER_GROUP_ID],
)


def _role(types: Any, operations: list[str], write_regular_fields: bool = False) -> dict[str, Any]:
    """A scope role as it would be stored"""
    return {'public_id': NEW_ROLE_ID, 'name': 'new', 'types': types, 'operations': operations,
            'write_regular_fields': write_regular_fields, 'field_classes': []}


class TestTypesBeyond:
    """types_beyond"""

    def test_listed_types(self) -> None:
        """A restricted Type not allowed is beyond; an allowed or unrestricted one is not"""
        lacking = types_beyond(TypeSet.of([SERVER_TYPE_ID]), TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID]),
                               TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID]))

        assert lacking == TypeSet.of([ROUTER_TYPE_ID])

    @pytest.mark.parametrize('allowed, expected', [
        (TypeSet.of([SERVER_TYPE_ID]), TypeSet.everything()),
        (TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID]), TypeSet()),
        (TypeSet.everything(), TypeSet()),
    ], ids=['one-restricted-missing', 'every-restricted-held', 'every-type-held'])
    def test_a_role_on_every_type(self, allowed: TypeSet, expected: TypeSet) -> None:
        """Needs every restricted Type"""
        assert types_beyond(allowed, TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID]), TypeSet.everything()) == expected


class TestBeyondReach:
    """beyond_reach"""

    def test_within_reach(self) -> None:
        """View + edit on servers, anything on the unrestricted Type"""
        assert not beyond_reach(CALLER_GRANTS, _role([SERVER_TYPE_ID, FREE_TYPE_ID], ['view', 'edit']))

    def test_an_operation_beyond(self) -> None:
        """Delete on servers, view on routers - each named, in operation order"""
        assert beyond_reach(CALLER_GRANTS, _role([SERVER_TYPE_ID, ROUTER_TYPE_ID], ['delete', 'view'])) == [
            'view on Types [12]', 'delete on Types [11, 12]']

    def test_writing_fields_beyond(self) -> None:
        """Edit on servers is held, writing fields there is not"""
        assert beyond_reach(CALLER_GRANTS, _role([SERVER_TYPE_ID], ['edit'], write_regular_fields=True)) == [
            'writing fields on Types [11]']

    def test_writing_fields_needs_a_writing_operation(self) -> None:
        """A view-only role writes nothing"""
        assert not beyond_reach(CALLER_GRANTS, _role([SERVER_TYPE_ID], ['view'], write_regular_fields=True))

    def test_a_role_on_every_type(self) -> None:
        """Routers are restricted and not held"""
        assert beyond_reach(CALLER_GRANTS, _role('*', ['view'])) == ['view on every Type']


class TestOwnReachProblem:
    """own_reach_problem"""

    def test_another_groups_role_is_not_judged(self) -> None:
        """Assigning beyond reach to a group the caller is not in"""
        assert own_reach_problem(CALLER_GRANTS, NEW_ROLE_ID, _role('*', ['delete']), [OTHER_GROUP_ID],
                                 [CALLER_GROUP_ID]) is None

    def test_an_own_group_beyond_reach(self) -> None:
        """Every part named"""
        problem = own_reach_problem(CALLER_GRANTS, NEW_ROLE_ID, _role([ROUTER_TYPE_ID], ['view', 'edit']),
                                    [OTHER_GROUP_ID, CALLER_GROUP_ID], [CALLER_GROUP_ID])

        assert problem == AccessRuleMessage.BEYOND_OWN_REACH.value.format(
            role_id=NEW_ROLE_ID, beyond=ReachPart.SEPARATOR.value.join(['view on Types [12]', 'edit on Types [12]']))

    def test_an_own_group_within_reach(self) -> None:
        """No problem"""
        assert own_reach_problem(CALLER_GRANTS, NEW_ROLE_ID, _role([SERVER_TYPE_ID], ['view']), [CALLER_GROUP_ID],
                                 [CALLER_GROUP_ID]) is None


class TestDelegationProblem:
    """delegation_problem - any group, measured against the delegate's grants together"""

    def test_a_role_within_the_delegates_access(self) -> None:
        """No problem"""
        assert delegation_problem(CALLER_GRANTS, NEW_ROLE_ID, _role([SERVER_TYPE_ID], ['view'])) is None

    def test_a_role_beyond_it_names_every_part(self) -> None:
        """Whatever group it is meant for"""
        problem = delegation_problem(CALLER_GRANTS, NEW_ROLE_ID, _role([ROUTER_TYPE_ID], ['view', 'edit']))

        assert problem == AccessRuleMessage.BEYOND_DELEGATION.value.format(
            role_id=NEW_ROLE_ID, beyond=ReachPart.SEPARATOR.value.join(['view on Types [12]', 'edit on Types [12]']))

