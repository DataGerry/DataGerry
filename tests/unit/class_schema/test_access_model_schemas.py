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
Unit tests for cmdb.class_schema.access_model - the schemas of field classes, scope roles and assignments

Pure Cerberus tests: what each document accepts and refuses, the defaults a create fills in, and the messages the
own rules report. Whether a Type, group, role or class exists is the write rules' check, not the schema's
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.access_model.cmdb_access_assignment_schema import get_cmdb_access_assignment_schema
from cmdb.class_schema.access_model.cmdb_field_class_schema import get_cmdb_field_class_schema
from cmdb.class_schema.access_model.cmdb_scope_role_schema import get_cmdb_scope_role_schema
from cmdb.models.access_model import (
    DESCRIPTION_MAX_LENGTH,
    LABEL_MAX_LENGTH,
    MAX_ROLE_FIELD_CLASSES,
    MAX_ROLE_TYPES,
    NAME_MAX_LENGTH,
    NOT_BLANK_MSG,
    SCOPE_SHAPE_MSG,
    UNCONDITIONAL_SCOPE,
    AccessAssignmentKey,
    FieldClassKey,
    ScopeRoleKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

CLASS_NAME: str = 'compliance'
CLASS_LABEL: str = 'Compliance'
ROLE_NAME: str = 'Operator'
TYPE_IDS: list[int] = [3, 7]
GROUP_ID: int = 4
ROLE_ID: int = 9

FIELD_CLASS: dict[str, Any] = {FieldClassKey.NAME.value: CLASS_NAME, FieldClassKey.LABEL.value: CLASS_LABEL}
SCOPE_ROLE: dict[str, Any] = {ScopeRoleKey.NAME.value: ROLE_NAME, ScopeRoleKey.TYPES.value: TYPE_IDS,
                              ScopeRoleKey.OPERATIONS.value: ['view', 'create']}
ASSIGNMENT: dict[str, Any] = {AccessAssignmentKey.GROUP_ID.value: GROUP_ID, AccessAssignmentKey.ROLE_ID.value: ROLE_ID,
                              AccessAssignmentKey.SCOPE.value: '*'}


def _validator(schema: dict[str, Any], document: dict[str, Any]) -> Validator:
    """A validator that has judged the document"""
    validator = Validator(schema)
    validator.validate(document)

    return validator


def _errors(schema: dict[str, Any], document: dict[str, Any], key: str) -> str:
    """The errors reported for one key, as text"""
    return str(_validator(schema, document).errors.get(key))


class TestFieldClass:
    """A slug name, never 'system'; a non-blank label; an optional description."""

    def test_the_minimal_class_and_its_default(self) -> None:
        """Name + label; the description defaults to ''"""
        validator = _validator(get_cmdb_field_class_schema(), FIELD_CLASS)

        assert validator.errors == {}
        assert validator.document[FieldClassKey.DESCRIPTION.value] == ''

    @pytest.mark.parametrize('name', ['Compliance', '1st', 'two words', '', None])
    def test_a_name_that_is_no_slug_is_refused(self, name: Any) -> None:
        """Upper case, a leading digit, a space, empty, null"""
        assert _validator(get_cmdb_field_class_schema(), {**FIELD_CLASS, FieldClassKey.NAME.value: name}).errors

    def test_the_built_in_class_is_reserved(self) -> None:
        """'system' fits the pattern but is refused by name"""
        assert 'reserved' in _errors(get_cmdb_field_class_schema(), {**FIELD_CLASS, FieldClassKey.NAME.value: 'system'},
                                     FieldClassKey.NAME.value)

    @pytest.mark.parametrize('label', ['', '   ', 'x' * (LABEL_MAX_LENGTH + 1), None])
    def test_an_unusable_label_is_refused(self, label: Any) -> None:
        """Empty, blank, too long, null"""
        assert _validator(get_cmdb_field_class_schema(), {**FIELD_CLASS, FieldClassKey.LABEL.value: label}).errors

    def test_a_blank_label_names_the_reason(self) -> None:
        """The own rule's message"""
        assert NOT_BLANK_MSG in _errors(get_cmdb_field_class_schema(), {**FIELD_CLASS, FieldClassKey.LABEL.value: ' '},
                                        FieldClassKey.LABEL.value)

    def test_the_description_is_capped(self) -> None:
        """At most DESCRIPTION_MAX_LENGTH characters"""
        document: dict[str, Any] = {**FIELD_CLASS, FieldClassKey.DESCRIPTION.value: 'x' * (DESCRIPTION_MAX_LENGTH + 1)}

        assert _validator(get_cmdb_field_class_schema(), document).errors


class TestScopeRoleTypes:
    """'*' or a list of unique Type ids, the empty list included."""

    @pytest.mark.parametrize('types', ['*', [], [1], TYPE_IDS], ids=['all', 'empty', 'one', 'several'])
    def test_accepted(self, types: Any) -> None:
        """Every Type, no Type, Type ids"""
        assert _validator(get_cmdb_scope_role_schema(), {**SCOPE_ROLE, ScopeRoleKey.TYPES.value: types}).errors == {}

    @pytest.mark.parametrize('types', ['all', '', 5, [0], [True], ['3'], [1.5], None],
                             ids=['other-string', 'empty-string', 'number', 'zero', 'boolean', 'string-id', 'fraction',
                                  'null'])
    def test_refused(self, types: Any) -> None:
        """Any other string, a bare number, ids that are no ids, null"""
        assert _validator(get_cmdb_scope_role_schema(), {**SCOPE_ROLE, ScopeRoleKey.TYPES.value: types}).errors

    def test_a_repeated_type_is_refused(self) -> None:
        """Each Type once"""
        assert 'more than once' in _errors(get_cmdb_scope_role_schema(),
                                           {**SCOPE_ROLE, ScopeRoleKey.TYPES.value: [3, 3]}, ScopeRoleKey.TYPES.value)

    def test_the_type_list_is_capped(self) -> None:
        """At most MAX_ROLE_TYPES ids"""
        types: list[int] = list(range(1, MAX_ROLE_TYPES + 2))

        assert str(MAX_ROLE_TYPES) in _errors(get_cmdb_scope_role_schema(),
                                              {**SCOPE_ROLE, ScopeRoleKey.TYPES.value: types}, ScopeRoleKey.TYPES.value)


class TestScopeRoleRest:
    """Name, operations, the field-write keys and the defaults."""

    def test_the_defaults(self) -> None:
        """No description, no regular fields, no classes"""
        document: dict[str, Any] = _validator(get_cmdb_scope_role_schema(), SCOPE_ROLE).document

        assert (document[ScopeRoleKey.DESCRIPTION.value], document[ScopeRoleKey.WRITE_REGULAR_FIELDS.value],
                document[ScopeRoleKey.FIELD_CLASSES.value]) == ('', False, [])

    @pytest.mark.parametrize('operations', [[], ['view', 'create', 'edit', 'delete']], ids=['none', 'all'])
    def test_any_set_of_operations(self, operations: list[str]) -> None:
        """An empty set is legal - the role then grants nothing"""
        document: dict[str, Any] = {**SCOPE_ROLE, ScopeRoleKey.OPERATIONS.value: operations}

        assert _validator(get_cmdb_scope_role_schema(), document).errors == {}

    @pytest.mark.parametrize('operations', [['READ'], ['view', 'view'], 'view', None],
                             ids=['acl-name', 'repeated', 'no-list', 'null'])
    def test_unusable_operations_are_refused(self, operations: Any) -> None:
        """Only the four operation names, each once, as a list"""
        document: dict[str, Any] = {**SCOPE_ROLE, ScopeRoleKey.OPERATIONS.value: operations}

        assert _validator(get_cmdb_scope_role_schema(), document).errors

    @pytest.mark.parametrize('name', ['', '  ', 'x' * (NAME_MAX_LENGTH + 1)], ids=['empty', 'blank', 'too-long'])
    def test_an_unusable_name_is_refused(self, name: str) -> None:
        """Non-blank, at most NAME_MAX_LENGTH"""
        assert _validator(get_cmdb_scope_role_schema(), {**SCOPE_ROLE, ScopeRoleKey.NAME.value: name}).errors

    @pytest.mark.parametrize('classes', [['system'], ['Compliance'], ['a', 'a'], ['a'] * (MAX_ROLE_FIELD_CLASSES + 1)],
                             ids=['reserved', 'no-slug', 'repeated', 'too-many'])
    def test_unusable_field_classes_are_refused(self, classes: list[str]) -> None:
        """Slug names, never the built-in class, each once, capped"""
        document: dict[str, Any] = {**SCOPE_ROLE, ScopeRoleKey.FIELD_CLASSES.value: classes}

        assert _validator(get_cmdb_scope_role_schema(), document).errors

    def test_the_write_keys_are_kept(self) -> None:
        """Regular fields on, one class"""
        document: dict[str, Any] = {**SCOPE_ROLE, ScopeRoleKey.WRITE_REGULAR_FIELDS.value: True,
                                    ScopeRoleKey.FIELD_CLASSES.value: [CLASS_NAME]}
        validator = _validator(get_cmdb_scope_role_schema(), document)

        assert validator.errors == {}
        assert validator.document[ScopeRoleKey.FIELD_CLASSES.value] == [CLASS_NAME]


class TestAssignment:
    """Two ids and a scope: '*' or a list."""

    def test_the_minimal_assignment(self) -> None:
        """Group, role, '*'; the description defaults to ''"""
        validator = _validator(get_cmdb_access_assignment_schema(), ASSIGNMENT)

        assert validator.errors == {}
        assert validator.document[AccessAssignmentKey.DESCRIPTION.value] == ''

    @pytest.mark.parametrize('scope', [{'location': {'within': 1}}, 'all', '', None],
                             ids=['object', 'other-string', 'empty', 'null'])
    def test_any_other_scope_is_refused_with_the_reason(self, scope: Any) -> None:
        """'*' or a list - nothing else"""
        document: dict[str, Any] = {**ASSIGNMENT, AccessAssignmentKey.SCOPE.value: scope}

        assert SCOPE_SHAPE_MSG.format(unconditional=UNCONDITIONAL_SCOPE) in _errors(
            get_cmdb_access_assignment_schema(), document, AccessAssignmentKey.SCOPE.value)

    @pytest.mark.parametrize('scope', [[], [{'field': 'size', 'op': 'exists'}], [{'unknown': 1}]],
                             ids=['empty-list', 'condition', 'malformed-condition'])
    def test_a_list_passes_the_schema(self, scope: Any) -> None:
        """Its conditions are the write rules' to judge against the role's Types (R29)"""
        assert _validator(get_cmdb_access_assignment_schema(),
                          {**ASSIGNMENT, AccessAssignmentKey.SCOPE.value: scope}).errors == {}

    def test_the_scope_is_required(self) -> None:
        """No default - a client says which objects"""
        document: dict[str, Any] = {key: value for key, value in ASSIGNMENT.items()
                                    if key != AccessAssignmentKey.SCOPE.value}

        assert _validator(get_cmdb_access_assignment_schema(), document).errors

    @pytest.mark.parametrize('key', [AccessAssignmentKey.GROUP_ID.value, AccessAssignmentKey.ROLE_ID.value])
    @pytest.mark.parametrize('value', [0, True, '4', None], ids=['zero', 'boolean', 'string', 'null'])
    def test_an_id_that_is_no_id_is_refused(self, key: str, value: Any) -> None:
        """Whole numbers from 1, never a boolean"""
        assert _validator(get_cmdb_access_assignment_schema(), {**ASSIGNMENT, key: value}).errors
