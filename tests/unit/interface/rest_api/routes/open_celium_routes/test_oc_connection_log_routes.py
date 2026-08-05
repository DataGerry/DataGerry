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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with OcConnectionLogManager patched at the route module path - no external
OpenCelium HTTP, no Mongo. The app runs on-premise (cloud_mode/local_mode False), so the cloud
unmap branch in oc_get_flowcharts is skipped. The AUTOMATIONS 403 gate is covered by the functional
automations-gating suite.

These pin the handler glue: the manager call, the success payload, the query-param validation aborts
(missing loopIndex / connectionId / schedulerId / status) and the per-error abort mapping. They
exercise handler LOGIC only - they do not assert blueprint route registration (see the audit note on
the unregistered DELETE route).
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_routes import (
    oc_connection_log_blueprint,
    oc_get_method_or_operator_details,
    oc_get_operator_children,
    oc_get_flowcharts,
    oc_get_first_level_logs,
    oc_get_log_list,
    oc_delete_logs,
)
from cmdb.errors.open_celium.connection_log import OcConnectionLogGetError, OcConnectionLogDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_routes'

TARGET_ID: int = 42
CONNECTION_ID: int = 1
SCHEDULER_ID: int = 2

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


@pytest.fixture(name='log_manager')
def fixture_log_manager() -> MagicMock:
    """The OcConnectionLogManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_manager')
def fixture_patched_manager(log_manager: MagicMock) -> Any:
    """Patches OcConnectionLogManager at the route module path."""
    with patch(f'{ROUTE_PATH}.OcConnectionLogManager', return_value=log_manager):
        yield


# ------------------------------------------ oc_get_method_or_operator_details --------------------------------------- #

class TestGetMethodOrOperatorDetails:
    """``oc_get_method_or_operator_details`` returns the manager's detail payload."""

    def test_returns_details(self, flask_app, log_manager, patched_manager) -> None:
        """The detail payload is returned with 200."""
        del patched_manager
        log_manager.get_details_method_or_operator.return_value = {'detail': True}

        with flask_app.test_request_context():
            response = _unwrap(oc_get_method_or_operator_details)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert response.status_code == HTTPStatus.OK
        log_manager.get_details_method_or_operator.assert_called_once_with(TARGET_ID)

    def test_get_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogGetError maps to 500."""
        del patched_manager
        log_manager.get_details_method_or_operator.side_effect = OcConnectionLogGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_method_or_operator_details)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ oc_get_operator_children ------------------------------------------ #

class TestGetOperatorChildren:
    """``oc_get_operator_children`` requires a loopIndex query param."""

    def test_returns_children(self, flask_app, log_manager, patched_manager) -> None:
        """A loopIndex returns the operator children with 200."""
        del patched_manager
        log_manager.get_operator_children.return_value = {'children': []}

        with flask_app.test_request_context('/connections/logs/children/42?loopIndex=3'):
            response = _unwrap(oc_get_operator_children)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert response.status_code == HTTPStatus.OK
        log_manager.get_operator_children.assert_called_once_with(TARGET_ID, '3')

    def test_missing_loop_index_returns_400(self, flask_app, log_manager, patched_manager) -> None:
        """A missing loopIndex query param aborts with 400."""
        del patched_manager, log_manager

        with flask_app.test_request_context('/connections/logs/children/42'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_operator_children)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_get_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogGetError maps to 500."""
        del patched_manager
        log_manager.get_operator_children.side_effect = OcConnectionLogGetError('boom')

        with flask_app.test_request_context('/connections/logs/children/42?loopIndex=3'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_operator_children)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- oc_get_flowcharts ---------------------------------------------- #

