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
Domain entities of the Port Connectivity feature

A port is NOT part of its owner CmdbObject's document: CmdbPort is its own document in
framework.ports, holding a one-way 'object_id' reference to the object it belongs to, the way
CmdbRackMount relates to the object it mounts. This package holds that entity plus the side and
document-key enums describing it - including PORT_TEMPLATE_FIELD_KEYS, the field list the virtual
section template is derived from
"""
from cmdb.models.port_model.port_constants import (
    PortKey,
    PortSide,
    PORT_TEMPLATE_FIELD_KEYS,
    PORT_SELECT_FIELD_OPTION_TYPES,
)
from cmdb.models.port_model.cmdb_port import CmdbPort
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PortKey',
    'PortSide',
    'PORT_TEMPLATE_FIELD_KEYS',
    'PORT_SELECT_FIELD_OPTION_TYPES',
    'CmdbPort',
]
