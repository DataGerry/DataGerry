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
Request keys and refusal messages of the port <-> interface link REST routes

These routes are guarded by the PORT rights (see PortRight in port_route_constants): a link is an
attribute of a port rather than an entity a user manages on its own, and the design added no fifth
right family for it. Deleting a port is what removes its links, so a caller who may edit a port can
already do everything a link right would have granted
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class InterfaceLinkRequestKey(BaseStrEnum):
    """
    Body keys a port <-> interface link request may carry

    The four identity keys belong to the CREATE alone and are immutable afterwards: they are the
    unique key of the link, so changing one would be creating a different link. Only RELATION_TYPE
    describes the pair, and it is therefore the only thing an update writes.

    PORT_ID is absent: the port comes from the URL, so a body could not disagree with it
    """
    INTERFACE_OBJECT_ID = 'interface_object_id'
    INTERFACE_SECTION_ID = 'interface_section_id'
    INTERFACE_MULTI_DATA_ID = 'interface_multi_data_id'
    RELATION_TYPE = 'relation_type'


# Key under which a resolved read returns the live interface row beside its link. Absent means the
# link is dangling, which is a state the frontend has to render rather than an error
INTERFACE_ROW_KEY: str = 'interface_row'

# Refusal (HTTP 404) when the addressed link does not exist
LINK_NOT_FOUND_MESSAGE: str = 'The Port interface link with ID:{public_id} was not found!'

# Refusal (HTTP 404) when the port named by the URL does not exist
LINK_PORT_NOT_FOUND_MESSAGE: str = 'The Port with ID:{port_id} was not found!'

# Refusal (HTTP 404) when the CmdbObject that should hold the interface row does not exist
LINK_INTERFACE_OBJECT_NOT_FOUND_MESSAGE: str = 'The CmdbObject with ID:{object_id} was not found!'

# Refusal (HTTP 400) when the request names no usable MDS row id. The concept refuses linking an
# interface row that carries no multi_data_id outright: the id IS the reference, so a link without one
# would point at nothing from the moment it was created
LINK_MISSING_MULTI_DATA_ID_MESSAGE: str = (
    'An interface row without a multi_data_id can not be linked - it carries nothing to reference it by!'
)

# Refusal (HTTP 400) when the addressed interface row does not exist on the object. A link is allowed
# to GO dangling later; creating one that already is, is a mistake the write path can see
LINK_INTERFACE_ROW_NOT_FOUND_MESSAGE: str = (
    "CmdbObject ID:{object_id} has no '{section_id}' interface row with multi_data_id {multi_data_id}!"
)

# Refusal (HTTP 400) when the relation type is missing or not one of the fixed five
LINK_RELATION_TYPE_INVALID_MESSAGE: str = (
    "'{relation_type}' is not a valid interface relation type. Allowed: {allowed}"
)

# Refusal (HTTP 400) when this port is already linked to this interface row. The unique index is what
# guarantees it; this message is what makes the common case readable
LINK_ALREADY_EXISTS_MESSAGE: str = (
    'Port ID:{port_id} is already linked to that interface row - change the existing link instead!'
)

# Refusal (HTTP 400) when an update payload would change one of the identity keys
LINK_FIELD_IMMUTABLE_MESSAGE: str = (
    "The '{field}' of a Port interface link can not be changed - delete it and create the new one!"
)
