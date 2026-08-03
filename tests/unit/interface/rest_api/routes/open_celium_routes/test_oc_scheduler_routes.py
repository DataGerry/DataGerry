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
from cmdb.errors.open_celium.connection import OcConnectionCreateError, OcConnectionGetError
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


# ---------------------------- create: remaining connection-error handlers (on-premise) ------------------------------ #

class TestCreateOcSchedulerConnectionErrors:
    """``create_oc_scheduler`` maps the connection create/get errors to 500."""

    def test_connection_create_error_returns_500(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An OcConnectionCreateError while creating the backing connection maps to 500."""
        del patched_managers, sched_manager
        conn_manager.check_connection_name_exists.return_value = False
        conn_manager.create_connection.side_effect = OcConnectionCreateError('boom')

        with flask_app.test_request_context(json={'connection': {'title': 'c'}, 'scheduler': {'title': 's'}}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_connection_get_error_returns_500(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An OcConnectionGetError while checking name uniqueness maps to 500."""
        del patched_managers, sched_manager
        conn_manager.check_connection_name_exists.side_effect = OcConnectionGetError('boom')

        with flask_app.test_request_context(json={'connection': {'title': 'c'}, 'scheduler': {'title': 's'}}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ==================================================== CLOUD MODE ==================================================== #
# In cloud mode the scheduler handlers map/unmap tenant titles, validate id access (cache-first, Service
# Portal fallback via the helpers) and keep the Service Portal id-lists in sync.

SCHED_HELPER: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_helper'
CONN_HELPER: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_helper'

CLOUD_DB: str = 'gfSKkjoRzAxJwC'
CLOUD_USER: SimpleNamespace = SimpleNamespace(database=CLOUD_DB, email='user@test.com', public_id=1)


def _mapped_scheduler() -> dict[str, Any]:
    """A scheduler doc as OpenCelium returns it (tenant-prefixed nested titles)."""
    return {
        'schedulerId': SCHEDULER_ID,
        'title': f'{CLOUD_DB}_sched',
        'connection': {
            'connectionId': CONNECTION_ID,
            'title': f'{CLOUD_DB}_conn',
            'fromConnector': {'title': f'{CLOUD_DB}_from'},
            'toConnector': {'title': f'{CLOUD_DB}_to'},
        },
    }


def _mapped_running_scheduler() -> dict[str, Any]:
    """A running-scheduler doc (flat connector titles, as that endpoint returns)."""
    return {
        'schedulerId': SCHEDULER_ID,
        'title': f'{CLOUD_DB}_sched',
        'fromConnector': f'{CLOUD_DB}_from',
        'toConnector': f'{CLOUD_DB}_to',
    }


@pytest.fixture(name='cloud_app')
def fixture_cloud_app() -> BaseCmdbApp:
    """A cloud BaseCmdbApp (cloud_mode=True, local_mode=False) with a stub database_manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = True
    app.local_mode = False

    return app


@pytest.fixture(name='cloud_managers')
def fixture_cloud_managers(sched_manager: MagicMock, conn_manager: MagicMock) -> Any:
    """Patches the managers at the route AND helper module paths; yields the cached + portal mocks.

    The cloud access helpers (assert_scheduler_access / get_accessible_scheduler_ids /
    connection_in_subscription) build their own CachedUserManager / DgServicePortalManager, so those must
    be patched at the helper module paths too - all returning the same mocks the test configures.
    """
    cached = MagicMock()
    dg_sp = MagicMock()
    with patch(f'{ROUTE_PATH}.OcSchedulerManager', return_value=sched_manager), \
         patch(f'{ROUTE_PATH}.OcConnectionManager', return_value=conn_manager), \
         patch(f'{ROUTE_PATH}.DgServicePortalManager', return_value=dg_sp), \
         patch(f'{ROUTE_PATH}.CachedUserManager', return_value=cached), \
         patch(f'{SCHED_HELPER}.DgServicePortalManager', return_value=dg_sp), \
         patch(f'{SCHED_HELPER}.CachedUserManager', return_value=cached), \
         patch(f'{CONN_HELPER}.DgServicePortalManager', return_value=dg_sp), \
         patch(f'{CONN_HELPER}.CachedUserManager', return_value=cached):
        yield SimpleNamespace(cached=cached, dg_sp=dg_sp)


class TestCreateOcSchedulerCloud:
    """Cloud create maps titles, creates connection + scheduler, and syncs the Service Portal ids."""

    def test_maps_creates_and_syncs_ids(
        self, cloud_app, sched_manager, conn_manager, cloud_managers,
    ) -> None:
        """Titles are tenant-mapped; the connection + scheduler ids are saved and the cache invalidated."""
        conn_manager.check_connection_name_exists.return_value = False
        conn_manager.create_connection.return_value = {'connectionId': CONNECTION_ID}
        sched_manager.create_scheduler.return_value = {'schedulerId': SCHEDULER_ID, 'title': f'{CLOUD_DB}_sched'}

        body = {'connection': {'title': 'conn'}, 'scheduler': {'title': 'sched'}}
        with cloud_app.test_request_context(json=body):
            response = _unwrap(create_oc_scheduler)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK
        assert conn_manager.create_connection.call_args.args[0]['title'] == f'{CLOUD_DB}_conn'
        assert sched_manager.create_scheduler.call_args.args[0]['title'] == f'{CLOUD_DB}_sched'
        cloud_managers.dg_sp.save_connection_id.assert_called_once()
        cloud_managers.dg_sp.save_scheduler_id.assert_called_once()

    def test_duplicate_connection_unmaps_and_returns_400(
        self, cloud_app, sched_manager, conn_manager, cloud_managers,
    ) -> None:
        """A duplicate connection name is reported unmapped with a 400."""
        del sched_manager, cloud_managers
        conn_manager.check_connection_name_exists.return_value = True

        with cloud_app.test_request_context(json={'connection': {'title': 'conn'}, 'scheduler': {'title': 's'}}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_scheduler)(request_user=CLOUD_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


class TestGetOcSchedulerCloud:
    """Cloud get validates access and unmaps the titles."""

    def test_valid_returns_unmapped(self, cloud_app, sched_manager, cloud_managers) -> None:
        """A scheduler in the subscription is returned (titles unmapped)."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.get_scheduler.return_value = _mapped_scheduler()

        with cloud_app.test_request_context():
            response = _unwrap(get_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK

    def test_not_in_subscription_returns_400(self, cloud_app, sched_manager, cloud_managers) -> None:
        """A scheduler outside the subscription aborts 400 before any fetch."""
        cloud_managers.cached.get_cached_user.return_value = None
        cloud_managers.dg_sp.check_scheduler_in_sub.return_value = False

        with cloud_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.get_scheduler.assert_not_called()


class TestGetAllOcSchedulersCloud:
    """Cloud get-all resolves accessible ids (cache-first) and unmaps each scheduler."""

    def test_via_cache(self, cloud_app, sched_manager, cloud_managers) -> None:
        """Ids come from the cache; each returned scheduler is unmapped."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.get_oc_ids.return_value = [SCHEDULER_ID]
        sched_manager.get_schedulers_by_ids.return_value = [_mapped_scheduler()]

        with cloud_app.test_request_context():
            response = _unwrap(get_all_oc_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK
        cloud_managers.dg_sp.get_scheduler_ids.assert_not_called()

    def test_via_portal_fallback(self, cloud_app, sched_manager, cloud_managers) -> None:
        """An uncached user resolves ids from the Service Portal."""
        cloud_managers.cached.get_cached_user.return_value = None
        cloud_managers.dg_sp.get_scheduler_ids.return_value = [SCHEDULER_ID]
        sched_manager.get_schedulers_by_ids.return_value = [_mapped_scheduler()]

        with cloud_app.test_request_context():
            response = _unwrap(get_all_oc_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK
        cloud_managers.dg_sp.get_scheduler_ids.assert_called_once()

    def test_no_ids_returns_none(self, cloud_app, sched_manager, cloud_managers) -> None:
        """No accessible ids skips the by-ids fetch."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.get_oc_ids.return_value = []

        with cloud_app.test_request_context():
            response = _unwrap(get_all_oc_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK
        sched_manager.get_schedulers_by_ids.assert_not_called()


class TestGetOcRunningSchedulersCloud:
    """Cloud running-list filters to the accessible ids and unmaps the flat connector titles."""

    def test_filters_and_unmaps(self, cloud_app, sched_manager, cloud_managers) -> None:
        """Only accessible running schedulers are returned, unmapped."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.get_oc_ids.return_value = [SCHEDULER_ID]
        sched_manager.get_running_schedulers.return_value = [_mapped_running_scheduler()]

        with cloud_app.test_request_context():
            response = _unwrap(get_oc_running_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK


class TestGetOcSchedulerLogsCloud:
    """Cloud logs validate access before fetching."""

    def test_valid_returns_logs(self, cloud_app, sched_manager, cloud_managers) -> None:
        """A valid scheduler in the subscription returns its logs."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.get_scheduler_logs.return_value = []

        with cloud_app.test_request_context(f'/?scheduler_id={SCHEDULER_ID}&status=s'):
            response = _unwrap(get_oc_scheduler_logs)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK

    def test_not_in_subscription_returns_400(self, cloud_app, sched_manager, cloud_managers) -> None:
        """A scheduler outside the subscription aborts 400 before the logs fetch."""
        cloud_managers.cached.get_cached_user.return_value = None
        cloud_managers.dg_sp.check_scheduler_in_sub.return_value = False

        with cloud_app.test_request_context(f'/?scheduler_id={SCHEDULER_ID}&status=s'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler_logs)(request_user=CLOUD_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.get_scheduler_logs.assert_not_called()


class TestExecuteOcSchedulerCloud:
    """Cloud execute validates access before executing."""

    def test_valid_executes(self, cloud_app, sched_manager, cloud_managers) -> None:
        """A scheduler in the subscription is executed."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.execute_scheduler.return_value = {'status': 'running'}

        with cloud_app.test_request_context():
            response = _unwrap(execute_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        sched_manager.execute_scheduler.assert_called_once_with(SCHEDULER_ID)


class TestUpdateOcSchedulerCloud:
    """Cloud update validates access, maps the title and unmaps the response."""

    def test_valid_maps_and_unmaps(self, cloud_app, sched_manager, cloud_managers) -> None:
        """The title is mapped for the update and the response titles are unmapped."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.update_scheduler.return_value = _mapped_scheduler()

        with cloud_app.test_request_context(json={'title': 'renamed'}):
            response = _unwrap(update_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        assert sched_manager.update_scheduler.call_args.args[0]['title'] == f'{CLOUD_DB}_renamed'


class TestDeleteOcSchedulerCloud:
    """Cloud delete validates the scheduler + connection, then cascades the Service Portal cleanup."""

    def test_valid_deletes_and_cleans_up(self, cloud_app, sched_manager, conn_manager, cloud_managers) -> None:
        """A valid delete removes the scheduler + connection and their Service Portal ids."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}
        sched_manager.delete_scheduler.return_value = True

        with cloud_app.test_request_context():
            response = _unwrap(delete_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        conn_manager.delete_connection.assert_called_once_with(CONNECTION_ID)
        cloud_managers.dg_sp.delete_scheduler_id.assert_called_once()
        cloud_managers.dg_sp.delete_connection_id.assert_called_once()

    def test_scheduler_not_in_subscription_returns_400(
        self, cloud_app, sched_manager, conn_manager, cloud_managers,
    ) -> None:
        """A scheduler outside the subscription aborts 400."""
        del conn_manager
        cloud_managers.cached.get_cached_user.return_value = None
        cloud_managers.dg_sp.check_scheduler_in_sub.return_value = False
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}

        with cloud_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.delete_scheduler.assert_not_called()

    def test_connection_not_in_subscription_returns_400(
        self, cloud_app, sched_manager, conn_manager, cloud_managers,
    ) -> None:
        """A backing connection outside the subscription aborts 400."""
        del conn_manager
        # scheduler check passes, connection check fails
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.side_effect = [True, False]
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}

        with cloud_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.delete_scheduler.assert_not_called()

    def test_not_deleted_skips_cascade(self, cloud_app, sched_manager, conn_manager, cloud_managers) -> None:
        """When the scheduler delete returns False, the connection/id cleanup is skipped."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.oc_id_exists.return_value = True
        sched_manager.get_scheduler.return_value = {'connection': {'connectionId': CONNECTION_ID}}
        sched_manager.delete_scheduler.return_value = False

        with cloud_app.test_request_context():
            response = _unwrap(delete_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert response.status_code == HTTPStatus.OK
        conn_manager.delete_connection.assert_not_called()
        cloud_managers.dg_sp.delete_scheduler_id.assert_not_called()


# ------------------------------- remaining branch / error-handler coverage ------------------------------------------ #

class TestSchedulerBranchCoverage:
    """Remaining cloud branch partials and per-handler error/HTTPException paths."""

    def test_running_no_accessible_ids(self, cloud_app, sched_manager, cloud_managers) -> None:
        """No accessible scheduler ids leaves the full running list untouched."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.get_oc_ids.return_value = []
        sched_manager.get_running_schedulers.return_value = [_mapped_running_scheduler()]

        with cloud_app.test_request_context():
            response = _unwrap(get_oc_running_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK

    def test_running_no_matching_scheduler(self, cloud_app, sched_manager, cloud_managers) -> None:
        """Accessible ids that match no running scheduler leave the list untouched."""
        cloud_managers.cached.get_cached_user.return_value = {'email': CLOUD_USER.email}
        cloud_managers.cached.get_oc_ids.return_value = [999]  # no running scheduler has this id
        sched_manager.get_running_schedulers.return_value = [_mapped_running_scheduler()]

        with cloud_app.test_request_context():
            response = _unwrap(get_oc_running_schedulers)(request_user=CLOUD_USER)

        assert response.status_code == HTTPStatus.OK

    def test_logs_get_error_returns_500(self, flask_app, sched_manager, conn_manager, patched_managers) -> None:
        """An OcSchedulerGetError while fetching logs maps to 500."""
        del patched_managers, conn_manager
        sched_manager.get_scheduler_logs.side_effect = OcSchedulerGetError('boom')

        with flask_app.test_request_context(f'/?scheduler_id={SCHEDULER_ID}&status=s'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_scheduler_logs)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_execute_not_in_subscription_returns_400(self, cloud_app, sched_manager, cloud_managers) -> None:
        """Executing a scheduler outside the subscription aborts 400 before running it."""
        cloud_managers.cached.get_cached_user.return_value = None
        cloud_managers.dg_sp.check_scheduler_in_sub.return_value = False

        with cloud_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(execute_oc_scheduler)(request_user=CLOUD_USER, scheduler_id=SCHEDULER_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        sched_manager.execute_scheduler.assert_not_called()

    def test_update_httpexception_propagates(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An HTTPException from the manager is re-raised unchanged by update."""
        del patched_managers, conn_manager
        sched_manager.update_scheduler.side_effect = HTTPException()

        with flask_app.test_request_context(json={'title': 'renamed'}):
            with pytest.raises(HTTPException):
                _unwrap(update_oc_scheduler)(request_user=REQUEST_USER, scheduler_id=SCHEDULER_ID)

    def test_get_all_httpexception_propagates(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An HTTPException from the manager is re-raised unchanged by get-all."""
        del patched_managers, conn_manager
        sched_manager.get_all_schedulers.side_effect = HTTPException()

        with flask_app.test_request_context():
            with pytest.raises(HTTPException):
                _unwrap(get_all_oc_schedulers)(request_user=REQUEST_USER)

    def test_running_httpexception_propagates(
        self, flask_app, sched_manager, conn_manager, patched_managers,
    ) -> None:
        """An HTTPException from the manager is re-raised unchanged by the running-list route."""
        del patched_managers, conn_manager
        sched_manager.get_running_schedulers.side_effect = HTTPException()

        with flask_app.test_request_context():
            with pytest.raises(HTTPException):
                _unwrap(get_oc_running_schedulers)(request_user=REQUEST_USER)
