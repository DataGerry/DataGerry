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
Unit tests for the managers of the permission data model: FieldClassesManager, ScopeRolesManager,
AccessAssignmentsManager

Driven past a MagicMock standing in for the manager (no database): each read asks for the right criteria, without
``_id``, ascending by public_id; each bulk write hands one filter to one call and answers its count; a database
failure is raised as the manager's own error carrying it, a programming error propagates as itself. What the criteria
match is the integration tier's question
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.manager.access_assignments_manager import BY_PUBLIC_ID, AccessAssignmentsManager
from cmdb.manager.field_classes_manager import FieldClassesManager
from cmdb.manager.scope_roles_manager import ScopeRolesManager
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.access_assignments_manager import (
    AccessAssignmentsManagerDeleteError,
    AccessAssignmentsManagerGetError,
)
from cmdb.errors.manager.field_classes_manager import FieldClassesManagerGetError
from cmdb.errors.manager.scope_roles_manager import ScopeRolesManagerGetError, ScopeRolesManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42
ROLE_ID: int = 7
GROUP_ID: int = 4
CLASS_NAME: str = 'compliance'
CHANGED: int = 3
STORED: list[dict[str, Any]] = [{'public_id': 1}, {'public_id': 2}]
WHOLE: dict[str, int] = {'_id': 0}


def _mock(manager_class: type) -> MagicMock:
    """A stand-in whose private reader is the real one, so the public methods can be followed into it"""
    mock = MagicMock(spec=manager_class)
    mock.find.return_value = STORED

    for name in ('_find_roles', '_find_assignments'):
        if hasattr(manager_class, name):
            real: Any = getattr(manager_class, name)
            setattr(mock, name, lambda *args, real=real: real(mock, *args))

    return mock


class TestFindExistingNames:
    """FieldClassesManager.find_existing_names - one projected $in read."""

    def test_the_stored_subset(self) -> None:
        """Reads the names only and answers the ones found"""
        mock = MagicMock(spec=FieldClassesManager)
        mock.find.return_value = [{'name': CLASS_NAME}]

        assert FieldClassesManager.find_existing_names(mock, [CLASS_NAME, 'other']) == {CLASS_NAME}
        mock.find.assert_called_once_with(criteria={'name': {'$in': [CLASS_NAME, 'other']}},
                                          projection={'name': 1, '_id': 0})

    @pytest.mark.parametrize('names', [[], None], ids=['empty', 'none'])
    def test_nothing_asked_reads_nothing(self, names: Any) -> None:
        """No query for no names"""
        mock = MagicMock(spec=FieldClassesManager)

        assert FieldClassesManager.find_existing_names(mock, names) == set()
        mock.find.assert_not_called()

    def test_a_failed_read_is_the_managers_error(self) -> None:
        """Carrying the cause"""
        mock = MagicMock(spec=FieldClassesManager)
        cause = BaseManagerGetError('down')
        mock.find.side_effect = cause

        with pytest.raises(FieldClassesManagerGetError) as raised:
            FieldClassesManager.find_existing_names(mock, [CLASS_NAME])

        assert raised.value.args[0] is cause


USAGE_READS: list[tuple[type, str, Any, dict[str, Any]]] = [
    (ScopeRolesManager, 'roles_granting_class', CLASS_NAME, {'field_classes': CLASS_NAME}),
    (ScopeRolesManager, 'roles_naming_type', TYPE_ID, {'types': TYPE_ID}),
    (AccessAssignmentsManager, 'assignments_of_role', ROLE_ID, {'role_id': ROLE_ID}),
    (AccessAssignmentsManager, 'assignments_of_group', GROUP_ID, {'group_id': GROUP_ID}),
    (ScopeRolesManager, 'roles_covering_type', TYPE_ID, {'$or': [{'types': TYPE_ID}, {'types': '*'}]}),
    (AccessAssignmentsManager, 'assignments_of_roles', [ROLE_ID, 8], {'role_id': {'$in': [ROLE_ID, 8]}}),
]
# The error each manager raises for a failed read
GET_ERROR: dict[type, type[Exception]] = {
    ScopeRolesManager: ScopeRolesManagerGetError,
    AccessAssignmentsManager: AccessAssignmentsManagerGetError,
}
USAGE_READ_IDS: list[str] = [
    'roles-of-class', 'roles-of-type', 'assignments-of-role', 'assignments-of-group', 'roles-covering-type',
    'assignments-of-roles',
]


