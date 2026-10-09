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
Shared constants for the OpenCelium REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class OcResponseKey(BaseStrEnum):
    """Keys of an OpenCelium API response object consumed by the OpenCelium routes"""
    TITLE = 'title'
    CONNECTION = 'connection'
    CONNECTION_ID = 'connectionId'
    CONNECTOR_ID = 'connectorId'
    SCHEDULER = 'scheduler'
    SCHEDULER_ID = 'schedulerId'
    FROM_CONNECTOR = 'fromConnector'
    TO_CONNECTOR = 'toConnector'
    PASSWORD = 'password'
    #: The invoker block of a connector - its NAME is what identifies a DataGerry template
    INVOKER = 'invoker'
    NAME = 'name'
    #: Carried by a flowchart of an execution log; rewritten in cloud mode so the tenant prefix
    #: never reaches a client (see oc_connection_log_helper)
    CONNECTOR_NAME = 'connectorName'


class OcLogQueryParam(BaseStrEnum):
    """
    Query parameters the OpenCelium execution-log routes read

    OpenCelium's own spellings (camelCase), which is why they are named here rather than left as
    literals: the routes forward them to OpenCelium unchanged, so a typo would answer 400 for a
    parameter the caller did send
    """
    LOOP_INDEX = 'loopIndex'
    CONNECTION_ID = 'connectionId'
    SCHEDULER_ID = 'schedulerId'
    STATUS = 'status'


class OcRight(BaseStrEnum):
    """
    The rights the OpenCelium routes ask for

    Two families exist: connectors (``OcConnectorRight``) and connections (``OcConnectionRight``). An Automation is
    a connection and its scheduler, created and deleted together, so every Automation surface - schedulers, their
    execution logs and the templates the editor saves - asks for the connection right of the same operation, the
    rights the frontend's automation screens are guarded by. The invokers are connector material (the automation
    form loads them together with the connectors), and OpenCelium's own licence is read from the automations list
    """
    CONNECTOR_VIEW = 'base.openCelium.connector.view'
    CONNECTOR_ADD = 'base.openCelium.connector.add'
    CONNECTOR_EDIT = 'base.openCelium.connector.edit'
    CONNECTOR_DELETE = 'base.openCelium.connector.delete'
    CONNECTION_VIEW = 'base.openCelium.connection.view'
    CONNECTION_ADD = 'base.openCelium.connection.add'
    CONNECTION_EDIT = 'base.openCelium.connection.edit'
    CONNECTION_DELETE = 'base.openCelium.connection.delete'


# HTTP request header carrying the OpenCelium master password
MASTER_PW_HEADER: str = 'X-Master-Password'


class OcAutomationMessage(BaseStrEnum):
    """
    What the Automation create and update answer when their body is incomplete, a step fails or an undo cannot
    finish

    RESIDUE is formatted with ``residue``: the remote objects the undo could not remove
    """
    NO_CONNECTION_TITLE = "No 'connection.title' provided to create the Automation!"
    NO_SCHEDULER_TITLE = "No 'scheduler.title' provided to create the Automation!"
    PORTAL_REFUSED = "Failed to register the Automation with the Service Portal!"
    RESIDUE = "The Automation could not be created, and its undo left these behind: {residue}"
    UPDATE_BODY_NOT_AN_OBJECT = "The Automation update must be a JSON object!"
    UPDATE_TITLE_INVALID = "The Automation's 'title' must be a non-blank text!"


# The `collection` a remote write is recorded under in the WriteLedger: the service it lives in, as the residue
# names it
OPEN_CELIUM_SERVICE: str = 'OpenCelium'
SERVICE_PORTAL: str = 'DataGerry Service Portal'
