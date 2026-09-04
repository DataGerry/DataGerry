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
Validation schemas of the Port Connectivity connection entities

Mirrors cmdb/models/port_connection_model/ one-to-one, as every package under cmdb/class_schema/ does
"""
from cmdb.class_schema.port_connection_model.cmdb_port_connection_schema import (
    get_cmdb_port_connection_schema,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'get_cmdb_port_connection_schema',
]
