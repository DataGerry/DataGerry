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
Unit tests for cmdb.framework.access_rules.access_reference_rules

Past MagicMock managers: a class a role grants and a role an assignment grants are refused with who holds them, a free
one is not; a group's assignments are recorded in the ledger before the one delete, then the request's grants are
dropped; nothing is recorded, deleted or dropped for a group without any
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.framework.access_rules import access_reference_rules
from cmdb.framework.access_rules import (
    AccessRuleMessage,
    delete_group_assignments,
    field_class_in_use,
    scope_role_in_use,
)
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 4
ROLE_ID: int = 21
FIELD_CLASS: dict[str, Any] = {'public_id': 11, 'name': 'compliance'}
HOLDERS: list[dict[str, Any]] = [{'public_id': 2}, {'public_id': 5}]


class TestInUse:
    """The refusals name the holders."""

    def test_a_granted_class(self) -> None:
        """The roles' ids"""
        roles = MagicMock()
        roles.roles_granting_class.return_value = HOLDERS

        assert field_class_in_use(roles, FIELD_CLASS) == AccessRuleMessage.FIELD_CLASS_IN_USE.value.format(
            name='compliance', role_ids=[2, 5])
        roles.roles_granting_class.assert_called_once_with('compliance')

    def test_an_assigned_role(self) -> None:
        """The assignments' ids"""
        assignments = MagicMock()
        assignments.assignments_of_role.return_value = HOLDERS

        assert scope_role_in_use(assignments, ROLE_ID) == AccessRuleMessage.SCOPE_ROLE_IN_USE.value.format(
            role_id=ROLE_ID, assignment_ids=[2, 5])

    def test_free_documents(self) -> None:
        """No holder, no problem"""
        roles, assignments = MagicMock(), MagicMock()
        roles.roles_granting_class.return_value = []
        assignments.assignments_of_role.return_value = []

        assert (field_class_in_use(roles, FIELD_CLASS), scope_role_in_use(assignments, ROLE_ID)) == (None, None)


class TestDeleteGroupAssignments:
    """Recorded first, then one delete."""

    def test_recorded_before_the_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The ledger gets the documents with their _id, then exactly those ids are deleted, then the request's grants
        are dropped; the count answered"""
        order = MagicMock()
        assignments, ledger = MagicMock(), MagicMock()
        assignments.assignments_of_group.return_value = HOLDERS
        assignments.delete_assignments.return_value = 2
        order.attach_mock(ledger.deleted_many, 'record')
        order.attach_mock(assignments.delete_assignments, 'delete')
        monkeypatch.setattr(access_reference_rules, 'forget_grants', order.forget)

        assert delete_group_assignments(ledger, assignments, GROUP_ID) == 2
        assignments.assignments_of_group.assert_called_once_with(GROUP_ID, with_mongo_id=True)
        assert order.mock_calls == [
            call.record(assignments, HOLDERS, AccessRuleMessage.GROUP_ASSIGNMENTS_DELETED.value.format(
                group_id=GROUP_ID)),
            call.delete([2, 5]),
            call.forget(),
        ]

    def test_a_group_without_assignments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing recorded, nothing deleted, nothing to forget"""
        assignments, ledger, forget = MagicMock(), MagicMock(), MagicMock()
        assignments.assignments_of_group.return_value = []
        monkeypatch.setattr(access_reference_rules, 'forget_grants', forget)

        assert delete_group_assignments(ledger, assignments, GROUP_ID) == 0
        ledger.deleted_many.assert_not_called()
        assignments.delete_assignments.assert_not_called()
        forget.assert_not_called()
