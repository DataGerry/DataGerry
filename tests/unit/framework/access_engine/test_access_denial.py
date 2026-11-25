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
Unit tests for cmdb.framework.access_engine.access_denial

A Type is denied an operation when restricted and not granted; with every Type restricted the denial is the
complement of the granted Types, and the filters admit those ($in) instead of excluding ($nin). Several operations
must all be held: the denials join - two lists add up, a complement loses the listed ids, two complements keep what
both admit. An empty operation list is refused
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    NO_OPERATION_MESSAGE,
    AccessGrants,
    DeniedTypes,
    build_grants,
    denied_for,
    denied_types_of,
    no_object_criteria,
    object_criteria,
    operation_list,
    operations_allowed,
    permission_operations,
    type_criteria,
)
from cmdb.models.access_model import ScopeOperation
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
SWITCH_TYPE_ID: int = 13
FREE_TYPE_ID: int = 14
USER_GROUP_ID: int = 21
OTHER_GROUP_ID: int = 23
VIEW = ScopeOperation.VIEW
CREATE = ScopeOperation.CREATE
EDIT = ScopeOperation.EDIT
DELETE = ScopeOperation.DELETE


def _role(public_id: int, types: Any, operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'types': types, 'operations': operations, 'write_regular_fields': True,
            'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': '*'}


def _grants(own: list[tuple[int, Any, list[str]]], others: list[tuple[int, Any, list[str]]]) -> AccessGrants:
    """The user holds the `own` roles, another group the `others` - (role id, types, operations) each"""
    roles: list[dict[str, Any]] = [_role(*role) for role in own + others]
    assignments: list[dict[str, Any]] = [_assignment(40 + role[0], USER_GROUP_ID, role[0]) for role in own]

    return build_grants(assignments, roles, [USER_GROUP_ID])


class TestDeniedTypes:
    """DeniedTypes"""

    def test_listed_ids_deny_only_themselves(self) -> None:
        """A finite denial"""
        denied = DeniedTypes(ids=frozenset({SERVER_TYPE_ID}))

        assert denied.denies(SERVER_TYPE_ID) and not denied.denies(ROUTER_TYPE_ID)
        assert not denied.denies_nothing()

    def test_a_complement_denies_all_but_the_admitted(self) -> None:
        """Also an id no Type carries"""
        denied = DeniedTypes(admitted=frozenset({SERVER_TYPE_ID}))

        assert not denied.denies(SERVER_TYPE_ID) and denied.denies(FREE_TYPE_ID)
        assert not denied.denies_nothing()

    def test_an_empty_complement_denies_everything(self) -> None:
        """Nothing admitted"""
        assert DeniedTypes(admitted=frozenset()).denies(SERVER_TYPE_ID)

    def test_the_empty_denial(self) -> None:
        """Nothing listed, no complement"""
        assert DeniedTypes().denies_nothing()

    @pytest.mark.parametrize('left, right, expected', [
        (DeniedTypes(ids=frozenset({11})), DeniedTypes(ids=frozenset({12})), DeniedTypes(ids=frozenset({11, 12}))),
        (DeniedTypes(admitted=frozenset({11, 12})), DeniedTypes(ids=frozenset({12, 13})),
         DeniedTypes(admitted=frozenset({11}))),
        (DeniedTypes(ids=frozenset({12, 13})), DeniedTypes(admitted=frozenset({11, 12})),
         DeniedTypes(admitted=frozenset({11}))),
        (DeniedTypes(admitted=frozenset({11, 12})), DeniedTypes(admitted=frozenset({12, 13})),
         DeniedTypes(admitted=frozenset({12}))),
    ], ids=['lists', 'complement-list', 'list-complement', 'complements'])
    def test_union(self, left: DeniedTypes, right: DeniedTypes, expected: DeniedTypes) -> None:
        """What either denies"""
        assert left.union(right) == expected


class TestOperationList:
    """operation_list + permission_operations"""

    def test_one_operation(self) -> None:
        """A bare member is a list of one"""
        assert operation_list(EDIT) == [EDIT]

    def test_several_in_order_each_once(self) -> None:
        """Also from a generator"""
        assert operation_list(operation for operation in [DELETE, VIEW, DELETE]) == [DELETE, VIEW]

    def test_no_operation_is_refused(self) -> None:
        """Nothing asked would deny every restricted Type"""
        with pytest.raises(ValueError, match=NO_OPERATION_MESSAGE):
            operation_list([])

    def test_permissions_read_as_operations(self) -> None:
        """One and several; READ is view, UPDATE edit"""
        assert permission_operations(AccessControlPermission.UPDATE) == [EDIT]
        assert permission_operations([AccessControlPermission.READ, AccessControlPermission.CREATE]) == [VIEW, CREATE]

    def test_no_permission_is_refused(self) -> None:
        """Same rule"""
        with pytest.raises(ValueError, match=NO_OPERATION_MESSAGE):
            permission_operations([])


