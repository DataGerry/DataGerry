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
Unit tests for cmdb.interface.rest_api.routes.connection_helper.load_frontend_config

Pure tests: no Flask app context. SystemConfigReader.RUNNING_CONFIG_LOCATION is pointed at a
temporary directory so real files are read through json.load, exercising the success branch
and both failure branches (missing file / malformed JSON) that fall back to an empty dict.
"""
from pathlib import Path
from unittest.mock import patch

from cmdb.interface.rest_api.routes.connection_helper import (
    load_frontend_config,
    FRONTEND_CONFIG_FILENAME,
)
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

SCR_PATH: str = 'cmdb.manager.system_manager.system_config_reader.SystemConfigReader'

VALID_CONFIG: dict[str, str] = {
    'protocol': 'http',
    'apiUrl': '192.168.64.2',
    'apiPort': '2120',
}


def _write_config(directory: Path, contents: str) -> None:
    """Writes ``contents`` verbatim into ``<directory>/app-config.json``."""
    (directory / FRONTEND_CONFIG_FILENAME).write_text(contents, encoding='utf-8')


# -------------------------------------------------------------------------------------------------------------------- #
#                                            load_frontend_config                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLoadFrontendConfig:
    """``load_frontend_config`` parses the file next to cmdb.conf, degrading to {} on any failure."""

    def test_returns_parsed_dict_for_valid_json(self, tmp_path: Path) -> None:
        """A well-formed JSON file is parsed and returned verbatim as a dict."""
        _write_config(tmp_path, '{"protocol": "http", "apiUrl": "192.168.64.2", "apiPort": "2120"}')

        with patch.object(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(tmp_path)):
            result = load_frontend_config()

        assert result == VALID_CONFIG

    def test_reads_from_the_config_directory_filename(self, tmp_path: Path) -> None:
        """The file resolved is exactly '<RUNNING_CONFIG_LOCATION>/app-config.json'."""
        _write_config(tmp_path, '{"apiPort": "2120"}')

        with patch.object(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(tmp_path)):
            result = load_frontend_config()

        assert result == {'apiPort': '2120'}

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        """A missing file (OSError) is swallowed and an empty dict is returned."""
        with patch.object(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(tmp_path)):
            result = load_frontend_config()

        assert result == {}

    def test_returns_empty_dict_for_malformed_json(self, tmp_path: Path) -> None:
        """A file that is not valid JSON (ValueError) is swallowed and an empty dict is returned."""
        _write_config(tmp_path, '{ this is not valid json ]')

        with patch.object(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(tmp_path)):
            result = load_frontend_config()

        assert result == {}

    def test_returns_empty_dict_for_empty_file(self, tmp_path: Path) -> None:
        """An empty file is not valid JSON and therefore degrades to an empty dict."""
        _write_config(tmp_path, '')

        with patch.object(SystemConfigReader, 'RUNNING_CONFIG_LOCATION', str(tmp_path)):
            result = load_frontend_config()

        assert result == {}
