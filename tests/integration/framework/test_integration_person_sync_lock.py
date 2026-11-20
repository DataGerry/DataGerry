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
Integration tests of ``person_sync.sync_lock.enforce_sync_lock`` against a real MongoDB

Pinned: the lock reads the stored settings - a mapped person group is judged only while the stored group sync is on -
and finds the synced persons among the members by their stored link, so removing one is refused and removing a person
written by hand is not
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, SettingsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION, SyncLockProblem
from cmdb.framework.person_sync.sync_lock import enforce_sync_lock
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    write_sync_settings,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42901
SYNCED_PERSON_ID: int = 42911
HAND_PERSON_ID: int = 42912
GROUP_OBJECT_ID: int = 42913
USER_GROUP_ID: int = 42921
USER_ID: int = 42922


def _object(public_id: int, fields: list[dict[str, Any]], system_ref: dict[str, Any] | None) -> dict[str, Any]:
    """An object document, linked when a system_ref is given"""
    document: dict[str, Any] = {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1,
                                'fields': fields}

    if system_ref is not None:
        document['system_ref'] = system_ref

    return document


def _group(members: list[int]) -> dict[str, Any]:
    """The mapped person group with the given members"""
    return _object(GROUP_OBJECT_ID, [
        {'name': PersonGroupField.NAME.value, 'value': 'Desk', 'type': 'text'},
        {'name': PersonGroupField.MEMBERS.value, 'value': members, 'type': 'person'},
    ], {'kind': 'user_group', 'id': USER_GROUP_ID})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[ObjectsManager]:
    """A synced person and a person by hand stored; the objects and the settings removed afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.insert_many([
        _object(SYNCED_PERSON_ID, [], {'kind': 'user', 'id': USER_ID}),
        _object(HAND_PERSON_ID, [], None),
    ])

    yield ObjectsManager(database_manager, database_name)

    objects.delete_many({'public_id': {'$in': [SYNCED_PERSON_ID, HAND_PERSON_ID, GROUP_OBJECT_ID]}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _store_settings(database_manager: MongoDatabaseManager, database_name: str, group_sync: bool) -> None:
    """The user sync on, the group sync as given"""
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings(
        users=UserSyncSettings(active=True), groups=GroupSyncSettings(active=group_sync),
    ))


def test_removing_a_synced_member_is_refused_by_its_stored_link(objects_manager: ObjectsManager,
                                                                database_manager: MongoDatabaseManager,
                                                                database_name: str) -> None:
    """The member query finds the synced person; the hand-added one is free"""
    _store_settings(database_manager, database_name, True)
    stored = _group([SYNCED_PERSON_ID, HAND_PERSON_ID])

    assert enforce_sync_lock(objects_manager, _group([HAND_PERSON_ID]), stored) == (
        SyncLockProblem.GROUP_MEMBERS.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID,
                                                   added=[], removed=[SYNCED_PERSON_ID])
    )
    assert enforce_sync_lock(objects_manager, _group([SYNCED_PERSON_ID]), stored) is None


@pytest.mark.parametrize('stored_settings', [False, None], ids=['group-sync-off', 'no-section'])
def test_the_stored_switch_decides_whether_a_mapped_group_is_locked(objects_manager: ObjectsManager,
                                                                    database_manager: MongoDatabaseManager,
                                                                    database_name: str,
                                                                    stored_settings: bool | None) -> None:
    """Off, or never configured: unlocked"""
    if stored_settings is not None:
        _store_settings(database_manager, database_name, stored_settings)

    assert enforce_sync_lock(objects_manager, _group([HAND_PERSON_ID]),
                             _group([SYNCED_PERSON_ID, HAND_PERSON_ID])) is None
