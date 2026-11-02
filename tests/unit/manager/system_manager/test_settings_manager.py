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
Unit tests for SettingsManager.get_sections and the conditional section writes

The reader interface (`SystemReader`) promises section NAMES, and the config-file and environment readers
answer them. `SettingsManager` used to answer the stored documents (`[{'_id': ...}]`) instead, so a caller
holding a reader could not treat the three alike. The conditional writes - `claim_section_where` and
`delete_section` with a condition - must match the section by its `_id` AND the condition, so a caller's
condition can never widen the write to another section. Pure: the database manager is a Mock
"""
from types import SimpleNamespace
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


CONDITION: dict[str, str] = {'holder': 'token-a'}
VALUES: dict[str, str] = {'holder': 'token-b'}


def test_claim_section_where_matches_the_section_and_the_condition() -> None:
    """One update on _id + condition, setting the values; True when it matched"""
    manager, dbm = _manager([])
    dbm.update.return_value = SimpleNamespace(matched_count=1)

    assert manager.claim_section_where(SECTION_NAMES[0], CONDITION, VALUES) is True

    dbm.update.assert_called_once_with(
        SettingsManager.COLLECTION, None, {**CONDITION, SETTINGS_SECTION_ID_KEY: SECTION_NAMES[0]}, VALUES,
    )


def test_claim_section_where_answers_false_when_nothing_matched() -> None:
    """Missing, or no longer meeting the condition"""
    manager, dbm = _manager([])
    dbm.update.return_value = SimpleNamespace(matched_count=0)

    assert manager.claim_section_where(SECTION_NAMES[0], CONDITION, VALUES) is False


def test_a_condition_cannot_name_another_section() -> None:
    """The section's own _id wins over an `_id` the condition carries"""
    manager, dbm = _manager([])
    dbm.update.return_value = SimpleNamespace(matched_count=0)
    dbm.delete.return_value = SimpleNamespace(deleted_count=0)

    manager.claim_section_where(SECTION_NAMES[0], {SETTINGS_SECTION_ID_KEY: SECTION_NAMES[1]}, VALUES)
    manager.delete_section(SECTION_NAMES[0], {SETTINGS_SECTION_ID_KEY: SECTION_NAMES[1]})

    assert dbm.update.call_args.args[2][SETTINGS_SECTION_ID_KEY] == SECTION_NAMES[0]
    assert dbm.delete.call_args.args[2][SETTINGS_SECTION_ID_KEY] == SECTION_NAMES[0]


def test_delete_section_with_a_condition_adds_it_to_the_criteria() -> None:
    """Deleted only while the section still meets the condition"""
    manager, dbm = _manager([])
    dbm.delete.return_value = SimpleNamespace(deleted_count=1)

    assert manager.delete_section(SECTION_NAMES[0], CONDITION) is True

    dbm.delete.assert_called_once_with(
        SettingsManager.COLLECTION, None, {**CONDITION, SETTINGS_SECTION_ID_KEY: SECTION_NAMES[0]},
    )


def test_delete_section_without_one_matches_the_id_alone() -> None:
    """The existing callers' criteria are unchanged"""
    manager, dbm = _manager([])
    dbm.delete.return_value = SimpleNamespace(deleted_count=0)

    assert manager.delete_section(SECTION_NAMES[0]) is False

    dbm.delete.assert_called_once_with(SettingsManager.COLLECTION, None, {SETTINGS_SECTION_ID_KEY: SECTION_NAMES[0]})
