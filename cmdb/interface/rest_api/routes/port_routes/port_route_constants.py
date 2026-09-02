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
Rights, request keys and refusal messages of the Port REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class PortRight(BaseStrEnum):
    """
    ACL right identifiers guarding the Port REST routes

    These guard the PORT surface. They are NOT a substitute for the owner CmdbObject's ACL, which every
    route checks separately: a port lives outside the object document, so nothing about it inherits the
    object's access control and a caller with port rights alone must not read or write the ports of an
    object they cannot see
    """
    VIEW = 'base.framework.port.view'
    ADD = 'base.framework.port.add'
    EDIT = 'base.framework.port.edit'
    DELETE = 'base.framework.port.delete'


class PortRequestKey(BaseStrEnum):
    """
    Body keys a port request may carry

    OBJECT_ID belongs to the CREATE alone: a port can not be moved to another CmdbObject afterwards, so
    an update ignores it in favour of the stored owner. SIDE is settable on create (the creation
    assistant is what sets front/rear) and IMMUTABLE afterwards - changing it would move the port into
    another face's name space, where its name may already be taken.

    The audit fields and PUBLIC_ID are absent on purpose: they are server-owned and stamped from the
    request, never read from the payload
    """
    OBJECT_ID = 'object_id'
    SIDE = 'side'
    NAME = 'name'
    PORT_NUMBER = 'port_number'
    STATUS = 'status'
    PORT_TYPE = 'port_type'
    SPEED = 'speed'
    DESCRIPTION = 'description'


# Refusal (HTTP 404) when the addressed port does not exist
PORT_NOT_FOUND_MESSAGE: str = 'The Port with ID:{public_id} was not found!'

# Refusal (HTTP 404) when the port's owner CmdbObject does not exist
PORT_OWNER_NOT_FOUND_MESSAGE: str = 'The CmdbObject with ID:{object_id} was not found!'

# Refusal (HTTP 400) when the owner's CmdbType does not declare that its objects have ports. 400
# rather than 403: nothing is wrong with the caller's rights, the request itself does not apply
PORT_TYPE_NOT_PORT_BEARING_MESSAGE: str = (
    "The Type of CmdbObject ID:{object_id} does not use ports. Enable 'uses_ports' on the Type first!"
)

# Refusal (HTTP 400) when the name is already taken on this face of this object. The unique index is
# what guarantees it; this message is what makes the common case readable
PORT_NAME_TAKEN_MESSAGE: str = (
    "A Port named '{name}' already exists on the '{side}' side of CmdbObject ID:{object_id}!"
)

# Refusal (HTTP 400) when a select field names a CmdbExtendableOption that does not exist, or one from
# the wrong list - a PORT_TYPE id in the speed field would otherwise be stored and rendered as a speed
PORT_OPTION_INVALID_MESSAGE: str = (
    "The value of '{field}' must be the public_id of a {option_type} option (got ID:{value})!"
)

# Refusal (HTTP 400) when a payload key that is server-owned or immutable carries a different value
PORT_FIELD_IMMUTABLE_MESSAGE: str = "The '{field}' of a Port can not be changed!"

# Refusal (HTTP 400) when the port name is missing or blank. The Cerberus schema states the same rule,
# but these routes read the body themselves (a port has server-owned fields the payload must not set),
# so the check is stated here too
PORT_NAME_REQUIRED_MESSAGE: str = 'A Port needs a name!'
