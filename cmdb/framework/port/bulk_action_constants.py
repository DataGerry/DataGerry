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
Constants of the port BULK ACTIONS - edit, delete and resolve (concept §30-35)

Names the request keys the three bulk routes read, the keys of what they answer, and every refusal
they report. The bulk CREATION has its own set in ``bulk_create_constants``: it takes a generator
specification rather than a selection, so the two share no vocabulary beyond the port model's own
"""
from cmdb.utils import BaseStrEnum

from cmdb.models.port_model.port_constants import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

# The port fields a bulk edit may set, and nothing else. `name` and `port_number` are excluded because
# they identify a port within its face - one value applied to a selection would collide by
# construction - and `object_id` / `side` because they are a port's identity, immutable on the single
# update route for the same reason
BULK_EDITABLE_FIELDS: tuple[PortKey, ...] = (
    PortKey.STATUS,
    PortKey.PORT_TYPE,
    PortKey.SPEED,
    PortKey.DESCRIPTION,
)


class BulkActionRequestKey(BaseStrEnum):
    """
    Body keys the bulk action routes read

    The selection and the new values are separate blocks on purpose: it is what lets an unknown field
    name inside VALUES be reported as such instead of being silently ignored, and it keeps the two
    delete routes (which carry no values) the same shape as the edit one

    PORT_IDS / CONNECTION_IDS never carry the owner object - that comes from the URL, so a body could
    not disagree with it
    """
    PORT_IDS = 'port_ids'
    CONNECTION_IDS = 'connection_ids'
    VALUES = 'values'


class BulkActionKey(BaseStrEnum):
    """
    Keys of what a bulk action answers with

    Every action reports WHAT it touched, not just how many: a client that asked for five ports and
    reads `updated: 5` learns nothing it did not already know, while the id lists are what it needs to
    refresh exactly those rows. The delete action also lists what its cascade took, because those rows
    were never named by the caller
    """
    UPDATED = 'updated'
    DELETED = 'deleted'
    RESOLVED = 'resolved'
    PORT_IDS = 'port_ids'
    CONNECTION_IDS = 'connection_ids'
    INTERFACE_LINK_IDS = 'interface_link_ids'
    PORTS = 'ports'


class BulkDeletePreviewKey(BaseStrEnum):
    """
    Keys of one port's entry in the delete pre-check

    The concept requires a bulk action to *"inform the user of the consequences"* (§41), and the
    consequence of deleting a port is never only the port: its connections and its interface links go
    with it. Each entry names the port the way the table shows it, so the dialog can list them without
    a second read
    """
    PORT_ID = 'port_id'
    NAME = 'name'
    SIDE = 'side'
    CONNECTION_IDS = 'connection_ids'
    INTERFACE_LINK_IDS = 'interface_link_ids'


class BulkActionError(BaseStrEnum):
    """
    Messages reported when a bulk action is refused

    Members with a `{...}` placeholder are filled via `format()`. Every one is an HTTP 400: a bulk
    action is validated as a WHOLE and applied only if every element passes, so these are reasons the
    request was not carried out at all - nothing partial happened
    """
    INVALID_SELECTION = "'{key}' must be a non-empty list of ids!"
    UNKNOWN_PORT = 'No Port with ID {port_id} exists!'
    FOREIGN_PORT = 'The Port with ID {port_id} does not belong to CmdbObject ID {object_id}!'
    UNKNOWN_CONNECTION = 'No Port connection with ID {connection_id} exists!'
    FOREIGN_CONNECTION = 'The Port connection with ID {connection_id} does not touch a Port of ' \
                         'CmdbObject ID {object_id}!'
    NO_VALUES = "'{key}' must name at least one field to set. Allowed: {allowed}"
    UNKNOWN_VALUE_FIELD = "'{field}' can not be set by a bulk edit. Allowed: {allowed}"


# Prefix of the aggregated abort message, so a refusal says which action was refused and that NOTHING
# was carried out - the difference between this and a partial application is the whole point
BULK_ACTION_ABORT_PREFIX: str = 'Bulk action refused, nothing was changed'

# Separator between the reasons of one refusal. A bulk action reports EVERY reason it found, so a
# caller fixes one request instead of discovering its selection's faults one element at a time
BULK_ACTION_SEPARATOR: str = ' | '
