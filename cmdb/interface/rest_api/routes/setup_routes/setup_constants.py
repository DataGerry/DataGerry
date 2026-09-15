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
Request keys and query parameters of the setup REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SetupQueryParam(BaseStrEnum):
    """
    Query parameters read by the setup routes
    """
    DATABASE = 'database'


class SetupRequestKey(BaseStrEnum):
    """
    Body keys a setup request may carry

    EMAIL accepts either a single email or a list of them; the route branches on the value type
    """
    EMAIL = 'email'
