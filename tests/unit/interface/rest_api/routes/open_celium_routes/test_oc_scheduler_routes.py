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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with the managers (OcSchedulerManager, OcConnectionManager,
DgServicePortalManager, CachedUserManager) patched at the route module path - no external OpenCelium
HTTP, no Mongo. The app runs on-premise (cloud_mode/local_mode False), so the cloud title-mapping /
Service-Portal branches are skipped and the local code paths are exercised. The AUTOMATIONS 403 gate
is covered by the functional automations-gating suite.

These pin the handler glue: the manager call, the success payload, the request-validation aborts
(missing connection/scheduler, duplicate connection name, missing/invalid log status, missing
scheduler) and the per-error abort mapping.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_routes import (
    create_oc_scheduler,
    get_oc_scheduler,
    get_all_oc_schedulers,
    get_oc_running_schedulers,
    get_oc_scheduler_logs,
    execute_oc_scheduler,
    update_oc_scheduler,
    delete_oc_scheduler,
)
from cmdb.errors.open_celium.scheduler import (
    OcSchedulerCreateError,
    OcSchedulerGetError,
    OcSchedulerUpdateError,
    OcSchedulerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_routes'

SCHEDULER_ID: int = 5
CONNECTION_ID: int = 10

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='db_test', email='user@test.com', public_id=1)


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (handle_oc_errors / insert_request_user / verify_api_access)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> BaseCmdbApp:
    """An on-premise BaseCmdbApp (cloud_mode/local_mode False) with a stub database_manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = False
    app.local_mode = False

    return app


@pytest.fixture(name='sched_manager')
def fixture_sched_manager() -> MagicMock:
    """The OcSchedulerManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='conn_manager')
