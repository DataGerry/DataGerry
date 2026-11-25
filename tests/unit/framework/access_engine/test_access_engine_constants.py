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
Unit tests for cmdb.framework.access_engine.access_engine_constants

Each type ACL permission reads as its own scope operation (READ is view, UPDATE edit) and back; every operation is
judged on its states - view and delete the stored object, create the new one, edit both; the maps cannot be changed
"""
from types import MappingProxyType

import pytest

from cmdb.framework.access_engine import (
    AccessDecisionStep,
    ObjectState,
    OPERATION_PERMISSIONS,
    OPERATION_STATES,
    PERMISSION_OPERATIONS,
)
from cmdb.models.access_model import ScopeOperation
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

PAIRS: list[tuple[AccessControlPermission, ScopeOperation]] = [
    (AccessControlPermission.READ, ScopeOperation.VIEW),
    (AccessControlPermission.CREATE, ScopeOperation.CREATE),
    (AccessControlPermission.UPDATE, ScopeOperation.EDIT),
    (AccessControlPermission.DELETE, ScopeOperation.DELETE),
]


class TestPermissionOperations:
    """PERMISSION_OPERATIONS and OPERATION_PERMISSIONS"""

    @pytest.mark.parametrize('permission, operation', PAIRS, ids=[pair[1].value for pair in PAIRS])
    def test_each_permission_reads_as_its_operation(self, permission: AccessControlPermission,
                                                    operation: ScopeOperation) -> None:
        """One pair each way"""
        assert PERMISSION_OPERATIONS[permission] is operation
        assert OPERATION_PERMISSIONS[operation] is permission

    def test_every_member_is_mapped_once(self) -> None:
        """Both maps cover their enum whole - a new permission or operation must be mapped"""
        assert set(PERMISSION_OPERATIONS) == set(AccessControlPermission)
        assert set(OPERATION_PERMISSIONS) == set(ScopeOperation)
        assert len(set(PERMISSION_OPERATIONS.values())) == len(PERMISSION_OPERATIONS)


class TestOperationStates:
    """OPERATION_STATES"""

    @pytest.mark.parametrize('operation, states', [
        (ScopeOperation.VIEW, (ObjectState.BEFORE,)),
        (ScopeOperation.CREATE, (ObjectState.AFTER,)),
        (ScopeOperation.EDIT, (ObjectState.BEFORE, ObjectState.AFTER)),
        (ScopeOperation.DELETE, (ObjectState.BEFORE,)),
    ], ids=['view', 'create', 'edit', 'delete'])
    def test_each_operation_is_judged_on_its_states(self, operation: ScopeOperation,
                                                    states: tuple[ObjectState, ...]) -> None:
        """The concept's table: view / delete before, create after, edit both"""
        assert OPERATION_STATES[operation] == states

    def test_every_operation_has_states(self) -> None:
        """No operation left out"""
        assert set(OPERATION_STATES) == set(ScopeOperation)


class TestReadOnly:
    """The maps are read-only"""

    @pytest.mark.parametrize('mapping', [PERMISSION_OPERATIONS, OPERATION_PERMISSIONS, OPERATION_STATES],
                             ids=['permission_operations', 'operation_permissions', 'operation_states'])
    def test_a_map_cannot_be_changed(self, mapping: MappingProxyType) -> None:
        """A caller cannot rewrite the engine's reading"""
        with pytest.raises(TypeError):
            mapping[next(iter(mapping))] = None  # type: ignore[index]


def test_the_decision_steps() -> None:
    """The values a trace answers"""
    assert [step.value for step in AccessDecisionStep] == ['unrestricted', 'scope', 'field_class']
    assert [state.value for state in ObjectState] == ['before', 'after']
