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
Unit tests for the models of cmdb.models.access_model: CmdbFieldClass, CmdbScopeRole, CmdbAccessAssignment

Pure tests. Each round trip hands the model a document in which every key holds a different value, so a key read
from or written to the wrong place cannot pass; the defaults of an absent key; the lists a document is built from
and written to are copies; each failure is raised as the model's own error; the declared indexes
"""
from typing import Any

import pytest

from cmdb.models.access_model import (
    ASSIGNMENT_UNIQUE_INDEX_NAME,
    UNCONDITIONAL_SCOPE,
    AccessAssignmentKey,
    CmdbAccessAssignment,
    CmdbFieldClass,
    CmdbScopeRole,
    FieldClassKey,
    ScopeRoleKey,
)
from cmdb.errors.models.cmdb_access_assignment import (
    CmdbAccessAssignmentInitFromDataError,
    CmdbAccessAssignmentToJsonError,
)
from cmdb.errors.models.cmdb_field_class import CmdbFieldClassInitFromDataError, CmdbFieldClassToJsonError
from cmdb.errors.models.cmdb_scope_role import (
    CmdbScopeRoleInitError,
    CmdbScopeRoleInitFromDataError,
    CmdbScopeRoleToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIELD_CLASS: dict[str, Any] = {
    FieldClassKey.PUBLIC_ID.value: 11,
    FieldClassKey.NAME.value: 'compliance',
    FieldClassKey.LABEL.value: 'Compliance',
    FieldClassKey.DESCRIPTION.value: 'Only auditors set these',
}
SCOPE_ROLE: dict[str, Any] = {
    ScopeRoleKey.PUBLIC_ID.value: 21,
    ScopeRoleKey.NAME.value: 'Auditor',
    ScopeRoleKey.DESCRIPTION.value: 'Edits the compliance fields',
    ScopeRoleKey.TYPES.value: [3, 7],
    ScopeRoleKey.OPERATIONS.value: ['view', 'edit'],
    ScopeRoleKey.WRITE_REGULAR_FIELDS.value: True,
    ScopeRoleKey.FIELD_CLASSES.value: ['compliance', 'audit'],
}
ASSIGNMENT: dict[str, Any] = {
    AccessAssignmentKey.PUBLIC_ID.value: 31,
    AccessAssignmentKey.GROUP_ID.value: 4,
    AccessAssignmentKey.ROLE_ID.value: 21,
    AccessAssignmentKey.SCOPE.value: '*',
    AccessAssignmentKey.DESCRIPTION.value: 'Security team',
}
UNREADABLE: list[Any] = [None, 'no document', 5]


@pytest.mark.parametrize('model, document, keys', [
    (CmdbFieldClass, FIELD_CLASS, FieldClassKey),
    (CmdbScopeRole, SCOPE_ROLE, ScopeRoleKey),
    (CmdbAccessAssignment, ASSIGNMENT, AccessAssignmentKey),
], ids=['field-class', 'scope-role', 'assignment'])
def test_the_round_trip_keeps_every_key(model: Any, document: dict[str, Any], keys: Any) -> None:
    """from_data then to_json gives back the document, every key the enum names"""
    written: dict[str, Any] = model.to_json(model.from_data(document))

    assert written == document
    assert set(written) == {key.value for key in keys}


class TestDefaults:
    """What an absent key reads as."""

    def test_a_field_class_without_description(self) -> None:
        """''"""
        document: dict[str, Any] = {key: value for key, value in FIELD_CLASS.items()
                                    if key != FieldClassKey.DESCRIPTION.value}

        assert CmdbFieldClass.from_data(document).description == ''

    def test_a_scope_role_with_only_the_required_keys(self) -> None:
        """No description, no regular fields, no classes"""
        role = CmdbScopeRole.from_data({ScopeRoleKey.PUBLIC_ID.value: 1, ScopeRoleKey.NAME.value: 'r',
                                        ScopeRoleKey.TYPES.value: '*', ScopeRoleKey.OPERATIONS.value: []})

        assert (role.description, role.write_regular_fields, role.field_classes, role.types) == ('', False, [], '*')

    def test_an_assignment_without_scope_or_description(self) -> None:
        """The unconditional scope, ''"""
        assignment = CmdbAccessAssignment.from_data({AccessAssignmentKey.PUBLIC_ID.value: 1,
                                                     AccessAssignmentKey.GROUP_ID.value: 2,
                                                     AccessAssignmentKey.ROLE_ID.value: 3})

        assert (assignment.scope, assignment.description) == (UNCONDITIONAL_SCOPE, '')


def test_a_scope_role_copies_its_lists() -> None:
    """Changing the document or the written dict leaves the model alone"""
    document: dict[str, Any] = {**SCOPE_ROLE, ScopeRoleKey.TYPES.value: [3, 7],
                                ScopeRoleKey.FIELD_CLASSES.value: ['compliance']}
    role = CmdbScopeRole.from_data(document)
    document[ScopeRoleKey.TYPES.value].append(9)
    CmdbScopeRole.to_json(role)[ScopeRoleKey.FIELD_CLASSES.value].append('other')

    assert (role.types, role.field_classes) == ([3, 7], ['compliance'])


class TestErrors:
    """Each failure is the model's own error, carrying the cause."""

    @pytest.mark.parametrize('model, error', [
        (CmdbFieldClass, CmdbFieldClassInitFromDataError),
        (CmdbScopeRole, CmdbScopeRoleInitFromDataError),
        (CmdbAccessAssignment, CmdbAccessAssignmentInitFromDataError),
    ], ids=['field-class', 'scope-role', 'assignment'])
    @pytest.mark.parametrize('data', UNREADABLE, ids=['null', 'string', 'number'])
    def test_from_data_of_no_document(self, model: Any, error: type[Exception], data: Any) -> None:
        """Something that is no dict"""
        with pytest.raises(error) as raised:
            model.from_data(data)

        assert isinstance(raised.value.args[0], Exception)

    @pytest.mark.parametrize('model, error', [
        (CmdbFieldClass, CmdbFieldClassToJsonError),
        (CmdbScopeRole, CmdbScopeRoleToJsonError),
        (CmdbAccessAssignment, CmdbAccessAssignmentToJsonError),
    ], ids=['field-class', 'scope-role', 'assignment'])
    def test_to_json_of_no_instance(self, model: Any, error: type[Exception]) -> None:
        """Something that is no model"""
        with pytest.raises(error):
            model.to_json(object())

    def test_a_scope_role_without_operations(self) -> None:
        """None cannot be read as a list of operations"""
        with pytest.raises(CmdbScopeRoleInitError):
            CmdbScopeRole(public_id=1, name='r', types='*', operations=None)


@pytest.mark.parametrize('model, expected', [
    (CmdbFieldClass, {'name': True, 'public_id': True}),
    (CmdbScopeRole, {'name': True, 'types': False, 'field_classes': False, 'public_id': True}),
    (CmdbAccessAssignment, {'group_id_public_id': False, 'role_id_public_id': False, ASSIGNMENT_UNIQUE_INDEX_NAME: True,
                            'public_id': True}),
], ids=['field-class', 'scope-role', 'assignment'])
def test_the_declared_indexes(model: Any, expected: dict[str, bool]) -> None:
    """Each index by name, and whether it is unique"""
    indexes: dict[str, bool] = {index.document['name']: bool(index.document.get('unique'))
                                for index in model.get_index_keys()}

    assert indexes == expected
