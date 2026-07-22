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
Unit tests for cmdb.manager.open_celium_managers.oc_scheduler_manager.OcSchedulerManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each test stubs the connector verb with a fake response and asserts
the endpoint + payload, the parsed 2xx body, the id/status guards, the scheduler-log formatting, and
the per-operation OC error on a non-2xx response. The ``_format_scheduler_log`` helper (real parsing
logic) is tested directly. No HTTP, no Mongo.
"""
# pylint: disable=protected-access
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_scheduler_manager import (
    OcSchedulerManager,
    SCHEDULER_URL,
    SCHEDULERS_BY_IDS_URL,
    ALL_SCHEDULERS_URL,
    EXECUTE_SCHEDULER_URL,
    SCHEDULER_LOGS_URL,
    RUNNING_SCHEDULERS_URL,
)
from cmdb.errors.open_celium.scheduler import (
    OcSchedulerCreateError,
    OcSchedulerGetError,
    OcSchedulerUpdateError,
    OcSchedulerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

SCHEDULER_ID: int = 5
LOG_STATUS: str = 's'

# A scheduler log filename: {date}_{hh-mm}_{connectionId}_{s/f}_{executionId}.log
LOG_FILENAME: str = '2026-01-30_12-46_734_s_892.log'
LOG_CONNECTION_ID: int = 734
LOG_EXECUTION_ID: int = 892

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='scheduler_manager')
def fixture_scheduler_manager() -> OcSchedulerManager:
    """An OcSchedulerManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcSchedulerManager(MagicMock(), 'db_test')


# ---------------------------------------------------- create_scheduler ---------------------------------------------- #

class TestCreateScheduler:
    """``create_scheduler`` POSTs to /scheduler."""

    def test_posts_and_returns_created(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body is parsed and returned; the payload hits the scheduler endpoint."""
        scheduler_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'schedulerId': SCHEDULER_ID})

        result = scheduler_manager.create_scheduler({'title': 'sched'})

        assert result == {'schedulerId': SCHEDULER_ID}
        scheduler_manager.oc_connector.oc_post.assert_called_once_with({'title': 'sched'}, SCHEDULER_URL)

    def test_non_2xx_raises_create_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerCreateError."""
        scheduler_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerCreateError):
            scheduler_manager.create_scheduler({'title': 'sched'})


# ------------------------------------------------- get_schedulers_by_ids -------------------------------------------- #

class TestGetSchedulersByIds:
    """``get_schedulers_by_ids`` POSTs the id list and guards an empty list."""

    def test_empty_ids_raises_without_http(self, scheduler_manager: OcSchedulerManager) -> None:
        """An empty id list raises OcSchedulerGetError before any HTTP call."""
        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_schedulers_by_ids([])

        scheduler_manager.oc_connector.oc_post.assert_not_called()

    def test_posts_identifiers_and_returns_body(self, scheduler_manager: OcSchedulerManager) -> None:
        """The ids are sent under 'identifiers' to the by-ids endpoint and the body is returned."""
        scheduler_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, [{'schedulerId': SCHEDULER_ID}])

        result = scheduler_manager.get_schedulers_by_ids([SCHEDULER_ID])

        assert result == [{'schedulerId': SCHEDULER_ID}]
        scheduler_manager.oc_connector.oc_post.assert_called_once_with(
            {'identifiers': [SCHEDULER_ID]}, SCHEDULERS_BY_IDS_URL
        )

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_schedulers_by_ids([SCHEDULER_ID])


# ----------------------------------------------------- get_scheduler ------------------------------------------------ #

