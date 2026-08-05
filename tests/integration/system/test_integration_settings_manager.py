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
Integration tests for the SettingsManager database-backed methods.

Covers write (create + upsert), get_section, get_sections, get_all_values_from_section (stored /
explicit default / empty-dict default / SectionError) and get_value (present / missing key / missing
section). Uses dedicated test section ids so the shared 'settings.conf' collection is not disturbed.
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

SECTION: str = 'itest_settings_section'
MISSING_SECTION: str = 'itest_settings_missing'
ALL_TEST_SECTIONS: list[str] = [SECTION, MISSING_SECTION]


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(database_manager: MongoDatabaseManager, database_name: str) -> SettingsManager:
    """Provides a SettingsManager wired to the test database."""
    return SettingsManager(database_manager, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any test sections seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
            .delete_many({'_id': {'$in': ALL_TEST_SECTIONS}})

    _purge()
    yield
    _purge()


class TestWrite:
    """SettingsManager.write creates and upserts sections."""

    def test_write_creates_section(self, settings_manager: SettingsManager) -> None:
        """Writing a new section makes its values retrievable via get_section."""
        result = settings_manager.write(SECTION, {'colour': 'red', 'size': 3})

        assert result.acknowledged
        stored = settings_manager.get_section(SECTION)
        assert stored is not None
        assert stored['colour'] == 'red'
        assert stored['size'] == 3
        # get_section reads through find(), which defaults to projection {'_id': 0}
        assert '_id' not in stored

    def test_write_upserts_existing_section(self, settings_manager: SettingsManager) -> None:
        """A second write to the same section updates the stored values."""
        settings_manager.write(SECTION, {'colour': 'red'})
        settings_manager.write(SECTION, {'colour': 'blue'})

        assert settings_manager.get_section(SECTION)['colour'] == 'blue'


class TestGetSection:
    """SettingsManager.get_section returns the section or None."""

    def test_missing_section_returns_none(self, settings_manager: SettingsManager) -> None:
        """A section that does not exist yields None."""
        assert settings_manager.get_section(MISSING_SECTION) is None


class TestGetSections:
    """SettingsManager.get_sections lists section identifiers."""

    def test_lists_written_section_id(self, settings_manager: SettingsManager) -> None:
        """A written section appears in get_sections, projected to its '_id' only."""
        settings_manager.write(SECTION, {'colour': 'red', 'size': 3})

        sections = settings_manager.get_sections()

        ids = [entry['_id'] for entry in sections]
        assert SECTION in ids
        # projection keeps only '_id'
        entry = next(entry for entry in sections if entry['_id'] == SECTION)
        assert set(entry.keys()) == {'_id'}


class TestGetAllValuesFromSection:
    """SettingsManager.get_all_values_from_section stored / default / raise behaviour."""

    def test_returns_stored_values(self, settings_manager: SettingsManager) -> None:
        """An existing section returns its full document."""
        settings_manager.write(SECTION, {'colour': 'red'})

        values = settings_manager.get_all_values_from_section(SECTION)

        assert values['colour'] == 'red'

    def test_returns_provided_default_when_missing(self, settings_manager: SettingsManager) -> None:
        """A missing section returns the provided default dict."""
        default = {'colour': 'green'}

        assert settings_manager.get_all_values_from_section(MISSING_SECTION, default) == default

    def test_empty_dict_default_is_returned(self, settings_manager: SettingsManager) -> None:
        """An empty-dict default is honoured (regression: only None means 'no default')."""
        assert settings_manager.get_all_values_from_section(MISSING_SECTION, {}) == {}

    def test_raises_when_missing_and_no_default(self, settings_manager: SettingsManager) -> None:
        """A missing section without a default raises SectionError."""
        with pytest.raises(SectionError):
            settings_manager.get_all_values_from_section(MISSING_SECTION)


class TestGetValue:
    """SettingsManager.get_value returns a single value or None."""

    def test_returns_stored_value(self, settings_manager: SettingsManager) -> None:
        """An existing key in an existing section returns its value."""
        settings_manager.write(SECTION, {'colour': 'red'})

        assert settings_manager.get_value('colour', SECTION) == 'red'

    def test_missing_key_returns_none(self, settings_manager: SettingsManager) -> None:
        """A missing key in an existing section returns None (regression: was a crash)."""
        settings_manager.write(SECTION, {'colour': 'red'})

        assert settings_manager.get_value('size', SECTION) is None

    def test_missing_section_returns_none(self, settings_manager: SettingsManager) -> None:
        """A missing section returns None (regression: was a crash)."""
        assert settings_manager.get_value('colour', MISSING_SECTION) is None
