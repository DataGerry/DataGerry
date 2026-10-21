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
Unit tests for cmdb.database.updater.versions.updater_20261021

The migration deletes the old DataGerry Assistant's marker section from the settings. Its run against a real database
is its own integration test; this module owns the frozen literals, the delete it sends, the version bump and the
failure tail
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261021 as module
from cmdb.database.updater.versions.updater_20261021 import Update20261021
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY, SettingsManager
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261021
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'settings gone'


def _updater(deleted_count: int) -> tuple[Update20261021, MagicMock]:
    """The migration over a mocked database manager whose delete removes `deleted_count` documents"""
    dbm = MagicMock()
    dbm.delete.return_value = MagicMock(deleted_count=deleted_count)
    updater = Update20261021(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.SETTINGS_COLLECTION, SettingsManager.COLLECTION),
    (module.SECTION_ID_FIELD, SETTINGS_SECTION_ID_KEY),
], ids=['collection', 'section-key'])
def test_the_frozen_literals_still_match_the_settings_manager(frozen: str, live: str) -> None:
    """The literals were frozen from the settings manager's own"""
    assert frozen == live


def test_the_marker_section_name_is_frozen() -> None:
    """The section the old assistant wrote"""
    assert module.OLD_ASSISTANT_SECTION_CRITERIA == {'_id': 'datagerry_assistant'}


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater(0)

    assert updater.creation_date() == CREATION_DATE
    assert 'DataGerry Assistant' in updater.description()


@pytest.mark.parametrize('deleted_count', [1, 0], ids=['marker-present', 'no-marker'])
def test_deletes_the_marker_and_bumps_the_version(deleted_count: int) -> None:
    """One delete on the settings section; the version moves whether or not there was a marker"""
    updater, dbm = _updater(deleted_count)

    updater.start_update()

    dbm.delete.assert_called_once_with(module.SETTINGS_COLLECTION, DATABASE_NAME,
                                       module.OLD_ASSISTANT_SECTION_CRITERIA)
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_delete_is_the_updater_exception_carrying_it() -> None:
    """The failure tail wraps the exception itself, and the version does not move"""
    updater, dbm = _updater(0)
    failure = RuntimeError(DB_FAILURE)
    dbm.delete.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