class TestGetFlowcharts:
    """``oc_get_flowcharts`` returns the flowcharts (no cloud unmap on-premise)."""

    def test_returns_flowcharts(self, flask_app, log_manager, patched_manager) -> None:
        """The flowcharts are returned with 200."""
        del patched_manager
        log_manager.get_flowcharts.return_value = [{'connectorName': 'c'}]

        with flask_app.test_request_context():
            response = _unwrap(oc_get_flowcharts)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert response.status_code == HTTPStatus.OK
        log_manager.get_flowcharts.assert_called_once_with(TARGET_ID)

    def test_get_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogGetError maps to 500."""
        del patched_manager
        log_manager.get_flowcharts.side_effect = OcConnectionLogGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_flowcharts)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------- oc_get_first_level_logs ------------------------------------------ #

class TestGetFirstLevelLogs:
    """``oc_get_first_level_logs`` returns the first-level logs."""

    def test_returns_logs(self, flask_app, log_manager, patched_manager) -> None:
        """The first-level logs are returned with 200."""
        del patched_manager
        log_manager.get_first_level_logs.return_value = {'logs': []}

        with flask_app.test_request_context():
            response = _unwrap(oc_get_first_level_logs)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert response.status_code == HTTPStatus.OK
        log_manager.get_first_level_logs.assert_called_once_with(TARGET_ID)

    def test_get_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogGetError maps to 500."""
        del patched_manager
        log_manager.get_first_level_logs.side_effect = OcConnectionLogGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_first_level_logs)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------- oc_get_log_list ----------------------------------------------- #

class TestGetLogList:
    """``oc_get_log_list`` requires connectionId, schedulerId and status query params."""

    def test_returns_log_list(self, flask_app, log_manager, patched_manager) -> None:
        """Valid query params return the log list with 200."""
        del patched_manager
        log_manager.get_log_list.return_value = {'list': []}

        url = f'/connections/logs/list?connectionId={CONNECTION_ID}&schedulerId={SCHEDULER_ID}&status=s'
        with flask_app.test_request_context(url):
            response = _unwrap(oc_get_log_list)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        log_manager.get_log_list.assert_called_once_with(CONNECTION_ID, SCHEDULER_ID, 's')

    def test_missing_connection_id_returns_400(self, flask_app, log_manager, patched_manager) -> None:
        """A missing connectionId aborts with 400."""
        del patched_manager, log_manager

        with flask_app.test_request_context(f'/connections/logs/list?schedulerId={SCHEDULER_ID}&status=s'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_log_list)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_missing_scheduler_id_returns_400(self, flask_app, log_manager, patched_manager) -> None:
        """A missing schedulerId aborts with 400."""
        del patched_manager, log_manager

        with flask_app.test_request_context(f'/connections/logs/list?connectionId={CONNECTION_ID}&status=s'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_log_list)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_missing_status_returns_400(self, flask_app, log_manager, patched_manager) -> None:
        """A missing status aborts with 400."""
        del patched_manager, log_manager

        url = f'/connections/logs/list?connectionId={CONNECTION_ID}&schedulerId={SCHEDULER_ID}'
        with flask_app.test_request_context(url):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_log_list)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_get_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogGetError maps to 500."""
        del patched_manager
        log_manager.get_log_list.side_effect = OcConnectionLogGetError('boom')

        url = f'/connections/logs/list?connectionId={CONNECTION_ID}&schedulerId={SCHEDULER_ID}&status=s'
        with flask_app.test_request_context(url):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_get_log_list)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------------- oc_delete_logs ----------------------------------------------- #

class TestDeleteLogs:
    """``oc_delete_logs`` deletes the execution logs (handler logic; route registration not asserted)."""

    def test_returns_delete_result(self, flask_app, log_manager, patched_manager) -> None:
        """The manager's delete result is returned with 200."""
        del patched_manager
        log_manager.delete_logs.return_value = {'deleted': True}

        with flask_app.test_request_context():
            response = _unwrap(oc_delete_logs)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert response.status_code == HTTPStatus.OK
        log_manager.delete_logs.assert_called_once_with(TARGET_ID)

    def test_delete_error_returns_500(self, flask_app, log_manager, patched_manager) -> None:
        """An OcConnectionLogDeleteError maps to 500."""
        del patched_manager
        log_manager.delete_logs.side_effect = OcConnectionLogDeleteError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_delete_logs)(request_user=REQUEST_USER, target_id=TARGET_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- route registration --------------------------------------------- #

class TestRouteRegistration:
    """The blueprint registers every documented route (guards the previously missing DELETE decorator)."""

    def test_delete_logs_route_is_registered(self) -> None:
        """``DELETE /connections/logs/<int:target_id>`` is registered on the blueprint (the '@' was missing)."""
        app = Flask(__name__)
        app.register_blueprint(oc_connection_log_blueprint)

        delete_rules = [
            rule for rule in app.url_map.iter_rules()
            if rule.rule == '/connections/logs/<int:target_id>' and 'DELETE' in rule.methods
        ]

        assert len(delete_rules) == 1
