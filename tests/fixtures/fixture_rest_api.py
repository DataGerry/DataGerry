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
This module defines pytest fixtures for setting up and managing the REST API test client.
"""
from logging import Logger, getLogger

import pytest
from flask import has_request_context, request

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.init_rest_api import create_rest_api
from tests.utils.flask_test_client import RestAPITestClient
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def rest_api(database_manager, full_access_user):
    """
    Provides a configured test client for the REST API.
    
    Args:
        database_manager (MongoDatabaseManager): Instance of the database manager.
        full_access_user: A user with full access permissions for testing.
    
    Yields:
        RestAPITestClient: A test client instance for making API requests.
    """
    api = create_rest_api(database_manager)
    api.test_client_class = RestAPITestClient

    # Not opened with `with`: that would keep every request's context pushed until the next request, so every later
    # test - unit tests included - would run inside the last request any test made. Each request pops its own context
    yield api.test_client(database_manager=database_manager, default_auth_user=full_access_user)


@pytest.fixture(scope="session", autouse=True)
def app_context():
    """
    Provides a bare application context for the whole session

    The app is a plain BaseCmdbApp WITHOUT a database manager. It is what ``current_app`` is whenever no request is
    running: the ``rest_api`` client pops each request's context when the request ends, so a test never runs inside
    another test's request. A test that reaches the database through ``ManagerProvider`` without making a request asks
    for ``rest_api_app_context``, which pushes the REST app's context

    Yields:
        None
    """
    current_app = BaseCmdbApp(__name__)
    with current_app.app_context():
        yield


@pytest.fixture
def rest_api_app_context(rest_api):
    """
    Pushes the REST API app's context, so ManagerProvider resolves ``current_app.database_manager`` to the session's
    database outside a request - where ``current_app`` is otherwise the bare session app (see ``app_context``)

    Not autouse: a test module switches it on with ``pytestmark = pytest.mark.usefixtures('rest_api_app_context')``,
    a single test with ``@pytest.mark.usefixtures('rest_api_app_context')``. A fixture marked like that is set up after
    the module's autouse fixtures - a seeding fixture that needs the context requests it instead

    Args:
        rest_api (RestAPITestClient): The session's REST API test client

    Yields:
        None
    """
    with rest_api.application.app_context():
        yield


#: The tripwire's failure: the test that leaves a request context pushed, and the path of that request
REQUEST_CONTEXT_LEFT_MESSAGE: str = (
    "{test} left a request context pushed ({path}) - every later test would run inside it. Pop what the test pushes "
    "(use `with ...test_request_context():`), and never open a test client with `with` for longer than one test"
)


def leftover_request_context_message(test_name: str) -> str | None:
    """
    The tripwire's verdict after one test: a message when a request context is still pushed, else None

    Args:
        test_name (str): The test that just ran

    Returns:
        str | None: The failure message, or None when no request context is left
    """
    if not has_request_context():
        return None

    return REQUEST_CONTEXT_LEFT_MESSAGE.format(test=test_name, path=request.path)


@pytest.fixture(autouse=True)
def no_request_context_left(request: pytest.FixtureRequest):
    """
    Fails the test after which a request context is still pushed - in its own teardown, so the report names it

    Request-scoped state (``route_utils.request_cache``, ``flask.g``) would otherwise leak into every later test.
    Set up before every other function fixture of a test and torn down after them, so a fixture that pushes a request
    for its test has popped it by then

    Args:
        request (pytest.FixtureRequest): The running test

    Yields:
        None
    """
    yield

    message: str | None = leftover_request_context_message(request.node.nodeid)

    if message:
        pytest.fail(message, pytrace=False)

