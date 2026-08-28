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
Functional tests for the two routes served at the /rest root

Exercises both endpoints of ``routes/connection.py`` end-to-end through the REST test client.

``GET /frontend_init`` returns the raw contents of app-config.json (read fresh from
SystemConfigReader.RUNNING_CONFIG_LOCATION per request) and degrades to an empty dict when the file is
missing or malformed. The config directory is pointed at a temporary path so the on-disk fixture is
fully controlled by each test.

``GET /`` is the reachability probe, added here on 2026-08-27: the whole route was untested, including
the 500 it answers when the database status probe fails. Note what its tests have to patch - the route
module binds its database manager at IMPORT time, so the manager is module state rather than a
request-scoped object. Both routes are unauthenticated by design, which is what makes them reachable in
these tests without a token.
"""
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
import logging

from cmdb import __title__, __version__
from cmdb.errors.database import DatabaseConnectionError
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.interface.rest_api.routes.connection_constants import ConnectionInfoKey
from cmdb.interface.rest_api.routes.connection_helper import FRONTEND_CONFIG_FILENAME
# -------------------------------------------------------------------------------------------------------------------- #

FRONTEND_INIT_URL: str = '/frontend_init'
CONNECTION_URL: str = '/'

SAMPLE_CONFIG: dict[str, str] = {
    'protocol': 'http',
    'apiUrl': '192.168.64.2',
    'apiPort': '2120',
}


def _point_config_dir_at(monkeypatch, directory: Path) -> None:
    """Points the SystemConfigReader config directory at ``directory`` for the current test."""
    monkeypatch.setattr(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(directory))


def _connection_module():
    """
    Imports the connection route module lazily and returns it

    It CANNOT be imported at collection time: the module binds its database manager at import inside
    ``with current_app.app_context()``, so importing it without a live app raises. By the time a test
    body runs, the app fixture has built the REST app and the module is already in sys.modules, so this
    import is a lookup. The awkwardness is the cost of that import-time binding, which is filed as a
    decision rather than fixed.
    """
    from cmdb.interface.rest_api.routes import connection  # pylint: disable=import-outside-toplevel

    return connection


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc

    return _fail


# -------------------------------------------------------------------------------------------------------------------- #
#                                            GET /frontend_init                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFrontendInitRoute:
    """GET /frontend_init returns the raw frontend config dict, or {} on any failure."""

    def test_returns_raw_config_dict(self, rest_api, monkeypatch, tmp_path: Path) -> None:
        """A present app-config.json is returned as the unwrapped, raw JSON dict with 200."""
        (tmp_path / FRONTEND_CONFIG_FILENAME).write_text(
            '{"protocol": "http", "apiUrl": "192.168.64.2", "apiPort": "2120"}', encoding='utf-8',
        )
        _point_config_dir_at(monkeypatch, tmp_path)

        response = rest_api.get(FRONTEND_INIT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == SAMPLE_CONFIG

    def test_returns_empty_dict_when_file_missing(self, rest_api, monkeypatch, tmp_path: Path) -> None:
        """With no app-config.json in the config directory the route still responds 200 with {}."""
        _point_config_dir_at(monkeypatch, tmp_path)

        response = rest_api.get(FRONTEND_INIT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}

    def test_returns_empty_dict_for_malformed_json(self, rest_api, monkeypatch, tmp_path: Path) -> None:
        """A malformed app-config.json degrades to 200 with {} rather than erroring."""
        (tmp_path / FRONTEND_CONFIG_FILENAME).write_text('{ not valid json ]', encoding='utf-8')
        _point_config_dir_at(monkeypatch, tmp_path)

        response = rest_api.get(FRONTEND_INIT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}


class TestConnectionCheckRoute:
    """GET /rest/ reports the title, version and database status."""

    def test_returns_title_version_and_connected(self, rest_api) -> None:
        """
        The probe answers 200 with the three contract keys

        The whole route body was untested before 2026-08-27.
        """
        response = rest_api.get(CONNECTION_URL)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert set(body) == {
            ConnectionInfoKey.TITLE.value,
            ConnectionInfoKey.VERSION.value,
            ConnectionInfoKey.CONNECTED.value,
        }
        assert body[ConnectionInfoKey.TITLE.value] == __title__
        assert body[ConnectionInfoKey.VERSION.value] == __version__

    def test_connected_is_true_while_the_database_answers(self, rest_api) -> None:
        """
        A reachable database reports connected: true

        It can never report False: MongoConnector.is_connected raises instead of returning False, so
        the negative answer is the 500 below (discussion-backlog #141).
        """
        response = rest_api.get(CONNECTION_URL)

        assert response.get_json()[ConnectionInfoKey.CONNECTED.value] is True

    def test_head_request_is_accepted(self, rest_api) -> None:
        """The route is registered for HEAD as well as GET."""
        assert rest_api.head(CONNECTION_URL).status_code == HTTPStatus.OK

    def test_unreachable_database_returns_500(self, rest_api, monkeypatch) -> None:
        """
        A failing status probe is the route's negative answer, and it is a 500

        Patches the MODULE attribute rather than a request-scoped manager, because the route binds its
        database manager once at import time.
        """
        broken_manager = SimpleNamespace(status=_raise(DatabaseConnectionError('unreachable')))
        monkeypatch.setattr(_connection_module(), 'dbm', broken_manager)

        response = rest_api.get(CONNECTION_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_failure_is_logged_at_error_level(self, rest_api, monkeypatch, caplog) -> None:
        """
        The one condition this route exists to report is logged at ERROR, not DEBUG

        It used to be LOGGER.debug, so a production instance whose database was unreachable answered
        500 and left no trace at the default log level.
        """
        connection = _connection_module()
        broken_manager = SimpleNamespace(status=_raise(DatabaseConnectionError('unreachable')))
        monkeypatch.setattr(connection, 'dbm', broken_manager)

        with caplog.at_level(logging.ERROR, logger=connection.LOGGER.name):
            rest_api.get(CONNECTION_URL)

        assert any('[connection_test_frontend]' in record.getMessage() for record in caplog.records)


class TestFrontendInitDefenceInDepth:
    """The route's own except arm is defence in depth behind the helper's own guard."""

    def test_a_raising_helper_still_answers_200_with_an_empty_dict(self, rest_api, monkeypatch) -> None:
        """
        Nothing reaches this arm today - load_frontend_config swallows its own errors

        It is kept so a future change to the helper's error handling cannot turn this route into a 500,
        and it is covered by making the helper raise, which is the only way to reach it.
        """
        monkeypatch.setattr(_connection_module(), 'load_frontend_config',
                            _raise(RuntimeError('helper changed')))

        response = rest_api.get(FRONTEND_INIT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
