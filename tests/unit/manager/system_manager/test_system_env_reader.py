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
Unit tests for SystemEnvironmentReader

The half of the configuration stack that reads `DATAGERRY_<SECTION>_<NAME>` environment variables.
`ConfigFileReader` builds one at construction and consults it ahead of the config file, so what this
class collects is what overrides `etc/cmdb.conf` in a containerised deployment.

It snapshots `os.environ` in its constructor, so every test sets the environment before building one.
`get_value` had no coverage: `ConfigFileReader` reaches for `get_sections` and
`get_all_values_from_section` instead, and nothing else reads a single value through this class.
"""
import pytest

from cmdb.manager.system_manager.system_env_reader import SystemEnvironmentReader
# -------------------------------------------------------------------------------------------------------------------- #

SECTION: str = 'Database'
NAME: str = 'port'
VALUE: str = '27017'


@pytest.fixture(name='clean_env')
def fixture_clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Removes every DATAGERRY_ variable so a test only sees what it sets itself."""
    import os  # pylint: disable=import-outside-toplevel

    for key in [key for key in os.environ if key.startswith('DATAGERRY_')]:
        monkeypatch.delenv(key, raising=False)

    return monkeypatch


class TestGetValue:
    """Reading one setting out of the collected environment."""

    def test_reads_a_collected_value(self, clean_env: pytest.MonkeyPatch) -> None:
        """`DATAGERRY_<SECTION>_<NAME>` is addressed by its section and name, not by the raw key."""
        clean_env.setenv(f'DATAGERRY_{SECTION}_{NAME}', VALUE)

        assert SystemEnvironmentReader().get_value(NAME, SECTION) == VALUE

    def test_the_name_may_contain_underscores(self, clean_env: pytest.MonkeyPatch) -> None:
        """The pattern is greedy on the name half, which is how `connection_timeout` survives."""
        clean_env.setenv(f'DATAGERRY_{SECTION}_connection_timeout', '30')

        assert SystemEnvironmentReader().get_value('connection_timeout', SECTION) == '30'

    def test_an_unknown_name_raises(self, clean_env: pytest.MonkeyPatch) -> None:
        """
        A missing setting is a KeyError, not None

        `ConfigFileReader` does not call this method - it merges whole sections instead - so nothing
        currently depends on which of the two it is. Recorded rather than changed.
        """
        clean_env.setenv(f'DATAGERRY_{SECTION}_{NAME}', VALUE)

        with pytest.raises(KeyError):
            SystemEnvironmentReader().get_value('no-such-name', SECTION)

    def test_an_unknown_section_raises(
            self, clean_env: pytest.MonkeyPatch) -> None:  # pylint: disable=unused-argument
        """A section nothing declared is absent from the collected map entirely."""
        with pytest.raises(KeyError):
            SystemEnvironmentReader().get_value(NAME, 'NoSuchSection')


class TestWhatItCollects:
    """Only `DATAGERRY_`-prefixed variables, grouped by section."""

    def test_ignores_unrelated_variables(self, clean_env: pytest.MonkeyPatch) -> None:
        """The process environment carries hundreds of variables that are none of its business."""
        clean_env.setenv('PATH_TO_SOMETHING', 'ignored')
        clean_env.setenv(f'DATAGERRY_{SECTION}_{NAME}', VALUE)

        assert list(SystemEnvironmentReader().get_sections()) == [SECTION]

    def test_groups_several_names_under_one_section(self, clean_env: pytest.MonkeyPatch) -> None:
        """One section usually carries every setting of a component."""
        clean_env.setenv(f'DATAGERRY_{SECTION}_{NAME}', VALUE)
        clean_env.setenv(f'DATAGERRY_{SECTION}_host', 'localhost')

        values = SystemEnvironmentReader().get_all_values_from_section(SECTION)

        assert values == {NAME: VALUE, 'host': 'localhost'}

    # clean_env is what makes this test meaningful - it strips the DATAGERRY_ variables the
    # environment may already carry - even though the body never touches the fixture itself
    def test_no_datagerry_variables_is_no_sections(
            self, clean_env: pytest.MonkeyPatch) -> None:  # pylint: disable=unused-argument
        """The ordinary on-premise case: everything comes from the config file."""
        assert not list(SystemEnvironmentReader().get_sections())