def fixture_conn_manager() -> MagicMock:
    """The OcConnectionManager instance the create/delete handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_managers')
def fixture_patched_managers(sched_manager: MagicMock, conn_manager: MagicMock) -> Any:
    """Patches the four managers the scheduler handlers construct at the route module path."""
    with patch(f'{ROUTE_PATH}.OcSchedulerManager', return_value=sched_manager), \
         patch(f'{ROUTE_PATH}.OcConnectionManager', return_value=conn_manager), \
         patch(f'{ROUTE_PATH}.DgServicePortalManager', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.CachedUserManager', return_value=MagicMock()):
        yield


# --------------------------------------------------- create_oc_scheduler -------------------------------------------- #

class TestCreateOcScheduler:
    """``create_oc_scheduler`` creates the connection then the scheduler."""

    def test_creates_and_returns_scheduler(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """A valid payload creates the connection and scheduler and returns the scheduler."""
        del patched_managers
        conn_manager.check_connection_name_exists.return_value = False
        conn_manager.create_connection.return_value = {'connectionId': CONNECTION_ID}
        sched_manager.create_scheduler.return_value = {'schedulerId': SCHEDULER_ID, 'title': 'sched'}

        body = {'connection': {'title': 'conn'}, 'scheduler': {'title': 'sched'}}
        with flask_app.test_request_context(json=body):
            response = _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        sched_manager.create_scheduler.assert_called_once()

    def test_missing_connection_returns_400(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """A payload without 'connection' data aborts with 400."""
        del patched_managers, sched_manager, conn_manager

        with flask_app.test_request_context(json={'scheduler': {'title': 'sched'}}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_missing_scheduler_returns_400(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """A payload without 'scheduler' data aborts with 400."""
        del patched_managers, sched_manager, conn_manager

        with flask_app.test_request_context(json={'connection': {'title': 'conn'}}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_duplicate_connection_name_returns_400(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An existing connection name aborts with 400 before creating anything."""
        del patched_managers, sched_manager
        conn_manager.check_connection_name_exists.return_value = True

        body = {'connection': {'title': 'conn'}, 'scheduler': {'title': 'sched'}}
        with flask_app.test_request_context(json=body):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        conn_manager.create_connection.assert_not_called()

    def test_scheduler_create_error_returns_500(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An OcSchedulerCreateError maps to 500."""
        del patched_managers
        conn_manager.check_connection_name_exists.return_value = False
        conn_manager.create_connection.return_value = {'connectionId': CONNECTION_ID}
        sched_manager.create_scheduler.side_effect = OcSchedulerCreateError('boom')

        body = {'connection': {'title': 'conn'}, 'scheduler': {'title': 'sched'}}
        with flask_app.test_request_context(json=body):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------------- get_oc_scheduler --------------------------------------------- #

class TestGetOcScheduler:
    """``get_oc_scheduler`` returns the scheduler (no cloud validation on-premise)."""

    def test_returns_scheduler(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """The manager's scheduler is returned with 200."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler.return_value = {'schedulerId': SCHEDULER_ID}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        sched_manager.get_scheduler.assert_called_once_with(SCHEDULER_ID)

    def test_get_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerGetError maps to 500."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler.side_effect = OcSchedulerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- get_all_oc_schedulers ------------------------------------------ #

class TestGetAllOcSchedulers:
    """``get_all_oc_schedulers`` returns all schedulers (local mode)."""

    def test_returns_all_schedulers(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """The local get_all_schedulers result is returned with 200."""
        del patched_managers, conn_manager
        sched_manager.get_all_schedulers.return_value = [{'schedulerId': SCHEDULER_ID}]

        with flask_app.test_request_context():
            response = _unwrap(get_all_oc_schedulers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        sched_manager.get_all_schedulers.assert_called_once_with()

    def test_get_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerGetError maps to 500."""
        del patched_managers, conn_manager
        sched_manager.get_all_schedulers.side_effect = OcSchedulerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_schedulers)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ get_oc_running_schedulers ----------------------------------------- #

class TestGetOcRunningSchedulers:
    """``get_oc_running_schedulers`` returns the running schedulers."""

    def test_returns_running_schedulers(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """The running schedulers are returned with 200."""
        del patched_managers, conn_manager
        sched_manager.get_running_schedulers.return_value = [{'schedulerId': SCHEDULER_ID}]

        with flask_app.test_request_context():
            response = _unwrap(get_oc_running_schedulers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        sched_manager.get_running_schedulers.assert_called_once_with()

    def test_get_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerGetError maps to 500."""
        del patched_managers, conn_manager
        sched_manager.get_running_schedulers.side_effect = OcSchedulerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_running_schedulers)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------- get_oc_scheduler_logs ------------------------------------------- #

class TestGetOcSchedulerLogs:
    """``get_oc_scheduler_logs`` validates the query params, then returns the logs."""

    def test_returns_logs(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """Valid scheduler_id + status returns the logs with 200."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler_logs.return_value = [{'status': 's'}]

        with flask_app.test_request_context(f'/schedulers/logs?scheduler_id={SCHEDULER_ID}&status=s'):
            response = _unwrap(get_oc_scheduler_logs)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        sched_manager.get_scheduler_logs.assert_called_once_with(SCHEDULER_ID, 's')

    def test_missing_scheduler_id_returns_400(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """A missing scheduler_id query param aborts with 400."""
        del patched_managers, sched_manager, conn_manager

        with flask_app.test_request_context('/schedulers/logs?status=s'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler_logs)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_missing_status_returns_400(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """A missing status query param aborts with 400."""
        del patched_managers, sched_manager, conn_manager

        with flask_app.test_request_context(f'/schedulers/logs?scheduler_id={SCHEDULER_ID}'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler_logs)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_invalid_status_returns_400(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """A status other than 's'/'f' aborts with 400."""
        del patched_managers, sched_manager, conn_manager

        with flask_app.test_request_context(f'/schedulers/logs?scheduler_id={SCHEDULER_ID}&status=x'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler_logs)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# --------------------------------------------------- execute_oc_scheduler ------------------------------------------- #

class TestExecuteOcScheduler:
    """``execute_oc_scheduler`` runs the scheduler (no cloud validation on-premise)."""

    def test_returns_execution_result(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """The execution result is returned with 200."""
        del patched_managers, conn_manager
        sched_manager.execute_scheduler.return_value = {'status': 'started'}

        with flask_app.test_request_context():
            response = _unwrap(execute_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        sched_manager.execute_scheduler.assert_called_once_with(SCHEDULER_ID)

    def test_execute_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerGetError maps to 500."""
        del patched_managers, conn_manager
        sched_manager.execute_scheduler.side_effect = OcSchedulerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(execute_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- update_oc_scheduler -------------------------------------------- #

class TestUpdateOcScheduler:
    """``update_oc_scheduler`` forwards the payload to the manager (local mode)."""

    def test_updates_and_returns_scheduler(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """The updated scheduler is returned with 200."""
        del patched_managers, conn_manager
        sched_manager.update_scheduler.return_value = {'schedulerId': SCHEDULER_ID, 'title': 'renamed'}

        with flask_app.test_request_context(json={'title': 'renamed'}):
            response = _unwrap(update_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        sched_manager.update_scheduler.assert_called_once_with({'title': 'renamed'}, SCHEDULER_ID)

    def test_update_error_returns_400(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerUpdateError maps to 400."""
        del patched_managers, conn_manager
        sched_manager.update_scheduler.side_effect = OcSchedulerUpdateError('boom')

        with flask_app.test_request_context(json={'title': 'renamed'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# --------------------------------------------------- delete_oc_scheduler -------------------------------------------- #

class TestDeleteOcScheduler:
    """``delete_oc_scheduler`` fetches the scheduler, then deletes it and its connection."""

    def test_deletes_and_returns_result(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """A located scheduler is deleted (with its connection) and the result is returned."""
        del patched_managers
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}
        sched_manager.delete_scheduler.return_value = True

        with flask_app.test_request_context():
            response = _unwrap(delete_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        sched_manager.delete_scheduler.assert_called_once_with(SCHEDULER_ID)
        conn_manager.delete_connection.assert_called_once_with(CONNECTION_ID)

    def test_missing_scheduler_returns_400(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """A scheduler that does not exist aborts with 400 before any deletion."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler.return_value = None

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.delete_scheduler.assert_not_called()

    def test_delete_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerDeleteError maps to 500."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}
        sched_manager.delete_scheduler.side_effect = OcSchedulerDeleteError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
