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
Request keys and refusal messages of the port name preview

The device kind is the assistant's FIRST choice and it replaces any "port side" field: a standard
device gets n plain ports, a patch panel gets equal numbers of front and rear ports, each face named by
its own syntax. Nothing here asks the user which side a port is on - that follows from the kind.

`PortDeviceKind` and the preview's RESPONSE keys live in cmdb.framework.port.name_syntax_constants
beside the builder that writes them; only the request body is this layer's business
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class PortPreviewRequestKey(BaseStrEnum):
    """
    Body keys of a preview request

    SYNTAX names a standard device's ports and a panel's FRONT face; REAR_SYNTAX names the panel's rear
    face and is required for a panel only - the concept gives a panel two syntaxes because its two
    faces are labelled differently far more often than not
    """
    DEVICE_KIND = 'device_kind'
    SYNTAX = 'syntax'
    REAR_SYNTAX = 'rear_syntax'
    COUNT = 'count'
    START_INDEX = 'start_index'
    PREFIX = 'prefix'
    SLOT = 'slot'


# Refusal (HTTP 404) when the CmdbObject the preview is for does not exist
PREVIEW_OWNER_NOT_FOUND_MESSAGE: str = 'The CmdbObject with ID:{object_id} was not found!'

# Refusal (HTTP 400) when the device kind is missing or unknown
PREVIEW_UNKNOWN_DEVICE_KIND_MESSAGE: str = (
    "'{device_kind}' is not a valid device kind. Allowed: {allowed}"
)

# Refusal (HTTP 400) when a patch panel preview carries no syntax for its rear face
PREVIEW_MISSING_REAR_SYNTAX_MESSAGE: str = (
    'A patch panel needs a rear syntax as well - its two faces are named separately!'
)