@pytest.mark.parametrize('manager_class, method, argument, criteria', USAGE_READS, ids=USAGE_READ_IDS)
def test_a_usage_read_queries_whole_documents_in_order(manager_class: type, method: str, argument: Any,
                                                       criteria: dict[str, Any]) -> None:
    """The criteria, no ``_id``, ascending by public_id; the documents as read"""
    mock = _mock(manager_class)

    assert getattr(manager_class, method)(mock, argument) == STORED
    mock.find.assert_called_once_with(criteria=criteria, projection=WHOLE, sort=BY_PUBLIC_ID)


@pytest.mark.parametrize('manager_class, method, argument, criteria', USAGE_READS, ids=USAGE_READ_IDS)
def test_a_failed_usage_read_is_the_managers_error(manager_class: type, method: str, argument: Any,
                                                   criteria: dict[str, Any]) -> None:
    """Carrying the cause, whichever the criteria"""
    mock = _mock(manager_class)
    cause = BaseManagerGetError(f'down for {criteria}')
    mock.find.side_effect = cause

    with pytest.raises(GET_ERROR[manager_class]) as raised:
        getattr(manager_class, method)(mock, argument)

    assert raised.value.args[0] is cause


def test_the_order_is_ascending_public_id() -> None:
    """Both managers answer in the same order"""
    assert BY_PUBLIC_ID == [('public_id', 1)]


class TestPullTypeFromRoles:
    """ScopeRolesManager.pull_type_from_roles - one $pull over every role listing the Type."""

    def test_one_pull_and_its_count(self) -> None:
        """Matches the roles listing the id and pulls it from their Types"""
        mock = MagicMock(spec=ScopeRolesManager)
        mock.update_many_pull.return_value = MagicMock(modified_count=CHANGED)

        assert ScopeRolesManager.pull_type_from_roles(mock, TYPE_ID) == CHANGED
        mock.update_many_pull.assert_called_once_with({'types': TYPE_ID}, {'types': TYPE_ID})

    def test_a_failed_write_is_the_managers_error(self) -> None:
        """Carrying the cause"""
        mock = MagicMock(spec=ScopeRolesManager)
        cause = BaseManagerUpdateError('down')
        mock.update_many_pull.side_effect = cause

        with pytest.raises(ScopeRolesManagerUpdateError) as raised:
            ScopeRolesManager.pull_type_from_roles(mock, TYPE_ID)

        assert raised.value.args[0] is cause

    def test_a_programming_error_propagates(self) -> None:
        """Not wrapped"""
        mock = MagicMock(spec=ScopeRolesManager)
        mock.update_many_pull.side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            ScopeRolesManager.pull_type_from_roles(mock, TYPE_ID)


class TestDeleteAssignments:
    """AccessAssignmentsManager.delete_assignments - one delete_many of exactly the given ids."""

    def test_one_delete_and_its_count(self) -> None:
        """By public_id, counted"""
        mock = MagicMock(spec=AccessAssignmentsManager)
        mock.delete_many.return_value = MagicMock(deleted_count=CHANGED)

        assert AccessAssignmentsManager.delete_assignments(mock, [1, 2]) == CHANGED
        mock.delete_many.assert_called_once_with({'public_id': {'$in': [1, 2]}})

    def test_nothing_to_delete_writes_nothing(self) -> None:
        """An empty selection"""
        mock = MagicMock(spec=AccessAssignmentsManager)

        assert AccessAssignmentsManager.delete_assignments(mock, []) == 0
        mock.delete_many.assert_not_called()

    def test_a_failed_delete_is_the_managers_error(self) -> None:
        """Carrying the cause"""
        mock = MagicMock(spec=AccessAssignmentsManager)
        cause = BaseManagerDeleteError('down')
        mock.delete_many.side_effect = cause

        with pytest.raises(AccessAssignmentsManagerDeleteError) as raised:
            AccessAssignmentsManager.delete_assignments(mock, [GROUP_ID])

        assert raised.value.args[0] is cause

