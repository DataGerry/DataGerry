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
Unit tests for cmdb.security.acl.engine_read_errors

An access engine read failure inside a type ACL function is re-raised as a BaseManagerGetError carrying it - the error
every caller already wraps; any other exception passes as it is; a result passes untouched
"""
import pytest

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.access_assignments_manager import AccessAssignmentsManagerGetError
from cmdb.errors.manager.scope_roles_manager import ScopeRolesManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.framework import access_engine
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.engine_read_errors import as_manager_read_error
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

ANSWER: list[int] = [3, 9]
USER: CmdbUser = CmdbUser(public_id=51, user_name='engine-errors', active=True, group_ids=[21])


@pytest.mark.parametrize('error', [AccessAssignmentsManagerGetError('down'), ScopeRolesManagerGetError('down'),
                                   TypesManagerGetError('down')], ids=['assignments', 'roles', 'types'])
def test_an_engine_read_failure_is_a_manager_read_error(error: Exception) -> None:
    """Carrying the original as args[0] and as the cause"""
    @as_manager_read_error
    def failing() -> None:
        raise error

    with pytest.raises(BaseManagerGetError) as raised:
        failing()

    assert raised.value.__cause__ is error
    assert raised.value.args[0] is error


def test_any_other_exception_passes() -> None:
    """Not an engine read - not ours to type"""
    @as_manager_read_error
    def failing() -> None:
        raise KeyError('bug')

    with pytest.raises(KeyError):
        failing()


def test_a_result_passes_untouched() -> None:
    """The common case"""
    @as_manager_read_error
    def answering() -> list[int]:
        return ANSWER

    assert answering() is ANSWER


def test_a_delegating_function_answers_a_manager_read_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_denied_type_ids as its callers expect it to fail"""
    def down(*_args: object) -> list[int]:
        raise ScopeRolesManagerGetError('down')

    monkeypatch.setattr(access_engine, 'denied_type_ids', down)

    with pytest.raises(BaseManagerGetError):
        resolve_denied_type_ids(USER, AccessControlPermission.READ)
