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
Unit tests for cmdb.database.database_services.database_updater

The SettingsManager is mocked at construction so DatabaseUpdater touches no real database, and
run_updates' dynamic loader / progress bar / sleep are patched. Covers the version bookkeeping
(getters, availability check), the current-version read (stored / missing-version / no-section
fallback to MIN_CLOUD_UPDATER_VERSION) and the selective execution of pending updates.
"""
from typing import Any, Iterator
from unittest.mock import patch, MagicMock

import pytest

from cmdb.errors.system_config import SectionError
from cmdb.database.database_constants import MIN_CLOUD_UPDATER_VERSION
from cmdb.database.database_services.database_updater import DatabaseUpdater
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.database.database_services.database_updater'
UPDATER_SECTION: str = 'updater'
TEST_DB: str = 'test_db'


@pytest.fixture(name='updater')
def fixture_updater() -> Iterator[DatabaseUpdater]:
    """A DatabaseUpdater whose SettingsManager is a MagicMock (no real DB access)"""
    with patch(f'{MODULE}.SettingsManager') as settings_manager_cls:
        updater: DatabaseUpdater = DatabaseUpdater(MagicMock(), TEST_DB)
        # self.settings_manager is the mock instance the patched class produced
        updater.settings_manager = settings_manager_cls.return_value
        yield updater

# -------------------------------------------------------------------------------------------------------------------- #
#                                          version bookkeeping getters                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_updater_versions_is_sorted(updater: DatabaseUpdater) -> None:
    """The available updater versions are returned in ascending order"""
    versions: list[int] = updater.get_updater_versions()

    assert versions == sorted(versions)
    assert len(versions) > 0


def test_get_highest_update_version_is_last(updater: DatabaseUpdater) -> None:
    """The highest update version equals the last sorted version"""
    assert updater.get_highest_update_version() == updater.get_updater_versions()[-1]


def test_is_update_available_true_when_below_highest(updater: DatabaseUpdater) -> None:
    """An update is available when the stored version is below the highest known version"""
    updater.settings_manager.get_all_values_from_section.return_value = {'version': 0}

    assert updater.is_update_available() is True


def test_is_update_available_false_when_at_highest(updater: DatabaseUpdater) -> None:
    """No update is available when the stored version equals the highest known version"""
    highest: int = updater.get_highest_update_version()
    updater.settings_manager.get_all_values_from_section.return_value = {'version': highest}

    assert updater.is_update_available() is False

# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_current_update_version                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_current_update_version_returns_stored_version(updater: DatabaseUpdater) -> None:
    """The stored version is returned when the updater section carries one"""
    updater.settings_manager.get_all_values_from_section.return_value = {'version': 20250619}

    assert updater.get_current_update_version() == 20250619


def test_get_current_update_version_defaults_when_version_missing(updater: DatabaseUpdater) -> None:
    """A section without a 'version' falls back to MIN_CLOUD_UPDATER_VERSION (never None)"""
    updater.settings_manager.get_all_values_from_section.return_value = {}

    assert updater.get_current_update_version() == MIN_CLOUD_UPDATER_VERSION


def test_get_current_update_version_seeds_default_when_section_missing(updater: DatabaseUpdater) -> None:
    """With no updater section the default is written and MIN_CLOUD_UPDATER_VERSION is returned"""
    updater.settings_manager.get_all_values_from_section.side_effect = SectionError(UPDATER_SECTION)

    assert updater.get_current_update_version() == MIN_CLOUD_UPDATER_VERSION
    updater.settings_manager.write.assert_called_once_with(
        _id=UPDATER_SECTION,
        data={'_id': UPDATER_SECTION, 'version': MIN_CLOUD_UPDATER_VERSION},
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                              set_update_version                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_set_update_version_writes_payload(updater: DatabaseUpdater) -> None:
    """Setting the version writes the updater document with the new version"""
    updater.set_update_version(42)

    updater.settings_manager.write.assert_called_once_with(
        _id=UPDATER_SECTION,
        data={'_id': UPDATER_SECTION, 'version': 42},
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 run_updates                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_run_updates_runs_only_versions_above_current(updater: DatabaseUpdater) -> None:
    """Only updater versions newer than the current version are loaded and started"""
    versions: list[int] = updater.get_updater_versions()
    target_version: int = versions[-1]
    expected_path: str = f'cmdb.database.updater.versions.updater_{target_version}.Update{target_version}'

    # Current version is the second-highest, so only the highest update must run
    updater.settings_manager.get_all_values_from_section.return_value = {'version': versions[-2]}

    with patch(f'{MODULE}.load_class') as load_class, \
         patch(f'{MODULE}.process_bar'), \
         patch(f'{MODULE}.time.sleep') as sleep_mock:
        updater_instance: Any = load_class.return_value.return_value

        updater.run_updates()

        load_class.assert_called_once_with(expected_path)
        updater_instance.start_update.assert_called_once()
        sleep_mock.assert_called_once()


def test_run_updates_runs_nothing_when_current_is_highest(updater: DatabaseUpdater) -> None:
    """No updater is loaded when the database is already at the highest version"""
    highest: int = updater.get_highest_update_version()
    updater.settings_manager.get_all_values_from_section.return_value = {'version': highest}

    with patch(f'{MODULE}.load_class') as load_class, patch(f'{MODULE}.process_bar'), patch(f'{MODULE}.time.sleep'):
        updater.run_updates()

        load_class.assert_not_called()