class TestPullMissingTypes:
    """ScopeRolesManager.pull_missing_types - one $pull of every id not stored, on the roles listing ids."""

    def test_one_pull_and_its_count(self) -> None:
        """Roles whose Types are a list; everything not among the stored ids leaves"""
        mock = MagicMock(spec=ScopeRolesManager)
        mock.update_many_raw.return_value = MagicMock(modified_count=CHANGED)

        assert ScopeRolesManager.pull_missing_types(mock, [TYPE_ID]) == CHANGED
        mock.update_many_raw.assert_called_once_with({'types': {'$type': 'array'}},
                                                     {'$pull': {'types': {'$nin': [TYPE_ID]}}})

    def test_a_failed_write_is_the_managers_error(self) -> None:
        """Carrying the cause"""
        mock = MagicMock(spec=ScopeRolesManager)
        cause = BaseManagerUpdateError('down')
        mock.update_many_raw.side_effect = cause

        with pytest.raises(ScopeRolesManagerUpdateError) as raised:
            ScopeRolesManager.pull_missing_types(mock, [])

        assert raised.value.args[0] is cause


def test_a_group_read_for_a_ledger_keeps_the_mongo_id() -> None:
    """with_mongo_id reads without a projection"""
    mock = _mock(AccessAssignmentsManager)

    AccessAssignmentsManager.assignments_of_group(mock, GROUP_ID, with_mongo_id=True)

    mock.find.assert_called_once_with(criteria={'group_id': GROUP_ID}, projection=None, sort=BY_PUBLIC_ID)


class TestMigrationReports:
    """ScopeRolesManager.migration_reports"""

    TYPE_REPORT: dict[str, Any] = {'status': 'complete', 'types': []}
    RIGHTS_REPORT: dict[str, Any] = {'groups': [{'group_id': 7, 'granted': ['base.access.view']}]}

    def test_each_report_read_by_its_id_without_mongo_id(self) -> None:
        """The report collection, one document per id, keyed by it"""
        mock = _mock(ScopeRolesManager)
        mock.get_many_from_other_collection.side_effect = [[self.TYPE_REPORT], [self.RIGHTS_REPORT]]

        assert ScopeRolesManager.migration_reports(mock) == {
            'type_acl_migration': self.TYPE_REPORT, 'access_rights_migration': self.RIGHTS_REPORT,
        }
        assert mock.get_many_from_other_collection.call_args_list == [
            call('access.migrationReport', limit=1, projection=WHOLE, criteria={'_id': report_id})
            for report_id in ('type_acl_migration', 'access_rights_migration')
        ]

    def test_a_missing_report_is_absent(self) -> None:
        """Only the rights migration ran"""
        mock = _mock(ScopeRolesManager)
        mock.get_many_from_other_collection.side_effect = [[], [self.RIGHTS_REPORT]]

        assert ScopeRolesManager.migration_reports(mock) == {'access_rights_migration': self.RIGHTS_REPORT}

    def test_no_report_is_empty(self) -> None:
        """A database no migration wrote to"""
        mock = _mock(ScopeRolesManager)
        mock.get_many_from_other_collection.return_value = []

        assert not ScopeRolesManager.migration_reports(mock)

    def test_a_failed_read_is_the_managers_error(self) -> None:
        """Carrying the cause"""
        mock = _mock(ScopeRolesManager)
        cause = BaseManagerGetError('down')
        mock.get_many_from_other_collection.side_effect = cause

        with pytest.raises(ScopeRolesManagerGetError) as raised:
            ScopeRolesManager.migration_reports(mock)

        assert raised.value.args[0] is cause


def test_no_roles_read_no_assignments() -> None:
    """assignments_of_roles([]) asks nothing"""
    mock = _mock(AccessAssignmentsManager)

    assert AccessAssignmentsManager.assignments_of_roles(mock, []) == []
    mock.find.assert_not_called()
