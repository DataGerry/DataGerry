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
Shared constants for the connection routes mounted at the ``/rest`` root
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ConnectionInfoKey',
]


class ConnectionInfoKey(BaseStrEnum):
    """
    Keys of the ``GET /rest/`` response (frontend contract)

    ``TITLE`` and ``VERSION`` share their string values with ``SystemInfoKey``, which names the keys of
    ``GET /settings/system/``. That overlap is incidental and the two enums are deliberately NOT merged:
    the two routes are separate contracts with different key sets - this one carries ``CONNECTED`` and
    none of the db-version / runtime / startup fields - so one enum would misrepresent both and let a
    change to one route's payload silently edit the other's
    """
    TITLE = 'title'
    VERSION = 'version'
    CONNECTED = 'connected'
