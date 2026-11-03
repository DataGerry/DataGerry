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
section), and the three methods a section is used as a lock with: claim_section (create only if absent),
claim_section_where (take over only while a condition holds) and delete_section with a condition - each
pinned for its atomicity too, by threads racing on the real collection. Uses dedicated test section ids so the
shared 'settings.conf' collection is not disturbed.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

SECTION: str = 'itest_settings_section'
MISSING_SECTION: str = 'itest_settings_missing'
ALL_TEST_SECTIONS: list[str] = [SECTION, MISSING_SECTION]
RACERS: int = 8
OLD_STAMP: int = 1
NEW_STAMP: int = 2


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
    """SettingsManager.get_sections lists section names, like every SystemReader."""

    def test_lists_written_section_names(self, settings_manager: SettingsManager) -> None:
        """A written section appears by its name - a plain string, not the stored document"""
        settings_manager.write(SECTION, {'colour': 'red', 'size': 3})

        sections = settings_manager.get_sections()

        assert SECTION in sections
        assert all(isinstance(section, str) for section in sections)

    def test_each_section_is_listed_once(self, settings_manager: SettingsManager) -> None:
        """Writing a section again updates the one document instead of adding a second name"""
        settings_manager.write(SECTION, {'colour': 'red'})
        settings_manager.write(SECTION, {'colour': 'blue'})

        assert settings_manager.get_sections().count(SECTION) == 1


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


class TestClaimSection:
    """claim_section creates a section only when it does not exist yet."""

    def test_the_first_claim_creates_the_section(self, settings_manager: SettingsManager) -> None:
        """True, and the values are stored under the section's name"""
        assert settings_manager.claim_section(SECTION, {'holder': 'a'}) is True
        assert settings_manager.get_section(SECTION) == {'holder': 'a'}

    def test_a_second_claim_is_refused_and_changes_nothing(self, settings_manager: SettingsManager) -> None:
        """False, and the first claim's values stay"""
        settings_manager.claim_section(SECTION, {'holder': 'a'})

        assert settings_manager.claim_section(SECTION, {'holder': 'b'}) is False
        assert settings_manager.get_section(SECTION) == {'holder': 'a'}

    def test_exactly_one_of_concurrent_claims_wins(self, settings_manager: SettingsManager) -> None:
        """The unique _id decides, however many claim at once"""
        with ThreadPoolExecutor(max_workers=RACERS) as pool:
            won: list[bool] = list(pool.map(
                lambda racer: settings_manager.claim_section(SECTION, {'holder': racer}), range(RACERS),
            ))

        assert won.count(True) == 1
        assert settings_manager.get_section(SECTION) == {'holder': won.index(True)}


class TestClaimSectionWhere:
    """claim_section_where takes a section over only while it meets the condition."""

    def test_a_section_meeting_the_condition_is_taken_over(self, settings_manager: SettingsManager) -> None:
        """True, and the new values replace the matched ones"""
        settings_manager.claim_section(SECTION, {'holder': 'a', 'stamp': OLD_STAMP})

        assert settings_manager.claim_section_where(SECTION, {'stamp': OLD_STAMP},
                                                    {'holder': 'b', 'stamp': NEW_STAMP}) is True
        assert settings_manager.get_section(SECTION) == {'holder': 'b', 'stamp': NEW_STAMP}

    def test_a_section_not_meeting_it_is_left_alone(self, settings_manager: SettingsManager) -> None:
        """False, nothing changes"""
        settings_manager.claim_section(SECTION, {'holder': 'a', 'stamp': NEW_STAMP})

        assert settings_manager.claim_section_where(SECTION, {'stamp': OLD_STAMP}, {'holder': 'b'}) is False
        assert settings_manager.get_section(SECTION) == {'holder': 'a', 'stamp': NEW_STAMP}

    def test_a_missing_section_is_not_created(self, settings_manager: SettingsManager) -> None:
        """A takeover is no upsert"""
        assert settings_manager.claim_section_where(MISSING_SECTION, {}, {'holder': 'b'}) is False
        assert settings_manager.get_section(MISSING_SECTION) is None

    def test_exactly_one_of_concurrent_takeovers_wins(self, settings_manager: SettingsManager) -> None:
        """The first takeover ends the condition, so no second one matches"""
        settings_manager.claim_section(SECTION, {'holder': 'old', 'stamp': OLD_STAMP})

        with ThreadPoolExecutor(max_workers=RACERS) as pool:
            won: list[bool] = list(pool.map(
                lambda racer: settings_manager.claim_section_where(
                    SECTION, {'stamp': OLD_STAMP}, {'holder': racer, 'stamp': NEW_STAMP},
                ),
                range(RACERS),
            ))

        assert won.count(True) == 1
        assert settings_manager.get_section(SECTION)['holder'] == won.index(True)


class TestDeleteSectionWithCondition:
    """delete_section with a condition deletes only a section that still meets it."""

    def test_the_holder_deletes_its_section(self, settings_manager: SettingsManager) -> None:
        """The condition holds: deleted"""
        settings_manager.claim_section(SECTION, {'holder': 'a'})

        assert settings_manager.delete_section(SECTION, {'holder': 'a'}) is True
        assert settings_manager.get_section(SECTION) is None

    def test_another_holder_leaves_it(self, settings_manager: SettingsManager) -> None:
        """The section was taken over meanwhile: the late release deletes nothing"""
        settings_manager.claim_section(SECTION, {'holder': 'b'})

        assert settings_manager.delete_section(SECTION, {'holder': 'a'}) is False
        assert settings_manager.get_section(SECTION) == {'holder': 'b'}

    def test_without_a_condition_it_deletes_whatever_is_stored(self, settings_manager: SettingsManager) -> None:
        """The existing callers' behaviour"""
        settings_manager.claim_section(SECTION, {'holder': 'b'})

        assert settings_manager.delete_section(SECTION) is True
