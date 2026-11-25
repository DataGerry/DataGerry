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
Unit tests for the access-control pipeline filter

The user-facing functions delegate to the access engine, asked in scope operations (READ is view); the type ACL's own
criteria builder - frozen for the migrations and the equivalence tests - and the exclusion condition are pure.
"""
from typing import Any

import pytest

from cmdb.framework import access_engine
from cmdb.models.access_model import ScopeOperation
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import (
    build_acl_pipeline,
    build_denied_types_condition,
    build_denied_types_criteria,
    build_group_permissions_path,
    build_permitted_types_criteria,
    normalize_permissions,
    resolve_denied_type_ids,
)
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

# "no stages at all" is the contract for an unrestricted group, so these assert the exact empty list
# rather than falsiness - a None slipping through would break every caller that splices the result
# pylint: disable=use-implicit-booleaness-not-comparison

GROUP_ID: int = 7
OTHER_GROUP_ID: int = 3
GROUPS: list[int] = [GROUP_ID]
DENIED_TYPE_IDS: list[int] = [3, 9]
TYPE_ID_KEY: str = 'type_id'
PUBLIC_ID_KEY: str = 'public_id'


USER: CmdbUser = CmdbUser(public_id=51, user_name='acl-builder', active=True, group_ids=GROUPS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_group_permissions_path                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildGroupPermissionsPath:
    """The dotted path addressing one group's permission list inside a stored type's ACL."""

    def test_path_shape(self) -> None:
        """The path walks acl -> groups -> includes -> <group_id>."""
        assert build_group_permissions_path(GROUP_ID) == f'acl.groups.includes.{GROUP_ID}'

    def test_group_id_is_interpolated(self) -> None:
        """A different group addresses a different key."""
        assert build_group_permissions_path(1).endswith('.1')


# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_denied_types_criteria                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildDeniedTypesCriteria:
    """The framework.types filter selecting the types a user's groups may not access."""

    @staticmethod
    def _clauses() -> list[dict[str, Any]]:
        """The two $and clauses of the criteria."""
        return build_denied_types_criteria(GROUPS, AccessControlPermission.READ)['$and']

    def test_only_an_activated_acl_can_deny(self) -> None:
        """
        Only `activated: true` denies - a type with no ACL, one switched off, one carrying no `activated` key
        or a null one is never denied

        That is the model's reading (`AccessControlList.from_data` defaults the flag to False). The flag is
        stored as a boolean only, so an equality test is that reading exactly and a listing and a single object
        read never disagree on the same stored document.
        """
        assert {'acl.activated': True} in self._clauses()

    def test_negates_the_permission_check(self) -> None:
        """The group is denied unless its list carries the permission, via $nor over an equality on the array"""
        expected = {'$nor': [{f'acl.groups.includes.{GROUP_ID}': 'READ'}]}

        assert expected in self._clauses()

    def test_uses_the_permission_string_value(self) -> None:
        """A stored ACL holds permission strings, so the query must compare against .value."""
        criteria = build_denied_types_criteria(GROUPS, AccessControlPermission.UPDATE)

        assert criteria['$and'][1]['$nor'][0][f'acl.groups.includes.{GROUP_ID}'] == 'UPDATE'

    @pytest.mark.parametrize('permission', list(AccessControlPermission))
    def test_every_permission_builds_a_criteria(self, permission: AccessControlPermission) -> None:
        """Each of the four permissions produces a well-formed two-clause criteria."""
        assert len(build_denied_types_criteria(GROUPS, permission)['$and']) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                the user-facing functions delegate to the access engine                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDelegation:
    """resolve_denied_type_ids, build_acl_pipeline and build_permitted_types_criteria ask the engine, in operations"""

    def test_resolve_denied_type_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """READ is asked as view; the engine's ids answered"""
        asked: list[Any] = []
        monkeypatch.setattr(access_engine, 'denied_type_ids',
                            lambda user, operations: asked.append((user, operations)) or DENIED_TYPE_IDS)

        assert resolve_denied_type_ids(USER, AccessControlPermission.READ) == DENIED_TYPE_IDS
        assert asked == [(USER, [ScopeOperation.VIEW])]

    def test_build_acl_pipeline_wraps_the_scope_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One $match of the engine's filter; UPDATE asked as edit"""
        asked: list[Any] = []
        monkeypatch.setattr(access_engine, 'scope_filter',
                            lambda user, operations: asked.append(operations) or {TYPE_ID_KEY: {'$nin': [3]}})

        assert build_acl_pipeline(USER, AccessControlPermission.UPDATE) == [{'$match': {TYPE_ID_KEY: {'$nin': [3]}}}]
        assert asked == [[ScopeOperation.EDIT]]

    def test_nothing_denied_produces_no_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty filter is no stage at all"""
        monkeypatch.setattr(access_engine, 'scope_filter', lambda user, operations: {})

        assert build_acl_pipeline(USER, AccessControlPermission.READ) == []

    def test_build_permitted_types_criteria_asks_every_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Several permissions are several operations, all to be held"""
        asked: list[Any] = []
        monkeypatch.setattr(access_engine, 'permitted_types_criteria',
                            lambda user, operations: asked.append((user, operations)) or {PUBLIC_ID_KEY: 1})

        assert build_permitted_types_criteria(
            USER, [AccessControlPermission.READ, AccessControlPermission.CREATE]) == {PUBLIC_ID_KEY: 1}
        assert asked == [(USER, [ScopeOperation.VIEW, ScopeOperation.CREATE])]


