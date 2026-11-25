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
Unit tests for cmdb.models.access_model.access_constants and scope_operation_enum

Pure tests: the stored keys and operation values are the API's spelling, the field class name pattern accepts slugs
only, the reserved and unconditional values, the caps, and the package's re-exports
"""
import re

import pytest

from cmdb.models import access_model
from cmdb.models.access_model import (
    ALL_TYPES,
    DESCRIPTION_MAX_LENGTH,
    FIELD_CLASS_NAME_PATTERN,
    LABEL_MAX_LENGTH,
    MAX_ROLE_FIELD_CLASSES,
    MAX_ROLE_TYPES,
    NAME_MAX_LENGTH,
    SYSTEM_FIELD_CLASS,
    UNCONDITIONAL_SCOPE,
    AccessAssignmentKey,
    FieldClassKey,
    ScopeOperation,
    ScopeRoleKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LONGEST_NAME_LENGTH: int = 64


class TestKeys:
    """The stored keys are the API's spelling."""

    @pytest.mark.parametrize('enum, values', [
        (FieldClassKey, ['public_id', 'name', 'label', 'description']),
        (ScopeRoleKey, ['public_id', 'name', 'description', 'types', 'operations', 'write_regular_fields',
                        'field_classes']),
        (AccessAssignmentKey, ['public_id', 'group_id', 'role_id', 'scope', 'description']),
    ], ids=['field-class', 'scope-role', 'assignment'])
    def test_every_key(self, enum: type, values: list[str]) -> None:
        """Each enum names exactly these keys, in this order"""
        assert [member.value for member in enum] == values


class TestScopeOperation:
    """The four operations of the concept."""

    def test_the_values(self) -> None:
        """view, create, edit, delete"""
        assert [operation.value for operation in ScopeOperation] == ['view', 'create', 'edit', 'delete']

    @pytest.mark.parametrize('value, valid', [('view', True), ('edit', True), ('READ', False), ('transfer', False)])
    def test_is_valid(self, value: str, valid: bool) -> None:
        """Only the lowercase operation names; the ACL's permission names are no operation"""
        assert ScopeOperation.is_valid(value) is valid


class TestFieldClassName:
    """A lowercase slug starting with a letter, at most 64 characters."""

    @pytest.mark.parametrize('name', ['compliance', 'iso-27001', 'a', 'audit_trail2', 'a' * LONGEST_NAME_LENGTH])
    def test_accepted(self, name: str) -> None:
        """Letters, digits, dash and underscore after a first letter"""
        assert re.fullmatch(FIELD_CLASS_NAME_PATTERN, name)

    @pytest.mark.parametrize('name', ['', 'Compliance', '1st', '-x', 'with space', 'ümlaut', 'a.b',
                                      'a' * (LONGEST_NAME_LENGTH + 1)])
    def test_refused(self, name: str) -> None:
        """Upper case, a leading digit or dash, other characters, too long"""
        assert re.fullmatch(FIELD_CLASS_NAME_PATTERN, name) is None

    def test_the_reserved_class_is_a_valid_name(self) -> None:
        """'system' fits the pattern - it is refused for being reserved, not for its spelling"""
        assert re.fullmatch(FIELD_CLASS_NAME_PATTERN, SYSTEM_FIELD_CLASS)


class TestValues:
    """The reserved, unconditional values and the caps."""

    def test_reserved_and_unconditional_values(self) -> None:
        """The built-in class, every Type, every object"""
        assert (SYSTEM_FIELD_CLASS, ALL_TYPES, UNCONDITIONAL_SCOPE) == ('system', '*', '*')

    def test_the_caps(self) -> None:
        """Names and labels 255, descriptions 4000, 5000 Types and 1000 classes per role"""
        assert (NAME_MAX_LENGTH, LABEL_MAX_LENGTH, DESCRIPTION_MAX_LENGTH, MAX_ROLE_TYPES,
                MAX_ROLE_FIELD_CLASSES) == (255, 255, 4000, 5000, 1000)


def test_the_package_exports_what_it_declares() -> None:
    """Every name in __all__ resolves on the package"""
    assert all(hasattr(access_model, name) for name in access_model.__all__)
