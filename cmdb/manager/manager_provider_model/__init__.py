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
Provides the `ManagerProvider`, its `ManagerType` enum and the registry the two share

`ManagerProvider.get_manager(ManagerType.X, request_user)` is how every REST route obtains a
manager bound to the database that is correct for the requesting user. `MANAGER_CLASSES` is the
`ManagerType -> class` registry behind it and is exported so tests (and any future tooling) can
assert its integrity from the package path. See `manager_provider.py` for the registry contract
and the three steps to register a new manager
"""
from .manager_provider import MANAGER_CLASSES, ManagerProvider
from .manager_type_enum import ManagerType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MANAGER_CLASSES',
    'ManagerProvider',
    'ManagerType',
]
