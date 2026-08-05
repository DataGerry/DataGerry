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
Functional tests for the GET /frontend_init route.

Exercises the endpoint end-to-end through the REST test client: it returns the raw contents of
app-config.json (read fresh from SystemConfigReader.RUNNING_CONFIG_LOCATION per request) and
degrades to an empty dict when the file is missing or malformed. The config directory is pointed
at a temporary path so the on-disk fixture is fully controlled by each test.
"""
from http import HTTPStatus
from pathlib import Path

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.interface.rest_api.routes.connection_helper import FRONTEND_CONFIG_FILENAME
# -------------------------------------------------------------------------------------------------------------------- #

FRONTEND_INIT_URL: str = '/frontend_init'

SAMPLE_CONFIG: dict[str, str] = {
    'protocol': 'http',
    'apiUrl': '192.168.64.2',
    'apiPort': '2120',
}


def _point_config_dir_at(monkeypatch, directory: Path) -> None:
    """Points the SystemConfigReader config directory at ``directory`` for the current test."""
    monkeypatch.setattr(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(directory))


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
