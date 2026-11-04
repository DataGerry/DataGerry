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
Functional tests: two object reads answer a temporary database failure with the app's 503 / 423

``GET /objects/state/<id>`` caught ``Exception`` around its read, and ``GET /objects/<id>`` around its render (which
reads referenced objects and types), so a lost connection or a lock timeout became their own 500. The state route
now ends in ``handle_route_errors``; the render arm lets the outage through to it. An unexpected error still answers
each route's own 500
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects import objects_routes

from tests.functional.framework.objects.objects_route_helpers import ROUTE_URL, drop_object, insert_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 97101
VALUE: str = 'outage'
TRANSIENT_ANSWERS: list[tuple[type[Exception], HTTPStatus]] = [
    (DocumentNetworkError, HTTPStatus.SERVICE_UNAVAILABLE),
    (DocumentLockTimeoutError, HTTPStatus.LOCKED),
]
TRANSIENT_IDS: list[str] = ['network-503', 'lock-423']
STATE_URL: str = f'{ROUTE_URL}/state/{OBJECT_ID}'
OBJECT_URL: str = f'{ROUTE_URL}/{OBJECT_ID}'
STATE_500: str = f'An internal server error occured while retrieving the object state of ID:{OBJECT_ID}!'
RENDER_500: str = f'Object with ID: {OBJECT_ID} could not be rendered!'


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """One object of the package's type"""
    insert_object_doc(database_manager, database_name, OBJECT_ID, VALUE)
    yield
    drop_object(database_manager, database_name, OBJECT_ID)


def _raise(failure: Exception) -> Any:
    """A stand-in that raises ``failure`` whatever it is called with"""
    def _stub(*_args: Any, **_kwargs: Any) -> Any:
        raise failure

    return _stub


class TestTheStateRead:
    """GET /objects/state/<id>"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, error: type[Exception],
                                                    status: HTTPStatus) -> None:
        """Try again later"""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raise(error('database unavailable')))

        assert rest_api.get(STATE_URL).status_code == status

    def test_an_unexpected_error_is_the_routes_500(self, rest_api, monkeypatch) -> None:
        """Named by the route's message"""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raise(RuntimeError('a bug')))

        response = rest_api.get(STATE_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == STATE_500

    def test_without_a_failure_it_answers(self, rest_api) -> None:
        """The seeded object is active"""
        assert rest_api.get(STATE_URL).get_json() is True


class TestTheRender:
    """GET /objects/<id> - the render reads referenced objects and types"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, error: type[Exception],
                                                    status: HTTPStatus) -> None:
        """Not 'could not be rendered'"""
        monkeypatch.setattr(objects_routes, 'CmdbMultiRender', _raise(error('database unavailable')))

        assert rest_api.get(OBJECT_URL).status_code == status

    def test_an_unexpected_error_keeps_its_500(self, rest_api, monkeypatch) -> None:
        """Worded as before"""
        monkeypatch.setattr(objects_routes, 'CmdbMultiRender', _raise(RuntimeError('a bug')))

        response = rest_api.get(OBJECT_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == RENDER_500
