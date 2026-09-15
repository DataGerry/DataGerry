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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with OcInvokerManager patched at the route module path - no external OpenCelium
HTTP, no Mongo. The app runs on-premise (cloud_mode/local_mode False). The AUTOMATIONS 403 gate is
covered by the functional automations-gating suite.

These pin the handler glue: the manager call (incl. the opsIncluded flag), the success payload and
the per-error abort mapping. The flag's own rule and the manager factory live in `oc_invoker_helper`
and are tested there, without a request context.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from flask import Flask

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes import (
    get_all_oc_invokers,
    get_oc_invoker_by_name,
    check_oc_invoker_exists,
    oc_invokers_blueprint,
)
from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes'

INVOKER_NAME: str = 'DataGerry'

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


@pytest.fixture(name='invoker_manager')
def fixture_invoker_manager() -> MagicMock:
    """The OcInvokerManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_manager')
def fixture_patched_manager(invoker_manager: MagicMock) -> Any:
    """
    Patches the manager factory the routes call

    The construction moved into `oc_invoker_helper.build_invoker_manager` when the three identical
    copies were extracted, so the routes' collaborator is that factory - patching `OcInvokerManager`
    at this module path would let the real manager be built (and read the OpenCelium config).
    """
    with patch(f'{ROUTE_PATH}.build_invoker_manager', return_value=invoker_manager):
        yield


# --------------------------------------------------- get_all_oc_invokers -------------------------------------------- #

class TestGetAllOcInvokers:
    """``get_all_oc_invokers`` returns all invokers, forwarding the opsIncluded flag."""

    def test_returns_all_invokers_default_ops(self, flask_app, invoker_manager, patched_manager) -> None:
        """With no query param, operations are included by default (True)."""
        del patched_manager
        invoker_manager.get_all_invokers.return_value = [{'name': INVOKER_NAME}]

        with flask_app.test_request_context('/invokers'):
            response = _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(True)

    def test_ops_included_false_disables_operations(self, flask_app, invoker_manager, patched_manager) -> None:
        """``?opsIncluded=false`` is parsed as False (guards the previous type=bool footgun)."""
        del patched_manager
        invoker_manager.get_all_invokers.return_value = []

        with flask_app.test_request_context('/invokers?opsIncluded=false'):
            response = _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(False)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.get_all_invokers.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context('/invokers'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------- get_oc_invoker_by_name ------------------------------------------- #

class TestGetOcInvokerByName:
    """``get_oc_invoker_by_name`` returns a single invoker by name."""

    def test_returns_invoker(self, flask_app, invoker_manager, patched_manager) -> None:
        """The manager's invoker is returned with 200."""
        del patched_manager
        invoker_manager.get_invoker_by_name.return_value = {'name': INVOKER_NAME}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_invoker_by_name)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_invoker_by_name.assert_called_once_with(INVOKER_NAME)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.get_invoker_by_name.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_invoker_by_name)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ check_oc_invoker_exists ------------------------------------------- #

class TestCheckOcInvokerExists:
    """``check_oc_invoker_exists`` returns the manager's existence flag."""

    def test_returns_exists_flag(self, flask_app, invoker_manager, patched_manager) -> None:
        """The boolean from check_invoker_exists is returned with 200."""
        del patched_manager
        invoker_manager.check_invoker_exists.return_value = True

        with flask_app.test_request_context():
            response = _unwrap(check_oc_invoker_exists)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.check_invoker_exists.assert_called_once_with(INVOKER_NAME)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.check_invoker_exists.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_oc_invoker_exists)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------- the answered shapes ---------------------------------------------- #

class TestTheAnsweredShapes:
    """What a client actually receives - a frontend-visible contract on both routes."""

    def test_the_list_route_answers_a_list(self, flask_app, invoker_manager, patched_manager) -> None:
        """
        The connector form iterates it

        Answered as OpenCelium listed them: no envelope, no per-invoker rewriting.
        """
        del patched_manager
        invoker_manager.get_all_invokers.return_value = [{'name': INVOKER_NAME}, {'name': 'Other'}]

        with flask_app.test_request_context('/invokers'):
            response = _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert response.json == [{'name': INVOKER_NAME}, {'name': 'Other'}]

    @pytest.mark.parametrize('exists', [True, False])
    def test_the_exists_route_answers_a_bare_boolean(
            self, flask_app, invoker_manager, patched_manager, exists: bool) -> None:
        """
        Not `{'result': ...}` - the same shape as the connector-exists route beside it

        The manager reads OpenCelium's `result` key and answers the bool; the route passes it
        through untouched.
        """
        del patched_manager
        invoker_manager.check_invoker_exists.return_value = exists

        with flask_app.test_request_context(f'/invokers/exists/{INVOKER_NAME}'):
            response = _unwrap(check_oc_invoker_exists)(request_user=REQUEST_USER, name=INVOKER_NAME)

        assert response.json is exists

    def test_the_name_route_answers_the_invoker_itself(
            self, flask_app, invoker_manager, patched_manager) -> None:
        """One invoker, as OpenCelium answered it - no envelope either"""
        del patched_manager
        invoker_manager.get_invoker_by_name.return_value = {'name': INVOKER_NAME, 'operations': []}

        with flask_app.test_request_context(f'/invokers/{INVOKER_NAME}'):
            response = _unwrap(get_oc_invoker_by_name)(request_user=REQUEST_USER, name=INVOKER_NAME)

        assert response.json == {'name': INVOKER_NAME, 'operations': []}


# ------------------------------------------------ the route registration -------------------------------------------- #

class TestRouteRegistration:
    """Every route of the blueprint is registered."""

    def test_every_route_is_registered(self) -> None:
        """
        Asserted as a map, because this package has shipped an unregistered route before

        A missing '@' on the execution-log DELETE left it invisible until someone looked; the log
        module has carried this guard since, and these three had none.
        """
        app = Flask(__name__)
        app.register_blueprint(oc_invokers_blueprint)

        registered = {(rule.rule, method) for rule in app.url_map.iter_rules() for method in rule.methods}

        assert {
            ('/invokers', 'GET'),
            ('/invokers/<string:name>', 'GET'),
            ('/invokers/exists/<string:name>', 'GET'),
        } <= registered

    def test_the_read_routes_answer_head_as_well(self) -> None:
        """All three are declared GET/HEAD, which is what the docstrings claim"""
        app = Flask(__name__)
        app.register_blueprint(oc_invokers_blueprint)

        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/invokers'):
                assert 'HEAD' in rule.methods
