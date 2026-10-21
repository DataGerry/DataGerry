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
Integration tests for updater_20261021 against a real MongoDB

The old DataGerry Assistant's marker section is deleted, every other settings section stays, and a second run - like
a run on a database that never had the marker - deletes nothing
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261021 import Update20261021
from cmdb.manager.system_manager.settings_manager import SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

OLD_ASSISTANT_SECTION: str = 'datagerry_assistant'
NEIGHBOUR_SECTION: str = 'updater-20261021-neighbour'


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The marker and a neighbouring section; both removed again afterwards"""
    settings = SettingsManager(database_manager, database_name)
    settings.write(OLD_ASSISTANT_SECTION, {'claimed_by': 1})
    settings.write(NEIGHBOUR_SECTION, {'kept': True})

    yield settings

    settings.delete_section(OLD_ASSISTANT_SECTION)
    settings.delete_section(NEIGHBOUR_SECTION)


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261021(database_manager, database_name).start_update()


def test_the_marker_is_deleted_and_the_neighbour_kept(settings: SettingsManager, database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
    """Only the old assistant's section goes"""
    _run(database_manager, database_name)

    assert settings.get_section(OLD_ASSISTANT_SECTION) is None
    assert settings.get_section(NEIGHBOUR_SECTION) is not None


def test_a_second_run_changes_nothing(settings: SettingsManager, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
    """Re-run safe: nothing left to delete, no error, the neighbour still there"""
    _run(database_manager, database_name)
    _run(database_manager, database_name)

    assert settings.get_section(OLD_ASSISTANT_SECTION) is None
    assert settings.get_section(NEIGHBOUR_SECTION) is not None
