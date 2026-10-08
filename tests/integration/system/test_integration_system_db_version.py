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
Integration tests for ``system_helper.read_db_version`` against a real MongoDB

The database version ``GET /settings/system/`` reports is the one the updater stored in the ``updater`` settings
section. Seeds that section through the real SettingsManager collection and asserts: a recorded version is read
back, a section without a version and a missing section are ``UNKNOWN_DB_VERSION``. The stored section is restored
afterwards, since every other test runs against the same settings
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.interface.rest_api.routes.settings_routes.system_constants import (
    UNKNOWN_DB_VERSION,
    UPDATER_SETTINGS_SECTION,
    SystemInfoKey,
)
from cmdb.interface.rest_api.routes.settings_routes.system_helper import read_db_version
# -------------------------------------------------------------------------------------------------------------------- #

RECORDED_VERSION: int = 20991231
SECTION_ID_KEY: str = '_id'


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The settings collection, its updater section restored after the test"""
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    stored: dict[str, Any] | None = settings.find_one({SECTION_ID_KEY: UPDATER_SETTINGS_SECTION})
    yield settings
    settings.delete_one({SECTION_ID_KEY: UPDATER_SETTINGS_SECTION})

    if stored:
        settings.insert_one(stored)


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> SettingsManager:
    """A SettingsManager on the test database"""
    return SettingsManager(database_manager, database_name)


def test_a_recorded_version_is_read_back(settings, manager: SettingsManager) -> None:
    """What the updater wrote"""
    settings.replace_one({SECTION_ID_KEY: UPDATER_SETTINGS_SECTION},
                         {SECTION_ID_KEY: UPDATER_SETTINGS_SECTION, SystemInfoKey.VERSION.value: RECORDED_VERSION},
                         upsert=True)

    assert read_db_version(manager) == RECORDED_VERSION


def test_a_section_without_a_version_is_unknown(settings, manager: SettingsManager) -> None:
    """The section exists, the key does not"""
    settings.replace_one({SECTION_ID_KEY: UPDATER_SETTINGS_SECTION}, {SECTION_ID_KEY: UPDATER_SETTINGS_SECTION},
                         upsert=True)

    assert read_db_version(manager) == UNKNOWN_DB_VERSION


def test_a_missing_section_is_unknown(settings, manager: SettingsManager) -> None:
    """A database the updater never touched - no SectionError reaches the caller"""
    settings.delete_one({SECTION_ID_KEY: UPDATER_SETTINGS_SECTION})

    assert read_db_version(manager) == UNKNOWN_DB_VERSION
