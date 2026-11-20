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
Integration tests of ``person_sync.sync_guards.enforce_synced_objects_delete`` against a real MongoDB

Pinned: the guard reads the stored switch of the tenant the ObjectsManager names - a mapped person group is refused
while the stored group sync is on, and may go while it is off or was never configured; a linked person is refused
whatever is stored
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, SettingsManager
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION, SyncGuardProblem
from cmdb.framework.person_sync.sync_guards import enforce_synced_objects_delete
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, write_sync_settings
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_OBJECT_ID: int = 43001
PERSON_ID: int = 43002
USER_GROUP_ID: int = 43011
USER_ID: int = 43012
GROUP: dict[str, Any] = {'public_id': GROUP_OBJECT_ID, 'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}}
PERSON: dict[str, Any] = {'public_id': PERSON_ID, 'system_ref': {'kind': 'user', 'id': USER_ID}}


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[ObjectsManager]:
    """An ObjectsManager on the test tenant; the sync settings removed before and after"""
    settings_manager = SettingsManager(database_manager, database_name)
    settings_manager.delete_section(PERSON_SYNC_SETTINGS_SECTION)

    yield ObjectsManager(database_manager, database_name)

    settings_manager.delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _store(database_manager: MongoDatabaseManager, database_name: str, group_sync: bool) -> None:
    """Stores the group sync switch"""
    write_sync_settings(SettingsManager(database_manager, database_name),
                        PersonSyncSettings(groups=GroupSyncSettings(active=group_sync)))


def test_a_mapped_group_follows_the_stored_switch(objects_manager: ObjectsManager,
                                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Never configured and off: it may go; on: refused"""
    assert enforce_synced_objects_delete(objects_manager, [GROUP]) is None

    _store(database_manager, database_name, False)
    assert enforce_synced_objects_delete(objects_manager, [GROUP]) is None

    _store(database_manager, database_name, True)
    assert enforce_synced_objects_delete(objects_manager, [GROUP]) == (
        SyncGuardProblem.MAPPED_GROUP_DELETE.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID))


def test_a_linked_person_is_refused_whatever_is_stored(objects_manager: ObjectsManager) -> None:
    """No settings at all"""
    assert enforce_synced_objects_delete(objects_manager, [PERSON]) == (
        SyncGuardProblem.SYNCED_PERSON_DELETE.value.format(public_id=PERSON_ID, user_id=USER_ID))
