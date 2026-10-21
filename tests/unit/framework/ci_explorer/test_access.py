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
Unit tests for cmdb.framework.ci_explorer.access

Pure tests: no Mongo, no Flask. The module is the object-ACL filter the whole graph runs through,
so what is pinned here is exactly what may and may not reach the payload:

  - an ACL is a property of the CmdbType, so the decision is per type and costs no query
  - a denied object is dropped, and nothing distinguishes it from an object that is not there
  - an orphan - an object whose type_id resolves to no CmdbType - passes, matching acl/builder.py
  - no user means no filtering, the convention every manager here follows for an internal caller
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.framework.ci_explorer.access import (
    CI_EXPLORER_PERMISSION,
    collect_denied_type_ids,
    filter_accessible_objects,
    is_denied,
)
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 2
OTHER_GROUP_ID: int = 7

OPEN_TYPE_ID: int = 10
DENIED_TYPE_ID: int = 11
ORPHAN_TYPE_ID: int = 99


def _user(group_id: int = GROUP_ID) -> SimpleNamespace:
    """A CmdbUser stand-in carrying the two attributes the module reads."""
    return SimpleNamespace(group_id=group_id, public_id=1)


def _type_doc(public_id: int, acl_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """A CmdbType document; without acl_data it carries no acl key at all."""
    document: dict[str, Any] = {'public_id': public_id, 'name': f'type-{public_id}'}

    if acl_data is not None:
        document['acl'] = acl_data

    return document


def _locked_acl(includes: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """An activated ACL; with no includes it denies every group."""
    return {
        AclKey.ACTIVATED.value: True,
        AclKey.GROUPS.value: {AclKey.INCLUDES.value: includes or {}},
    }


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A CmdbObject document reduced to what the filter reads."""
    return {'public_id': public_id, 'type_id': type_id}


class TestCollectDeniedTypeIds:
    """Which of the in-scope types the requesting user may not read."""

    def test_no_user_disables_access_control(self) -> None:
        """An internal caller with no user to check is not filtered - same rule as verify_access."""
        types_by_id = {DENIED_TYPE_ID: _type_doc(DENIED_TYPE_ID, _locked_acl())}

        assert collect_denied_type_ids(types_by_id, None) == set()

    def test_types_without_an_acl_are_never_denied(self) -> None:
        """The common case: most installations activate an ACL on few types or none."""
        types_by_id = {OPEN_TYPE_ID: _type_doc(OPEN_TYPE_ID)}

        assert collect_denied_type_ids(types_by_id, _user()) == set()

    def test_an_activated_acl_without_the_group_is_denied(self) -> None:
        """An ACL that names no group at all denies everyone - it fails closed."""
        types_by_id = {
            OPEN_TYPE_ID: _type_doc(OPEN_TYPE_ID),
            DENIED_TYPE_ID: _type_doc(DENIED_TYPE_ID, _locked_acl()),
        }

        assert collect_denied_type_ids(types_by_id, _user()) == {DENIED_TYPE_ID}

    def test_the_users_own_group_decides(self) -> None:
        """The same type is denied to one group and open to another."""
        types_by_id = {
            DENIED_TYPE_ID: _type_doc(DENIED_TYPE_ID, _locked_acl({str(GROUP_ID): ['READ']})),
        }

        assert collect_denied_type_ids(types_by_id, _user(GROUP_ID)) == set()
        assert collect_denied_type_ids(types_by_id, _user(OTHER_GROUP_ID)) == {DENIED_TYPE_ID}

    def test_read_is_the_permission_the_graph_asks_for(self) -> None:
        """A group holding only UPDATE may not read, and the graph is a read surface."""
        types_by_id = {
            DENIED_TYPE_ID: _type_doc(DENIED_TYPE_ID, _locked_acl({str(GROUP_ID): ['UPDATE']})),
        }

        assert CI_EXPLORER_PERMISSION is AccessControlPermission.READ
        assert collect_denied_type_ids(types_by_id, _user()) == {DENIED_TYPE_ID}

    def test_the_permission_is_overridable(self) -> None:
        """The default is READ, but the parameter is real - a future writer can ask for another."""
        types_by_id = {
            DENIED_TYPE_ID: _type_doc(DENIED_TYPE_ID, _locked_acl({str(GROUP_ID): ['READ']})),
        }

        assert collect_denied_type_ids(
            types_by_id, _user(), AccessControlPermission.UPDATE,
        ) == {DENIED_TYPE_ID}

    def test_an_empty_scope_denies_nothing(self) -> None:
        """A graph whose objects carry no resolvable type still has to build."""
        assert collect_denied_type_ids({}, _user()) == set()


class TestIsDenied:
    """The per-object predicate."""

    @pytest.mark.parametrize('type_id, expected', [
        (DENIED_TYPE_ID, True),
        (OPEN_TYPE_ID, False),
        (ORPHAN_TYPE_ID, False),
    ])
    def test_membership_decides(self, type_id: int, expected: bool) -> None:
        """Only an object whose type is in the denied set is denied."""
        assert is_denied(_object(1, type_id), {DENIED_TYPE_ID}) is expected

    def test_an_object_without_a_type_id_passes(self) -> None:
        """An exclusion filter never denies on absence - acl/builder.py lets an orphan through too."""
        assert is_denied({'public_id': 1}, {DENIED_TYPE_ID}) is False


class TestFilterAccessibleObjects:
    """The list filter applied to the whole in-scope union."""

    def test_denied_objects_are_dropped(self) -> None:
        """Silently: what comes back carries no trace that anything was removed."""
        documents = [
            _object(100, OPEN_TYPE_ID),
            _object(101, DENIED_TYPE_ID),
            _object(102, OPEN_TYPE_ID),
        ]

        remaining = filter_accessible_objects(documents, {DENIED_TYPE_ID})

        assert [document['public_id'] for document in remaining] == [100, 102]

    def test_order_is_preserved(self) -> None:
        """The root is first in the union and the composers rely on the rest keeping their order."""
        documents = [_object(public_id, OPEN_TYPE_ID) for public_id in (5, 3, 9, 1)]

        remaining = filter_accessible_objects(documents, {DENIED_TYPE_ID})

        assert [document['public_id'] for document in remaining] == [5, 3, 9, 1]

    def test_nothing_denied_returns_the_same_list(self) -> None:
        """The common path does no work at all, not even a copy."""
        documents = [_object(100, OPEN_TYPE_ID)]

        assert filter_accessible_objects(documents, set()) is documents

    def test_everything_denied_returns_empty(self) -> None:
        """A user denied every type in scope gets an empty graph, not an error."""
        documents = [_object(100, DENIED_TYPE_ID), _object(101, DENIED_TYPE_ID)]

        assert filter_accessible_objects(documents, {DENIED_TYPE_ID}) == []