class TestGetScheduler:
    """``get_scheduler`` GETs /scheduler/<id> and guards a falsy id."""

    def test_falsy_id_raises_without_http(self, scheduler_manager: OcSchedulerManager) -> None:
        """A falsy scheduler id raises OcSchedulerGetError before any HTTP call."""
        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_scheduler(0)

        scheduler_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_and_returns_body(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body is parsed and returned from /scheduler/<id>."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'schedulerId': SCHEDULER_ID})

        result = scheduler_manager.get_scheduler(SCHEDULER_ID)

        assert result == {'schedulerId': SCHEDULER_ID}
        scheduler_manager.oc_connector.oc_get.assert_called_once_with(f"{SCHEDULER_URL}/{SCHEDULER_ID}")

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_scheduler(SCHEDULER_ID)


# ------------------------------------------------- get_running_schedulers ------------------------------------------- #

class TestGetRunningSchedulers:
    """``get_running_schedulers`` GETs the running-all endpoint."""

    def test_returns_running(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body is parsed and returned from the running endpoint."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'schedulerId': SCHEDULER_ID}])

        result = scheduler_manager.get_running_schedulers()

        assert result == [{'schedulerId': SCHEDULER_ID}]
        scheduler_manager.oc_connector.oc_get.assert_called_once_with(RUNNING_SCHEDULERS_URL)

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_running_schedulers()


# --------------------------------------------------- get_all_schedulers --------------------------------------------- #

class TestGetAllSchedulers:
    """``get_all_schedulers`` GETs /scheduler/all."""

    def test_returns_all(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body is parsed and returned from the all-schedulers endpoint."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'schedulerId': SCHEDULER_ID}])

        result = scheduler_manager.get_all_schedulers()

        assert result == [{'schedulerId': SCHEDULER_ID}]
        scheduler_manager.oc_connector.oc_get.assert_called_once_with(ALL_SCHEDULERS_URL)

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_all_schedulers()


# ---------------------------------------------------- execute_scheduler --------------------------------------------- #

class TestExecuteScheduler:
    """``execute_scheduler`` GETs the execute endpoint and returns True on success."""

    def test_falsy_id_raises_without_http(self, scheduler_manager: OcSchedulerManager) -> None:
        """A falsy scheduler id raises OcSchedulerGetError before any HTTP call."""
        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.execute_scheduler(0)

        scheduler_manager.oc_connector.oc_get.assert_not_called()

    def test_2xx_returns_true(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx execute returns True."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS)

        assert scheduler_manager.execute_scheduler(SCHEDULER_ID) is True
        scheduler_manager.oc_connector.oc_get.assert_called_once_with(f"{EXECUTE_SCHEDULER_URL}/{SCHEDULER_ID}")

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.execute_scheduler(SCHEDULER_ID)


# --------------------------------------------------- get_scheduler_logs --------------------------------------------- #

class TestGetSchedulerLogs:
    """``get_scheduler_logs`` validates the args, then formats the returned log filenames."""

    def test_missing_id_raises_without_http(self, scheduler_manager: OcSchedulerManager) -> None:
        """A falsy scheduler id raises OcSchedulerGetError before any HTTP call."""
        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_scheduler_logs(0, LOG_STATUS)

        scheduler_manager.oc_connector.oc_get.assert_not_called()

    def test_missing_status_raises_without_http(self, scheduler_manager: OcSchedulerManager) -> None:
        """A falsy status raises OcSchedulerGetError before any HTTP call."""
        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_scheduler_logs(SCHEDULER_ID, '')

        scheduler_manager.oc_connector.oc_get.assert_not_called()

    def test_formats_returned_logs(self, scheduler_manager: OcSchedulerManager) -> None:
        """Each returned log filename is parsed into its structured fields."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'result': [LOG_FILENAME]})

        result = scheduler_manager.get_scheduler_logs(SCHEDULER_ID, LOG_STATUS)

        assert result == [{
            'log_date': datetime(2026, 1, 30, 12, 46, tzinfo=timezone.utc),
            'connection_id': LOG_CONNECTION_ID,
            'status': LOG_STATUS,
            'execution_id': LOG_EXECUTION_ID,
        }]
        scheduler_manager.oc_connector.oc_get.assert_called_once_with(
            f"{SCHEDULER_LOGS_URL}?schedulerId={SCHEDULER_ID}&status={LOG_STATUS}"
        )

    def test_empty_result_returns_empty_list(self, scheduler_manager: OcSchedulerManager) -> None:
        """A null/empty 'result' yields an empty list."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'result': None})

        assert scheduler_manager.get_scheduler_logs(SCHEDULER_ID, LOG_STATUS) == []

    def test_missing_result_key_returns_empty_list(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body without a 'result' key returns [] instead of raising KeyError (uses .get)."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {})

        assert scheduler_manager.get_scheduler_logs(SCHEDULER_ID, LOG_STATUS) == []

    def test_non_2xx_raises_get_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerGetError."""
        scheduler_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerGetError):
            scheduler_manager.get_scheduler_logs(SCHEDULER_ID, LOG_STATUS)


# ---------------------------------------------------- update_scheduler ---------------------------------------------- #

class TestUpdateScheduler:
    """``update_scheduler`` PUTs to /scheduler/<id>."""

    def test_puts_and_returns_body(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx body is parsed and returned from the PUT."""
        scheduler_manager.oc_connector.oc_put.return_value = _response(OK_STATUS, {'schedulerId': SCHEDULER_ID})

        result = scheduler_manager.update_scheduler({'title': 'renamed'}, SCHEDULER_ID)

        assert result == {'schedulerId': SCHEDULER_ID}
        scheduler_manager.oc_connector.oc_put.assert_called_once_with(
            {'title': 'renamed'}, f"{SCHEDULER_URL}/{SCHEDULER_ID}"
        )

    def test_non_2xx_raises_update_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx response raises OcSchedulerUpdateError."""
        scheduler_manager.oc_connector.oc_put.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerUpdateError):
            scheduler_manager.update_scheduler({'title': 'renamed'}, SCHEDULER_ID)


# ---------------------------------------------------- delete_scheduler ---------------------------------------------- #

class TestDeleteScheduler:
    """``delete_scheduler`` returns True on success and RAISES (not False) on failure."""

    def test_2xx_returns_true(self, scheduler_manager: OcSchedulerManager) -> None:
        """A 2xx delete returns True."""
        scheduler_manager.oc_connector.oc_delete.return_value = _response(OK_STATUS)

        assert scheduler_manager.delete_scheduler(SCHEDULER_ID) is True
        scheduler_manager.oc_connector.oc_delete.assert_called_once_with(f"{SCHEDULER_URL}/{SCHEDULER_ID}")

    def test_non_2xx_raises_delete_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A non-2xx delete raises OcSchedulerDeleteError (unlike connection/connector delete)."""
        scheduler_manager.oc_connector.oc_delete.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcSchedulerDeleteError):
            scheduler_manager.delete_scheduler(SCHEDULER_ID)


# -------------------------------------------------- _format_scheduler_log ------------------------------------------- #

class TestFormatSchedulerLog:
    """``_format_scheduler_log`` parses the OC log filename into structured fields."""

    def test_parses_valid_filename(self, scheduler_manager: OcSchedulerManager) -> None:
        """A well-formed filename is split into date, connection id, status and execution id."""
        result = scheduler_manager._format_scheduler_log(LOG_FILENAME)

        assert result == {
            'log_date': datetime(2026, 1, 30, 12, 46, tzinfo=timezone.utc),
            'connection_id': LOG_CONNECTION_ID,
            'status': LOG_STATUS,
            'execution_id': LOG_EXECUTION_ID,
        }

    def test_invalid_filename_raises_value_error(self, scheduler_manager: OcSchedulerManager) -> None:
        """A filename that does not match the expected shape raises ValueError."""
        with pytest.raises(ValueError):
            scheduler_manager._format_scheduler_log('not-a-valid-log.log')
