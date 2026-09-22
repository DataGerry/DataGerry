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
the 500 it answers when the database status probe fails. Its database manager is resolved per request
from the app (it used to be captured at module import, which is why these tests had to import the
module lazily and patch module state - both worked around on 2026-09-07), so a broken manager is
injected by patching the app the test client is bound to. Both routes are unauthenticated by design,
which is what makes them reachable in these tests without a token.
"""
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
import logging

from cmdb import __title__, __version__
from cmdb.errors.database import DatabaseConnectionError
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.interface.rest_api.routes import connection
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


def _break_the_database_manager(rest_api, monkeypatch) -> None:
    """
    Points the app's database manager at one whose status probe raises

    This is the route **itself** failing, not the database being unreachable: since T123 an
    unreachable database answers `connected: false` with a 200, and only a manager that raises out of
    `status()` reaches the route's own 500. The route reads ``current_app.database_manager`` per
    request, so the app the test client is bound to is the thing to patch.
    """
    broken_manager = SimpleNamespace(status=_raise(DatabaseConnectionError('unreachable')))
    monkeypatch.setattr(rest_api.application, 'database_manager', broken_manager)


def _disconnect_the_database(rest_api, monkeypatch) -> None:
    """Points the app's database manager at one reporting an unreachable database, the honest way."""
    monkeypatch.setattr(rest_api.application, 'database_manager', SimpleNamespace(status=lambda: False))


def _make_the_real_probe_fail(rest_api, monkeypatch) -> None:
    """
    Breaks the **connector** rather than the manager, so the whole chain runs

    `is_connected` -> `status` -> the route. Patching the manager's `status` proves only what the route
    does with a False; this proves the connector produces one, which is the half that did not exist
    before T123.
    """
    connector = rest_api.application.database_manager.connector
    monkeypatch.setattr(type(connector), 'connect', _raise(DatabaseConnectionError('unreachable')))


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
        """A reachable database reports connected: true."""
        response = rest_api.get(CONNECTION_URL)

        assert response.get_json()[ConnectionInfoKey.CONNECTED.value] is True

    def test_an_unreachable_database_answers_200_with_connected_false(self, rest_api, monkeypatch) -> None:
        """
        The condition this route exists to report is reportable (T123)

        It used to be the 500 below, because `MongoConnector.is_connected` raised instead of returning
        False - so a monitoring check could not tell "the database is down" from "the API is broken".
        """
        _disconnect_the_database(rest_api, monkeypatch)

        response = rest_api.get(CONNECTION_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[ConnectionInfoKey.CONNECTED.value] is False

    def test_the_whole_probe_chain_answers_false_rather_than_raising(self, rest_api, monkeypatch) -> None:
        """
        End to end: a connector that cannot reach the database produces `connected: false`

        The other test patches the manager and proves what the route does with a False. This one
        breaks the real probe, which is what used to raise all the way out to the 500 (T123).
        """
        _make_the_real_probe_fail(rest_api, monkeypatch)

        response = rest_api.get(CONNECTION_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[ConnectionInfoKey.CONNECTED.value] is False

    def test_an_unreachable_database_still_reports_title_and_version(self, rest_api, monkeypatch) -> None:
        """The rest of the payload is the API's own state and is still answerable."""
        _disconnect_the_database(rest_api, monkeypatch)

        body = rest_api.get(CONNECTION_URL).get_json()

        assert body[ConnectionInfoKey.TITLE.value] == __title__
        assert body[ConnectionInfoKey.VERSION.value] == __version__

    def test_head_request_is_accepted(self, rest_api) -> None:
        """The route is registered for HEAD as well as GET."""
        assert rest_api.head(CONNECTION_URL).status_code == HTTPStatus.OK

    def test_a_status_probe_that_raises_is_still_a_500(self, rest_api, monkeypatch) -> None:
        """
        The catch-all is narrower now, not redundant

        An unreachable database is `connected: false`; what reaches the 500 is the route failing -
        a manager that raises out of `status()`, a missing manager, a serialisation failure.
        """
        _break_the_database_manager(rest_api, monkeypatch)

        response = rest_api.get(CONNECTION_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_manager_is_read_per_request(self, rest_api, monkeypatch) -> None:
        """
        A manager swapped between two requests is picked up by the second one

        This is what the import-time binding could not do: the manager was captured once, so it
        outlived the app it came from and every request answered from that one object.
        """
        assert rest_api.get(CONNECTION_URL).status_code == HTTPStatus.OK

        _break_the_database_manager(rest_api, monkeypatch)

        assert rest_api.get(CONNECTION_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_failure_is_logged_at_error_level(self, rest_api, monkeypatch, caplog) -> None:
        """
        A route failure is logged at ERROR, not DEBUG

        It used to be LOGGER.debug, so an instance answering 500 left no trace at the default level.
        """
        _break_the_database_manager(rest_api, monkeypatch)

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
        monkeypatch.setattr(connection, 'load_frontend_config', _raise(RuntimeError('helper changed')))

        response = rest_api.get(FRONTEND_INIT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
