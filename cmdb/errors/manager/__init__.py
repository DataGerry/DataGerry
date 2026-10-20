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
This package contains all errors of the BaseManager

Each manager's own package beside it exports its errors and, for a GenericManager, an error map
(``<MANAGER>_ERRORS``) keyed by the operation that fails: 'insert', 'get', 'iterate', 'update', 'delete'. Those are
the only keys a manager reads - building a manager touches no database, so no map has an 'init' entry
(``BaseManagerInitError`` is ``ManagerProvider``'s, when it cannot pick a manager or its tenant database)
"""
from .manager_errors import (
    BaseManagerError,
    BaseManagerInitError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'BaseManagerError',
    'BaseManagerInitError',
    'BaseManagerGetError',
    'BaseManagerInsertError',
    'BaseManagerUpdateError',
    'BaseManagerDeleteError',
    'BaseManagerIterationError',
]