# ---------------------------------------------- build_denied_types_condition ---------------------------------------- #

def test_build_denied_types_condition_excludes_the_given_ids() -> None:
    """The one spelling of 'exclude these types', as a filter document."""
    assert build_denied_types_condition(DENIED_TYPE_IDS) == {TYPE_ID_KEY: {'$nin': DENIED_TYPE_IDS}}


# ------------------------------------------------ normalize_permissions --------------------------------------------- #

def test_normalize_permissions_wraps_a_single_permission() -> None:
    """The single form is the special case of the list form, so only this function knows the difference."""
    assert normalize_permissions(AccessControlPermission.READ) == [AccessControlPermission.READ]


def test_normalize_permissions_keeps_a_list_in_order() -> None:
    """The order survives, so a built criteria is stable and comparable."""
    asked = [AccessControlPermission.READ, AccessControlPermission.CREATE]

    assert normalize_permissions(asked) == asked


def test_normalize_permissions_drops_repeats() -> None:
    """`?acl=READ,READ` is the same question asked once."""
    asked = [AccessControlPermission.READ, AccessControlPermission.CREATE, AccessControlPermission.READ]

    assert normalize_permissions(asked) == [AccessControlPermission.READ, AccessControlPermission.CREATE]


def test_normalize_permissions_refuses_an_empty_list() -> None:
    """
    An empty `$all` matches no document at all

    So an empty permission list would deny every ACL-carrying type rather than restrict nothing - a
    silently wrong answer that still returns 200.
    """
    with pytest.raises(ValueError):
        normalize_permissions([])


# ------------------------------------------- criteria over several permissions -------------------------------------- #

def test_denied_criteria_requires_all_of_several_permissions() -> None:
    """Denied when ANY permission is missing - so all of them are required, the Angular getAclFilter reading"""
    criteria = build_denied_types_criteria(
        GROUPS, [AccessControlPermission.READ, AccessControlPermission.CREATE],
    )

    assert criteria['$and'][1] == {'$or': [
        {'$nor': [{build_group_permissions_path(GROUP_ID): 'READ'}]},
        {'$nor': [{build_group_permissions_path(GROUP_ID): 'CREATE'}]},
    ]}


def test_denied_criteria_for_one_permission_needs_no_or() -> None:
    """A single permission is the plain two-clause criteria"""
    assert build_denied_types_criteria(GROUPS, AccessControlPermission.READ) == {
        '$and': [
            {'acl.activated': True},
            {'$nor': [{build_group_permissions_path(GROUP_ID): 'READ'}]},
        ]
    }


# ---------------------------------------------- criteria over several groups ---------------------------------------- #

def test_denied_criteria_asks_every_group_for_the_permission() -> None:
    """A permission is missing only when no group lists it - one $nor over every group's entry, in id order"""
    criteria = build_denied_types_criteria([GROUP_ID, OTHER_GROUP_ID], AccessControlPermission.READ)

    assert criteria['$and'][1] == {'$nor': [
        {build_group_permissions_path(OTHER_GROUP_ID): 'READ'},
        {build_group_permissions_path(GROUP_ID): 'READ'},
    ]}


def test_denied_criteria_combines_the_groups_per_permission() -> None:
    """Several groups and permissions: each permission may come from a different group (the union)"""
    criteria = build_denied_types_criteria(
        [GROUP_ID, OTHER_GROUP_ID], [AccessControlPermission.READ, AccessControlPermission.CREATE],
    )

    assert criteria['$and'][1] == {'$or': [
        {'$nor': [{build_group_permissions_path(group): permission} for group in (OTHER_GROUP_ID, GROUP_ID)]}
        for permission in ('READ', 'CREATE')
    ]}


def test_denied_criteria_reads_each_group_once() -> None:
    """Repeated and string ids are one int entry each"""
    assert build_denied_types_criteria([GROUP_ID, str(GROUP_ID), GROUP_ID], AccessControlPermission.READ) == \
        build_denied_types_criteria(GROUPS, AccessControlPermission.READ)


def test_no_groups_deny_every_activated_acl() -> None:
    """Fail closed - and no empty $nor, which MongoDB refuses"""
    assert build_denied_types_criteria([], AccessControlPermission.READ) == {'acl.activated': True}
