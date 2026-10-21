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
Unit tests for SettingsManager.get_sections

The reader interface (`SystemReader`) promises section NAMES, and the config-file and environment readers
answer them. `SettingsManager` used to answer the stored documents (`[{'_id': ...}]`) instead, so a caller
holding a reader could not treat the three alike. Pure: the database manager is a Mock
"""
from unittest.mock import Mock

from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY, SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

DATABASE_NAME: str = 'cmdb-unit'
SECTION_NAMES: list[str] = ['auth', 'date']


def _manager(documents: list[dict[str, str]]) -> tuple[SettingsManager, Mock]:
    """A SettingsManager whose collection answers `documents`, and the Mock database manager behind it"""
    dbm = Mock(name='dbm')
    dbm.db_name = DATABASE_NAME
    dbm.find_all.return_value = documents

    return SettingsManager(dbm), dbm


def test_the_section_names_are_answered() -> None:
    """One name per stored section document, as a plain string"""
    manager, _ = _manager([{SETTINGS_SECTION_ID_KEY: name} for name in SECTION_NAMES])

    assert manager.get_sections() == SECTION_NAMES


def test_only_the_section_id_is_read() -> None:
    """The settings values themselves are never loaded to list the sections"""
    manager, dbm = _manager([])

    manager.get_sections()

    assert dbm.find_all.call_args.kwargs['projection'] == {SETTINGS_SECTION_ID_KEY: 1}
    assert dbm.find_all.call_args.kwargs['collection'] == SettingsManager.COLLECTION


def test_an_empty_collection_has_no_sections() -> None:
    """Nothing stored, nothing listed"""
    manager, _ = _manager([])

    assert manager.get_sections() == []