class TestDeniedFor:
    """denied_for + denied_types_of"""

    def test_restricted_and_not_granted(self) -> None:
        """View on servers granted; routers restricted by another group; the free Type is not restricted"""
        grants: AccessGrants = _grants([(31, [SERVER_TYPE_ID], ['view'])], [(32, [ROUTER_TYPE_ID], ['view'])])

        assert denied_for(grants, VIEW) == DeniedTypes(ids=frozenset({ROUTER_TYPE_ID}))
        assert denied_for(grants, EDIT) == DeniedTypes(ids=frozenset({SERVER_TYPE_ID, ROUTER_TYPE_ID}))

    def test_every_type_restricted_is_a_complement(self) -> None:
        """A role on every Type elsewhere: only the granted Type is admitted"""
        grants: AccessGrants = _grants([(31, [SERVER_TYPE_ID], ['view'])], [(32, '*', ['view'])])

        assert denied_for(grants, VIEW) == DeniedTypes(admitted=frozenset({SERVER_TYPE_ID}))

    def test_granted_on_every_type_denies_nothing(self) -> None:
        """Whatever is restricted"""
        grants: AccessGrants = _grants([(31, '*', ['view'])], [(32, [ROUTER_TYPE_ID], ['edit'])])

        assert denied_for(grants, VIEW).denies_nothing()

    def test_several_operations_must_all_be_held(self) -> None:
        """View on servers, edit on routers: asking both denies both"""
        grants: AccessGrants = _grants([(31, [SERVER_TYPE_ID], ['view']), (32, [ROUTER_TYPE_ID], ['edit'])], [])

        assert denied_types_of(grants, [VIEW, EDIT]) == DeniedTypes(ids=frozenset({SERVER_TYPE_ID,
                                                                                   ROUTER_TYPE_ID}))
        assert denied_types_of(grants, VIEW) == DeniedTypes(ids=frozenset({ROUTER_TYPE_ID}))


class TestCriteria:
    """object_criteria, type_criteria, no_object_criteria"""

    def test_listed_ids_are_excluded_ascending(self) -> None:
        """$nin on each collection's own key"""
        denied = DeniedTypes(ids=frozenset({ROUTER_TYPE_ID, SERVER_TYPE_ID}))

        assert object_criteria(denied) == {'type_id': {'$nin': [SERVER_TYPE_ID, ROUTER_TYPE_ID]}}
        assert type_criteria(denied) == {'public_id': {'$nin': [SERVER_TYPE_ID, ROUTER_TYPE_ID]}}

    def test_a_complement_admits_ascending(self) -> None:
        """$in - an object of a gone Type is out (E5)"""
        denied = DeniedTypes(admitted=frozenset({SWITCH_TYPE_ID, SERVER_TYPE_ID}))

        assert object_criteria(denied) == {'type_id': {'$in': [SERVER_TYPE_ID, SWITCH_TYPE_ID]}}
        assert type_criteria(denied) == {'public_id': {'$in': [SERVER_TYPE_ID, SWITCH_TYPE_ID]}}

    def test_nothing_denied_filters_nothing(self) -> None:
        """No stage at all"""
        assert not object_criteria(DeniedTypes())
        assert not type_criteria(DeniedTypes())

    def test_no_object_criteria(self) -> None:
        """An empty $in"""
        assert no_object_criteria() == {'type_id': {'$in': []}}


def test_operations_allowed() -> None:
    """Per Type, in enum order; the free Type everything"""
    grants: AccessGrants = _grants([(31, [SERVER_TYPE_ID], ['delete', 'view'])], [(32, [ROUTER_TYPE_ID], ['view'])])

    assert operations_allowed(grants, [SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID]) == {
        SERVER_TYPE_ID: [VIEW, DELETE],
        ROUTER_TYPE_ID: [],
        FREE_TYPE_ID: [VIEW, CREATE, EDIT, DELETE],
    }
