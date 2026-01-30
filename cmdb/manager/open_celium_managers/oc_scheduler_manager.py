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
Implementation of OpenCelium SchedulerManager
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.scheduler import (
    OcSchedulerCreateError,
    OcSchedulerGetError,
    OcSchedulerUpdateError,
    OcSchedulerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

SCHEDULER_URL: str = "/scheduler"
SCHEDULERS_BY_IDS_URL: str = f"{SCHEDULER_URL}/list/get"
ALL_SCHEDULERS_URL: str = f"{SCHEDULER_URL}/all"
EXECUTE_SCHEDULER_URL: str = f"{SCHEDULER_URL}/execute"
SCHEDULER_LOGS_URL: str = "/execution/log-files"
# -------------------------------------------------------------------------------------------------------------------- #
#                                              OcSchedulerManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class OcSchedulerManager(OcBaseManager):
    """
    Manages Schedulers of OpenCelium

    Extends: OcBaseManager
    """

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_scheduler(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Creates a Scheduler in OpenCelium

        Args:
            params (dict[str, Any]): params of an OcScheduler

        Raises:
            OcSchedulerCreateError: When creating the OcScheduler failed

        Returns:
            dict[str, Any]: The created OcScheduler
        """
        create_scheduler_response: Response = self.oc_connector.oc_post(params, SCHEDULER_URL)

        if self.is_valid_response(create_scheduler_response):
            return json.loads(create_scheduler_response.text)

        LOGGER.error("[create_scheduler] OC Error: %s", create_scheduler_response.text)
        raise OcSchedulerCreateError("Failed to create the Scheduler in OpenCelium!")


    def get_schedulers_by_ids(self, scheduler_ids: list[int]) -> dict[str, Any]:
        """
        Retrieves a list of OcSchedulers with the provided 'scheduler_ids'

        Args:
            scheduler_ids (list[int]): List of scheduler_ids of OcSchedulers

        Raises:
            OcSchedulerGetError: When the scheduler_ids were not provided to this method
            OcSchedulerGetError: When the OcSchedulers could not be retrieved

        Returns:
            dict[str, Any]: The OcSchedulers with the given scheduler_ids
        """
        if not scheduler_ids:
            raise OcSchedulerGetError("No schedulerIds for Schedulers provided!")

        params: dict[str, Any] = {
            "identifiers": scheduler_ids
        }

        schedulers_response: Response = self.oc_connector.oc_post(params, SCHEDULERS_BY_IDS_URL)

        # LOGGER.debug(f"[get_schedulers_by_ids] body: {schedulers_response.text}")

        if self.is_valid_response(schedulers_response):
            return json.loads(schedulers_response.text)

        LOGGER.error("[get_schedulers_by_ids] OC Error: %s", schedulers_response.text)
        raise OcSchedulerGetError(f"Failed to retrieve OpenCelium Schedulers with IDs: {scheduler_ids}")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_scheduler(self, scheduler_id: int) -> dict[str, Any]:
        """
        Retrieves a single OcScheduler from OpenCelium

        Args:
            scheduler_id (int): schedulerId of the OcScheduler

        Raises:
            OcSchedulerGetError: When the schedulerId was not provided to this method
            OcSchedulerGetError: When the OcScheduler could not be retrieved

        Returns:
            dict[str, Any]: The retrieved OcScheduler
        """
        if not scheduler_id:
            raise OcSchedulerGetError("No schedulerId for Scheduler provided!")

        target_scheduler_response: Response = self.oc_connector.oc_get(f"{SCHEDULER_URL}/{scheduler_id}")

        if self.is_valid_response(target_scheduler_response):
            return json.loads(target_scheduler_response.text)

        LOGGER.error("[get_scheduler] OC Error: %s", target_scheduler_response.text)
        raise OcSchedulerGetError(f"Failed to retrieve OpenCelium Scheduler with ID: {scheduler_id}")


    def get_all_schedulers(self) -> list[dict[str, Any]]:
        """
        Retrieves all Schedulers from OpenCelium

        Raises:
            OcSchedulerGetError: When retrieving the OcSchedulers fails

        Returns:
            list[dict[str, Any]]: All Schedulers from OpenCelium
        """
        all_schedulers_response: Response = self.oc_connector.oc_get(ALL_SCHEDULERS_URL)

        if self.is_valid_response(all_schedulers_response):
            return json.loads(all_schedulers_response.text)

        LOGGER.error("[get_all_schedulers] OC Error: %s", all_schedulers_response.text)
        raise OcSchedulerGetError("Failed to retrieve Schedulers from OpenCelium!")


    def execute_scheduler(self, scheduler_id: int) -> bool:
        """
        Executes an OcScheduler in OpenCelium with the given scheduler_id

        Args:
            scheduler_id (int): schedulerId of the OcScheduler which should be executed

        Raises:
            OcSchedulerGetError: When the schedulerId was not provided to this method
            OcSchedulerGetError: When the OcScheduler could not be executed

        Returns:
            dict[str, Any]: The result of the OcScheduler execution
        """
        if not scheduler_id:
            raise OcSchedulerGetError("No schedulerId for Scheduler execution provided!")

        target_scheduler_response: Response = self.oc_connector.oc_get(f"{EXECUTE_SCHEDULER_URL}/{scheduler_id}")

        if self.is_valid_response(target_scheduler_response):
            return True

        LOGGER.error("[execute_scheduler] OC Error: %s", target_scheduler_response.text)
        raise OcSchedulerGetError(f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}")


    def get_scheduler_logs(self, scheduler_id: int, status: str) -> list[dict[str, Any]]:
        """
        Executes an OcScheduler in OpenCelium with the given scheduler_id

        Args:
            scheduler_id (int): schedulerId of the OcScheduler which should be executed

        Raises:
            OcSchedulerGetError: When the schedulerId was not provided to this method
            OcSchedulerGetError: When the OcScheduler could not be executed

        Returns:
            dict[str, Any]: The result of the OcScheduler execution
        """
        if not scheduler_id:
            raise OcSchedulerGetError("No schedulerId for Scheduler logs provided!")

        if not status:
            raise OcSchedulerGetError("No status for Scheduler logs provided!")

        scheduler_logs_resp: Response = self.oc_connector.oc_get(
            f"{SCHEDULER_LOGS_URL}?schedulerId={scheduler_id}&status={status}"
        )

        if self.is_valid_response(scheduler_logs_resp):
            raw_scheduler_logs = json.loads(scheduler_logs_resp.text)

            formatted_logs: list[dict[str, Any]] = []

            if raw_scheduler_logs:
                formatted_logs = [
                    self._format_scheduler_log(a_log)
                    for a_log in raw_scheduler_logs
                ]

            return formatted_logs
        LOGGER.error("[get_scheduler_logs] OC Error: %s", scheduler_logs_resp.text)
        raise OcSchedulerGetError(f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_scheduler(self, params: dict[str, Any], scheduler_id: int) -> dict[str, Any]:
        """
        Updates an OcScheduler with the given scheduler_id

        Args:
            params (dict[str, Any]): the new data of the Scheduler
            scheduler_id (int): schedulerId of the OcScheduler

        Raises:
            OcSchedulerUpdateError: When updating the Scheduler fails

        Returns:
            dict[str, Any]: The updated OcScheduler
        """
        updated_scheduler_response: Response = self.oc_connector.oc_put(params, f"{SCHEDULER_URL}/{scheduler_id}")

        if self.is_valid_response(updated_scheduler_response):
            return json.loads(updated_scheduler_response.text)

        LOGGER.error("[get_schedulers_by_ids] OC Error: %s", updated_scheduler_response.text)
        raise OcSchedulerUpdateError(f"Failed to update Scheduler with ID:{scheduler_id} in OpenCelium!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_scheduler(self, scheduler_id: int) -> bool:
        """
        Deletes a Scheduler in OpenCelium with the given scheduler_id

        Args:
            scheduler_id (int): the schedulerId of the OcScheduler which should be deleted

        Returns:
            bool: True if deletion was a success else False
        """
        delete_scheduler_response: Response = self.oc_connector.oc_delete(f"{SCHEDULER_URL}/{scheduler_id}")

        if self.is_valid_response(delete_scheduler_response):
            return True

        LOGGER.error("[delete_scheduler] OC Error: %s", delete_scheduler_response.text)
        raise OcSchedulerDeleteError(f"Failed to delete Scheduler with ID:{scheduler_id} in OpenCelium!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _format_scheduler_log(self, log: str) -> dict[str, Any]:
        """
        TODO: document
        
        expected formated string in style: "2026-01-30_12-46_734_s_892.log"

        Mapping: {date}_{hh-mm}_{connectionId}_{s/f}_{executionId}.log
        """
        # Remove file extension
        base = log.removesuffix(".log")

        try:
            date_part, time_part, connection_id, status, execution_id = base.split("_")

            # Build datetime object
            log_date = datetime.strptime(
                f"{date_part} {time_part}",
                "%Y-%m-%d %H-%M"
            ).replace(tzinfo=timezone.utc)

            return {
                "log_date": log_date,
                "connection_id": int(connection_id),
                "status": status,
                "execution_id": int(execution_id),
            }

        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid log format: {log}") from e
