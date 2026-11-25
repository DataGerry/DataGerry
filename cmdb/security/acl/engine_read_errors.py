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
The read failures of the access engine, answered as the type ACL functions always answered them

The type ACL functions read the Types through ``BaseManager`` - a failure was a ``BaseManagerGetError`` - or read
nothing at all. Their callers wrap exactly that error to keep an outage typed. Since the functions delegate to the
access engine, which reads the assignments, the scope roles and the Types through their own managers, a failure of one
of those reads is re-raised as a ``BaseManagerGetError`` carrying it - so every caller's wrapping still holds
"""
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.access_assignments_manager import AccessAssignmentsManagerGetError
from cmdb.errors.manager.scope_roles_manager import ScopeRolesManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ENGINE_READ_ERRORS: tuple[type[Exception], ...] = (
    AccessAssignmentsManagerGetError,
    ScopeRolesManagerGetError,
    TypesManagerGetError,
)

Result = TypeVar('Result')


def as_manager_read_error(function: Callable[..., Result]) -> Callable[..., Result]:
    """
    Re-raises an access engine read failure inside the function as a ``BaseManagerGetError`` carrying it

    Args:
        function (Callable[..., Result]): A type ACL function delegating to the engine

    Returns:
        Callable[..., Result]: The function, its engine read failures typed as before
    """
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Result:
        try:
            return function(*args, **kwargs)
        except ENGINE_READ_ERRORS as err:
            raise BaseManagerGetError(err) from err

    return wrapper
