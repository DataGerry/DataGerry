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
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

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
RUNNING_SCHEDULERS_URL: str = f"{SCHEDULER_URL}/running/all"
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
        return self.parse_response(
            self.oc_connector.oc_post(params, SCHEDULER_URL),
            OcSchedulerCreateError,
            "Failed to create the Scheduler in OpenCelium!",
        )


    def get_schedulers_by_ids(self, scheduler_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves a list of OcSchedulers with the provided 'scheduler_ids'

        Args:
            scheduler_ids (list[int]): List of scheduler_ids of OcSchedulers

        Raises:
            OcSchedulerGetError: When the scheduler_ids were not provided to this method
            OcSchedulerGetError: When the OcSchedulers could not be retrieved

        Returns:
            list[dict[str, Any]]: The OcSchedulers with the given scheduler_ids
        """
        if not scheduler_ids:
            raise OcSchedulerGetError("No schedulerIds for Schedulers provided!")

        params: dict[str, Any] = {
            "identifiers": scheduler_ids
        }

        return self.parse_response(
            self.oc_connector.oc_post(params, SCHEDULERS_BY_IDS_URL),
            OcSchedulerGetError,
            f"Failed to retrieve OpenCelium Schedulers with IDs: {scheduler_ids}",
        )

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

        return self.parse_response(
            self.oc_connector.oc_get(f"{SCHEDULER_URL}/{scheduler_id}"),
            OcSchedulerGetError,
            f"Failed to retrieve OpenCelium Scheduler with ID: {scheduler_id}",
        )


    def get_running_schedulers(self) -> list[dict[str, Any]]:
        """
        Retrieves all running schedulers

        Raises:
            OcSchedulerGetError: When the OcScheduler could not be retrieved

        Returns:
            list[dict[str, Any]]: All running schedulers
        """
        return self.parse_response(
            self.oc_connector.oc_get(RUNNING_SCHEDULERS_URL),
            OcSchedulerGetError,
            "Failed to retrieve currently running Schedulers!",
        )


    def get_all_schedulers(self) -> list[dict[str, Any]]:
        """
        Retrieves all Schedulers from OpenCelium

        Raises:
            OcSchedulerGetError: When retrieving the OcSchedulers fails

        Returns:
            list[dict[str, Any]]: All Schedulers from OpenCelium
        """
        return self.parse_response(
            self.oc_connector.oc_get(ALL_SCHEDULERS_URL),
            OcSchedulerGetError,
            "Failed to retrieve Schedulers from OpenCelium!",
        )


    def execute_scheduler(self, scheduler_id: int) -> bool:
        """
        Executes an OcScheduler in OpenCelium with the given scheduler_id

        Args:
            scheduler_id (int): schedulerId of the OcScheduler which should be executed

        Raises:
            OcSchedulerGetError: When the schedulerId was not provided to this method
            OcSchedulerGetError: When the OcScheduler could not be executed

        Returns:
            bool: True if the execution was triggered successfully
        """
        if not scheduler_id:
            raise OcSchedulerGetError("No schedulerId for Scheduler execution provided!")

        if self.is_valid_response(self.oc_connector.oc_get(f"{EXECUTE_SCHEDULER_URL}/{scheduler_id}")):
            return True

        raise OcSchedulerGetError(f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}")


    def get_scheduler_logs(self, scheduler_id: int, status: str) -> list[dict[str, Any]]:
        """
        Retrieves the execution logs of an OcScheduler with the given scheduler_id

        Args:
            scheduler_id (int): schedulerId of the OcScheduler whose logs are retrieved
            status (str): log status filter ('s' for success, 'f' for failed)

        Raises:
            OcSchedulerGetError: When the schedulerId or status was not provided to this method
            OcSchedulerGetError: When the OcScheduler logs could not be retrieved

        Returns:
            list[dict[str, Any]]: The formatted scheduler execution logs
        """
        if not scheduler_id:
            raise OcSchedulerGetError("No schedulerId for Scheduler logs provided!")

        if not status:
            raise OcSchedulerGetError("No status for Scheduler logs provided!")

        scheduler_logs = self.parse_response(
            self.oc_connector.oc_get(f"{SCHEDULER_LOGS_URL}?schedulerId={scheduler_id}&status={status}"),
            OcSchedulerGetError,
            f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}",
        )

        raw_scheduler_logs = scheduler_logs.get('result')

        if not raw_scheduler_logs:
            return []

        return [self._format_scheduler_log(a_log) for a_log in raw_scheduler_logs]

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
        return self.parse_response(
            self.oc_connector.oc_put(params, f"{SCHEDULER_URL}/{scheduler_id}"),
            OcSchedulerUpdateError,
            f"Failed to update Scheduler with ID:{scheduler_id} in OpenCelium!",
        )

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_scheduler(self, scheduler_id: int) -> bool:
        """
        Deletes a Scheduler in OpenCelium with the given scheduler_id

        Args:
            scheduler_id (int): the schedulerId of the OcScheduler which should be deleted

        Raises:
            OcSchedulerDeleteError: When the deletion failed (non-2xx response from OpenCelium)

        Returns:
            bool: True if deletion was a success
        """
        if self.is_valid_response(self.oc_connector.oc_delete(f"{SCHEDULER_URL}/{scheduler_id}")):
            return True

        raise OcSchedulerDeleteError(f"Failed to delete Scheduler with ID:{scheduler_id} in OpenCelium!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _format_scheduler_log(self, log: str) -> dict[str, Any]:
        """
        Parses an OpenCelium log-file name into a structured log entry

        Expects a file name of the form ``{date}_{hh-mm}_{connectionId}_{s/f}_{executionId}.log``
        (e.g. ``2026-01-30_12-46_734_s_892.log``) and returns its parts as a dict.

        Args:
            log (str): The log-file name to parse

        Raises:
            ValueError: When the log-file name does not match the expected format

        Returns:
            dict[str, Any]: The parsed log entry (log_date, connection_id, status, execution_id)
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
