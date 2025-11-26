# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of OpenCelium ConnectionLogManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.connection_log import OcConnectionLogGetError, OcConnectionLogDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

EXECUTION_URL: str = "/execution"
EXECUTION_LOG_LIST_URL: str = f"{EXECUTION_URL}/log-files"
EXECUTION_LOG_URL: str = f"{EXECUTION_URL}/log/element"


# -------------------------------------------------------------------------------------------------------------------- #
#                                            OcConnectionLogManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class OcConnectionLogManager(OcBaseManager):
    """
    Manages COnnection Logs of OpenCelium
    """

# --------------------------------------------------- GET - ROUTES --------------------------------------------------- #

    def get_details_method_or_operator(self, target_id: int) -> dict[str, Any]:
        """
        Retrieves details of Method or Operator

        Args:
            target_id (int): ID of method or operator
        Raises:
            OcConnectionLogGetError: When the Method/Operator could not be retrieved

        Returns:
            dict[str, Any]: The retrieved details of Method or Operator
        """
        target_connection_response: Response = self.oc_connector.oc_get(f"{EXECUTION_LOG_URL}/{target_id}/details")

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        raise OcConnectionLogGetError(f"Failed to retrieve Method/Operator with ID: {target_id}")


    def get_operator_children(self, target_id: int, loop_index: int) -> dict[str, Any]:
        """
        Retrieves Operator children

        Args:
            target_id (int): ID of operator
            loop_index (int): the index
        Raises:
            OcConnectionLogGetError: When the Operator children could not be retrieved

        Returns:
            dict[str, Any]: The retrieved children of the Operator
        """
        target_connection_response: Response = self.oc_connector.oc_get(
            f"{EXECUTION_LOG_URL}/{target_id}/children?loopIndex={loop_index}"
        )

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        raise OcConnectionLogGetError("Failed to retrieve Operator children!")


    def get_flowcharts(self, execution_id: int) -> dict[str, Any]:
        """
        Retrieves a Flowchart for an execution

        Args:
            execution_id (int): executionId of the Automation

        Raises:
            OcConnectionLogGetError: When the Flowcharts could not be retrieved

        Returns:
            dict[str, Any]: The retrieved flowcharts
        """
        target_connection_response: Response = self.oc_connector.oc_get(f"{EXECUTION_LOG_URL}/{execution_id}/children")

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        raise OcConnectionLogGetError(f"Failed to retrieve Flowcharts of Execution ID: {execution_id}")


    def get_first_level_logs(self, flowchart_id: int) -> dict[str, Any]:
        """
        Retrieves first level Logs

        Args:
            flowchart_id (int): flowchartId

        Raises:
            OcConnectionLogGetError: When the first level Logs could not be retrieved

        Returns:
            dict[str, Any]: The retrieved first level logs
        """
        target_connection_response: Response = self.oc_connector.oc_get(f"{EXECUTION_LOG_URL}/{flowchart_id}/children")

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        raise OcConnectionLogGetError(f"Failed to retrieve first level Logs of Execution ID: {flowchart_id}")


    def get_log_list(self, connection_id: int, scheduler_id: int, status: Any) -> dict[str, Any]:
        """
        Retrieves Operator children

        Args:
            connection_id (int): ID of Connection
            scheduler_id (int): ID of Scheduler
            status (Any): the status
        Raises:
            OcConnectionLogGetError: When the Operator children could not be retrieved

        Returns:
            dict[str, Any]: The retrieved children of the Operator
        """
        target_connection_response: Response = self.oc_connector.oc_get(
            f"{EXECUTION_LOG_LIST_URL}?connectionId={connection_id}&schedulerId={scheduler_id}&status={status}"
        )

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        raise OcConnectionLogGetError("Failed to retrieve Operator children!")

# -------------------------------------------------- DELETE - ROUTES ------------------------------------------------- #

    def delete_logs(self, execution_id: int) -> bool:
        """
        Deletes Logs of an Automation execution

        Args:
            execution_id (int): the executionId

        Returns:
            bool: True if deletion was a success else False
        """
        delete_connection_response: Response = self.oc_connector.oc_delete(f"{EXECUTION_URL}/{execution_id}")

        if self.is_valid_response(delete_connection_response):
            return True

        raise OcConnectionLogDeleteError("Failed to delete Logs!")
