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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests of the person sync settings against a real MongoDB

Pinned: without a stored section both syncs read as off; the settings are stored as one ``settings.conf`` section and
read back unchanged, and a second write replaces the first whole; a deleted user's override goes alone and the undo
restores it; ``find_sync_settings_problems`` judges the stored Types and users - a usable PERSON Type and the seeded
admin pass, a missing Type, a PERSON_GROUP Type as a target, a missing user and a group sync without a PERSON_GROUP
Type are named
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager, TypesManager, UsersManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION, PersonSyncProblem
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    drop_type_override,
    read_sync_settings,
    write_sync_settings,
)
from cmdb.framework.person_sync.sync_settings_rules import find_sync_settings_problems
from cmdb.framework.write_ledger import WriteLedger
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 42801
GROUP_TYPE_ID: int = 42802
MISSING_TYPE_ID: int = 42809
ADMIN_USER_ID: int = 1
MISSING_USER_ID: int = 42819


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[SettingsManager]:
    """The settings, without a person sync section before and after"""
    manager = SettingsManager(database_manager, database_name)
    manager.delete_section(PERSON_SYNC_SETTINGS_SECTION)

    yield manager

    manager.delete_section(PERSON_SYNC_SETTINGS_SECTION)


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A PERSON Type stored (no PERSON_GROUP Type: the group test adds one); removed afterwards"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, f'person-{PERSON_TYPE_ID}', PERSON_TYPE_ID)
    document['system_type'] = False
    collection.insert_one(document)

    yield

    collection.delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})


def _store_group_type(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Stores a PERSON_GROUP Type"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON_GROUP, f'group-{GROUP_TYPE_ID}',
                                                         GROUP_TYPE_ID)
    document['system_type'] = False
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(document)


def _problems(settings: PersonSyncSettings, database_manager: MongoDatabaseManager,
              database_name: str) -> list[str]:
    """The settings judged against the test database"""
    return find_sync_settings_problems(settings, TypesManager(database_manager, database_name),
                                       UsersManager(database_manager, database_name))


class TestTheSection:
    """Stored and read back."""

    def test_nothing_stored_reads_as_off(self, settings_manager: SettingsManager) -> None:
        """A fresh system chooses nothing"""
        assert read_sync_settings(settings_manager) == PersonSyncSettings()

    def test_the_settings_are_read_back_unchanged(self, settings_manager: SettingsManager) -> None:
        """One section, both halves, every override"""
        settings = PersonSyncSettings(
            users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                   type_overrides={ADMIN_USER_ID: PERSON_TYPE_ID}),
            groups=GroupSyncSettings(active=True),
        )

        write_sync_settings(settings_manager, settings)

        assert read_sync_settings(settings_manager) == settings

    def test_a_second_write_replaces_the_first(self, settings_manager: SettingsManager) -> None:
        """An override removed is gone, the switches are the new ones"""
        write_sync_settings(settings_manager, PersonSyncSettings(
            users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                   type_overrides={ADMIN_USER_ID: PERSON_TYPE_ID}),
            groups=GroupSyncSettings(active=True),
        ))
        replacement = PersonSyncSettings(users=UserSyncSettings(default_type_id=PERSON_TYPE_ID))

        write_sync_settings(settings_manager, replacement)

        assert read_sync_settings(settings_manager) == replacement


class TestADeletedUsersOverride:
    """drop_type_override"""

    def test_only_that_users_override_goes_and_the_undo_puts_it_back(self, settings_manager: SettingsManager) -> None:
        """The rest of the settings stay; the ledger restores the stored section"""
        stored = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                                           type_overrides={ADMIN_USER_ID: GROUP_TYPE_ID,
                                                                           MISSING_USER_ID: PERSON_TYPE_ID}))
        write_sync_settings(settings_manager, stored)
        ledger = WriteLedger()

        assert drop_type_override(settings_manager, ledger, MISSING_USER_ID) is True
        assert read_sync_settings(settings_manager).users.type_overrides == {ADMIN_USER_ID: GROUP_TYPE_ID}

        assert ledger.undo() == []
        assert read_sync_settings(settings_manager) == stored

    def test_a_user_without_an_override_writes_nothing(self, settings_manager: SettingsManager) -> None:
        """Nothing stored stays nothing stored"""
        assert drop_type_override(settings_manager, WriteLedger(), MISSING_USER_ID) is False
        assert settings_manager.get_section(PERSON_SYNC_SETTINGS_SECTION) is None


@pytest.mark.usefixtures('types')
class TestTheRulesOnStoredData:
    """The rules read the stored Types and users."""

    def test_a_usable_person_type_and_an_existing_user_pass(self, database_manager: MongoDatabaseManager,
                                                            database_name: str) -> None:
        """The blueprint's Type, the seeded admin"""
        settings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                                             type_overrides={ADMIN_USER_ID: PERSON_TYPE_ID}))

        assert _problems(settings, database_manager, database_name) == []

    def test_a_missing_type_a_group_type_and_a_missing_user_are_named(self, database_manager: MongoDatabaseManager,
                                                                      database_name: str) -> None:
        """Every problem at once"""
        _store_group_type(database_manager, database_name)
        settings = PersonSyncSettings(users=UserSyncSettings(
            active=True, default_type_id=MISSING_TYPE_ID, type_overrides={MISSING_USER_ID: GROUP_TYPE_ID},
        ))

        assert _problems(settings, database_manager, database_name) == [
            PersonSyncProblem.TYPE_NOT_PERSON.value.format(type_id=GROUP_TYPE_ID),
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID),
            PersonSyncProblem.OVERRIDE_USER_MISSING.value.format(user_id=MISSING_USER_ID),
        ]

    def test_the_group_sync_needs_a_person_group_type(self, database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
        """Refused without one, accepted once one is stored"""
        settings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
                                      groups=GroupSyncSettings(active=True))

        assert _problems(settings, database_manager, database_name) == [
            PersonSyncProblem.NO_PERSON_GROUP_TYPE.value,
        ]

        _store_group_type(database_manager, database_name)

        assert _problems(settings, database_manager, database_name) == []
