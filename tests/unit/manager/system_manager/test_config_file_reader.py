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
Unit tests for cmdb.manager.system_manager.config_file_reader

DB-free and app-free: real ini files are written into pytest's tmp_path and the DATAGERRY_* overlay is
driven with monkeypatch.setenv. Covers construction (file / missing file / malformed file / file-less
mode) and all three read paths, including the environment overlay precedence,
the env-only sections, the auto_cast of both sources, the default handling and every error arm.

Two things the suite has to respect:
* ``SystemEnvironmentReader`` snapshots os.environ in its constructor, so the environment has to be set
  BEFORE the reader is built - a reader built first never sees a later setenv;
* an autouse fixture strips every pre-existing DATAGERRY_* variable so a developer's shell cannot leak
  into the assertions.
"""
from pathlib import Path
from typing import Any

import pytest

from cmdb.manager.system_manager.config_file_reader import ConfigFileReader
from cmdb.errors.system_config import (
    ConfigFileNotFound,
    ConfigFileParsingError,
    ConfigNotLoaded,
    SectionError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ENV_PREFIX: str = 'DATAGERRY_'

CONFIG_NAME: str = 'cmdb-test.conf'
MALFORMED_NAME: str = 'malformed.conf'
MISSING_NAME: str = 'does-not-exist.conf'

DATABASE_SECTION: str = 'Database'
WEBSERVER_SECTION: str = 'WebServer'
ENV_ONLY_SECTION: str = 'OpenCelium'
GHOST_SECTION: str = 'Ghost'

HOST_KEY: str = 'host'
PORT_KEY: str = 'port'
NAME_KEY: str = 'database_name'
MISSING_KEY: str = 'not-in-there'

FILE_HOST: str = 'file-host'
FILE_PORT: int = 27017
FILE_DB_NAME: str = 'cmdb-file'
ENV_HOST: str = 'env-host'
ENV_PORT: int = 27018

CONFIG_BODY: str = f"""[{DATABASE_SECTION}]
{HOST_KEY} = {FILE_HOST}
{PORT_KEY} = {FILE_PORT}
{NAME_KEY} = {FILE_DB_NAME}

[{WEBSERVER_SECTION}]
workers = 2
threaded = True
keepalive = None
timeout = 1.5
"""

MALFORMED_BODY: str = f"{HOST_KEY} = no-section-header\n"


@pytest.fixture(autouse=True)
def _clean_datagerry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removes every pre-existing DATAGERRY_* variable so the shell cannot influence the results."""
    import os  # pylint: disable=import-outside-toplevel

    for key in [key for key in os.environ if key.startswith(ENV_PREFIX)]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(name='config_dir')
def fixture_config_dir(tmp_path: Path) -> Path:
    """Writes the valid and the malformed config file into a temporary directory."""
    (tmp_path / CONFIG_NAME).write_text(CONFIG_BODY, encoding='utf-8')
    (tmp_path / MALFORMED_NAME).write_text(MALFORMED_BODY, encoding='utf-8')

    return tmp_path


def _reader(config_dir: Path, config_name: str | None = CONFIG_NAME) -> ConfigFileReader:
    """Builds a reader for the temporary config directory (config_name=None -> file-less mode)."""
    location = f'{config_dir}/' if config_name is not None else None

    return ConfigFileReader(config_name, location)


def _env_key(section: str, name: str) -> str:
    """Builds the environment variable name the overlay reads for a section/key pair."""
    return f'{ENV_PREFIX}{section}_{name}'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CONSTRUCTION                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConstruction:
    """Loading a file, refusing a missing one, and the file-less mode."""

    def test_loads_an_existing_file(self, config_dir: Path) -> None:
        """A readable config file leaves the reader in the loaded state."""
        reader = _reader(config_dir)

        assert reader.config_status == ConfigFileReader.CONFIG_LOADED
        assert reader.config_name == CONFIG_NAME
        assert reader.get_value(HOST_KEY, DATABASE_SECTION) == FILE_HOST

    def test_missing_file_raises(self, config_dir: Path) -> None:
        """A config file that does not exist is reported as ConfigFileNotFound."""
        with pytest.raises(ConfigFileNotFound):
            _reader(config_dir, MISSING_NAME)

    def test_malformed_file_raises_a_parsing_error(self, config_dir: Path) -> None:
        """A file that exists but is not ini content raises the domain error, not a configparser one."""
        with pytest.raises(ConfigFileParsingError) as err:
            _reader(config_dir, MALFORMED_NAME)

        assert MALFORMED_NAME in str(err.value)

    def test_file_less_mode_is_loaded_and_has_no_file(self) -> None:
        """config_name=None serves the environment only and reports no file."""
        reader = _reader(Path('.'), None)

        assert reader.config_status == ConfigFileReader.CONFIG_LOADED
        assert (reader.config_name, reader.config_location, reader.config_file) == (None, None, None)

    def test_the_file_path_is_joined_not_concatenated(self, config_dir: Path) -> None:
        """A location without a trailing separator still resolves to the right file."""
        reader = ConfigFileReader(CONFIG_NAME, str(config_dir))

        assert reader.config_file == str(config_dir / CONFIG_NAME)
        assert reader.get_value(HOST_KEY, DATABASE_SECTION) == FILE_HOST


