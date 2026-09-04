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
The port <-> interface link entity of the Port Connectivity feature

A CmdbPortInterfaceLink is its own document in framework.portInterfaceLinks joining one CmdbPort to one
IPAM interface MDS row, N:M. It holds no IP and no MAC: the interface row stays the single source for
those, which is the whole reason a port links to one instead of copying its values.

The reference to that row is SOFT - it addresses a non-durable MDS row id, so a link whose row has gone
is tolerated and reported rather than cascaded
"""
from cmdb.models.port_interface_link_model.port_interface_link_constants import (
    InterfaceRelationType,
    PortInterfaceLinkKey,
    INTERFACE_REFERENCE_KEYS,
    INTERFACE_ROW_INDEX_NAME,
    LINK_IDENTITY_INDEX_NAME,
    LINK_IDENTITY_KEYS,
    PORT_ID_INDEX_NAME,
)
from cmdb.models.port_interface_link_model.cmdb_port_interface_link import CmdbPortInterfaceLink
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'InterfaceRelationType',
    'PortInterfaceLinkKey',
    'INTERFACE_REFERENCE_KEYS',
    'INTERFACE_ROW_INDEX_NAME',
    'LINK_IDENTITY_INDEX_NAME',
    'LINK_IDENTITY_KEYS',
    'PORT_ID_INDEX_NAME',
    'CmdbPortInterfaceLink',
]