# -------------------------------------------------------------------------------------------------------------------- #
#                                            read_config_file / setup                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadConfigFileAndSetup:
    """The two loading primitives, driven directly."""

    def test_read_config_file_rejects_a_missing_path(self, config_dir: Path) -> None:
        """A path that is not a file raises ConfigFileNotFound."""
        reader = _reader(config_dir)

        with pytest.raises(ConfigFileNotFound):
            reader.read_config_file(str(config_dir / MISSING_NAME))

    def test_read_config_file_wraps_a_parsing_failure(self, config_dir: Path) -> None:
        """A malformed file raises ConfigFileParsingError with the configparser error chained."""
        reader = _reader(config_dir)

        with pytest.raises(ConfigFileParsingError) as err:
            reader.read_config_file(str(config_dir / MALFORMED_NAME))

        assert err.value.__cause__ is not None

    def test_setup_reports_a_missing_file_as_not_loaded(self, config_dir: Path) -> None:
        """setup() converts a missing file into the CONFIG_NOT_LOADED status."""
        reader = _reader(config_dir)
        reader.config_file = str(config_dir / MISSING_NAME)

        assert reader.setup() == ConfigFileReader.CONFIG_NOT_LOADED

    def test_setup_reports_a_readable_file_as_loaded(self, config_dir: Path) -> None:
        """setup() re-reading the real file reports CONFIG_LOADED."""
        assert _reader(config_dir).setup() == ConfigFileReader.CONFIG_LOADED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     get_value                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetValue:
    """Single-value reads: overlay precedence, casting, defaults and the error arms."""

    def test_reads_a_file_value(self, config_dir: Path) -> None:
        """A value present in the file is served."""
        assert _reader(config_dir).get_value(HOST_KEY, DATABASE_SECTION) == FILE_HOST

    def test_file_values_are_cast(self, config_dir: Path) -> None:
        """A numeric file value is served as an int, not a string."""
        assert _reader(config_dir).get_value(PORT_KEY, DATABASE_SECTION) == FILE_PORT

    @pytest.mark.parametrize('key, expected', [
        ('workers', 2),
        ('threaded', True),
        ('keepalive', None),
        ('timeout', 1.5),
    ])
    def test_every_auto_cast_kind(self, config_dir: Path, key: str, expected: Any) -> None:
        """bool / int / None / float all arrive as their Python type."""
        assert _reader(config_dir).get_value(key, WEBSERVER_SECTION) == expected

    def test_environment_overrides_the_file(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A DATAGERRY_* variable wins over the same key in the file."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(config_dir).get_value(HOST_KEY, DATABASE_SECTION) == ENV_HOST

    def test_environment_values_are_cast_too(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An overlay value is cast like a file value (it used to stay a string)."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, PORT_KEY), str(ENV_PORT))

        assert _reader(config_dir).get_value(PORT_KEY, DATABASE_SECTION) == ENV_PORT

    def test_serves_an_env_only_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A section the file does not have at all is served from the overlay."""
        monkeypatch.setenv(_env_key(ENV_ONLY_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(Path('.'), None).get_value(HOST_KEY, ENV_ONLY_SECTION) == ENV_HOST

    def test_missing_key_returns_the_default(self, config_dir: Path) -> None:
        """A default is served for a key the section does not carry."""
        assert _reader(config_dir).get_value(MISSING_KEY, DATABASE_SECTION, default='fallback') == 'fallback'

    def test_missing_key_without_default_raises_key_error(self, config_dir: Path) -> None:
        """Without a default a missing key is a KeyError."""
        with pytest.raises(KeyError):
            _reader(config_dir).get_value(MISSING_KEY, DATABASE_SECTION)

    def test_missing_section_returns_the_default(self, config_dir: Path) -> None:
        """A default also covers a section that does not exist (it used to raise SectionError)."""
        assert _reader(config_dir).get_value(HOST_KEY, GHOST_SECTION, default='fallback') == 'fallback'

    def test_an_explicit_none_default_is_served(self, config_dir: Path) -> None:
        """default=None is a real default, not 'no default given'."""
        assert _reader(config_dir).get_value(HOST_KEY, GHOST_SECTION, default=None) is None

    def test_missing_section_without_default_raises_section_error(self, config_dir: Path) -> None:
        """Without a default an unknown section is a SectionError."""
        with pytest.raises(SectionError):
            _reader(config_dir).get_value(HOST_KEY, GHOST_SECTION)

    def test_missing_key_of_an_env_only_section_raises_key_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The section is known (from the overlay), so the missing key is a KeyError, not a SectionError."""
        monkeypatch.setenv(_env_key(ENV_ONLY_SECTION, HOST_KEY), ENV_HOST)

        with pytest.raises(KeyError):
            _reader(Path('.'), None).get_value(MISSING_KEY, ENV_ONLY_SECTION)

    def test_not_loaded_raises_config_not_loaded(self, config_dir: Path) -> None:
        """A reader whose status was invalidated refuses to serve file values."""
        reader = _reader(config_dir)
        reader.config_status = ConfigFileReader.CONFIG_NOT_LOADED

        with pytest.raises(ConfigNotLoaded):
            reader.get_value(HOST_KEY, DATABASE_SECTION)

    def test_the_overlay_is_served_even_when_not_loaded(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An overlay value does not depend on the config file being loaded."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)
        reader = _reader(config_dir)
        reader.config_status = ConfigFileReader.CONFIG_NOT_LOADED

        assert reader.get_value(HOST_KEY, DATABASE_SECTION) == ENV_HOST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    get_sections                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetSections:
    """Section listing across both sources."""

    def test_lists_the_file_sections_in_order(self, config_dir: Path) -> None:
        """The file's sections are listed in file order."""
        assert _reader(config_dir).get_sections() == [DATABASE_SECTION, WEBSERVER_SECTION]

    def test_appends_env_only_sections(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A section only the overlay defines is listed after the file's own."""
        monkeypatch.setenv(_env_key(ENV_ONLY_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(config_dir).get_sections() == [DATABASE_SECTION, WEBSERVER_SECTION, ENV_ONLY_SECTION]

    def test_a_section_in_both_sources_is_listed_once(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An overlay value for a known section does not duplicate the section."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(config_dir).get_sections().count(DATABASE_SECTION) == 1

    def test_not_loaded_raises_config_not_loaded(self, config_dir: Path) -> None:
        """Listing sections requires a loaded configuration."""
        reader = _reader(config_dir)
        reader.config_status = ConfigFileReader.CONFIG_NOT_LOADED

        with pytest.raises(ConfigNotLoaded):
            reader.get_sections()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_all_values_from_section                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetAllValuesFromSection:
    """Whole-section reads - the call the boot path uses for [Database]."""

    def test_returns_every_cast_file_value(self, config_dir: Path) -> None:
        """The section is served with each value cast to its Python type."""
        assert _reader(config_dir).get_all_values_from_section(DATABASE_SECTION) == {
            HOST_KEY: FILE_HOST,
            PORT_KEY: FILE_PORT,
            NAME_KEY: FILE_DB_NAME,
        }

    def test_the_overlay_wins_on_a_shared_key(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An overlay value replaces the file's, the untouched keys stay."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(config_dir).get_all_values_from_section(DATABASE_SECTION) == {
            HOST_KEY: ENV_HOST,
            PORT_KEY: FILE_PORT,
            NAME_KEY: FILE_DB_NAME,
        }

    def test_the_overlay_can_add_a_key(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key only the overlay defines is merged into the section, cast like any other value."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, 'extra'), str(ENV_PORT))

        assert _reader(config_dir).get_all_values_from_section(DATABASE_SECTION)['extra'] == ENV_PORT

    def test_serves_an_env_only_section(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A section the file does not have is served from the overlay alone."""
        monkeypatch.setenv(_env_key(ENV_ONLY_SECTION, HOST_KEY), ENV_HOST)

        assert _reader(config_dir).get_all_values_from_section(ENV_ONLY_SECTION) == {HOST_KEY: ENV_HOST}

    def test_file_less_mode_serves_the_whole_section_from_the_overlay(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The documented env-only deployment: no config file at all, [Database] from the environment."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)
        monkeypatch.setenv(_env_key(DATABASE_SECTION, PORT_KEY), str(ENV_PORT))
        monkeypatch.setenv(_env_key(DATABASE_SECTION, NAME_KEY), FILE_DB_NAME)

        assert _reader(Path('.'), None).get_all_values_from_section(DATABASE_SECTION) == {
            HOST_KEY: ENV_HOST,
            PORT_KEY: ENV_PORT,
            NAME_KEY: FILE_DB_NAME,
        }

    def test_unknown_section_raises_section_error(self, config_dir: Path) -> None:
        """A section neither source knows is a SectionError."""
        with pytest.raises(SectionError):
            _reader(config_dir).get_all_values_from_section(GHOST_SECTION)

    def test_not_loaded_without_overlay_raises_config_not_loaded(self, config_dir: Path) -> None:
        """With no usable file and nothing in the overlay the reader reports the real cause."""
        reader = _reader(config_dir)
        reader.config_status = ConfigFileReader.CONFIG_NOT_LOADED

        with pytest.raises(ConfigNotLoaded):
            reader.get_all_values_from_section(DATABASE_SECTION)

    def test_not_loaded_with_overlay_still_serves_the_overlay(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The overlay does not depend on the file being loaded."""
        monkeypatch.setenv(_env_key(DATABASE_SECTION, HOST_KEY), ENV_HOST)
        reader = _reader(config_dir)
        reader.config_status = ConfigFileReader.CONFIG_NOT_LOADED

        assert reader.get_all_values_from_section(DATABASE_SECTION) == {HOST_KEY: ENV_HOST}
