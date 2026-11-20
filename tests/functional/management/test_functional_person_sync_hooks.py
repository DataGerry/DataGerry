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
Functional tests: the user management routes run the user -> person sync

Over HTTP with the sync on: creating a user creates its person (and its CREATE log), updating it updates the person,
deleting it leaves a former user; renaming a mapped user group's label renames its person group; deleting a user group
unmaps its person group and its moved members' persons leave it. With an unusable target the user create answers 500
and nothing is stored - the user write and its sync are all or nothing. With the sync off, no person is written
"""
from dataclasses import replace
from http import HTTPStatus
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    read_sync_settings,
    write_sync_settings,
)
# -------------------------------------------------------------------------------------------------------------------- #

EVENTS_HELPER_PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper'
USERS_URL: str = '/users'
GROUPS_URL: str = '/groups'
PERSON_TYPE_ID: int = 9701
GROUP_TYPE_ID: int = 9702
USER_GROUP_ID: int = 9711
TARGET_USER_GROUP_ID: int = 9712
MAPPED_GROUP_ID: int = 9721
USER_NAME: str = 'fn-sync-hook-user'
GROUP_LABEL: str = 'Service Desk'
NEW_LABEL: str = 'Help Desk'
SYNC_FAILED_MESSAGE: str = 'the user sync could not mirror the change'

ON: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
                                            groups=GroupSyncSettings(active=True))


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types, two user groups, a person group mapped to the first; the sync on"""
    database = database_manager.connector.client[database_name]

    for type_id, marker in ((PERSON_TYPE_ID, SpecialType.PERSON), (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'fn-sync-hook-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': USER_GROUP_ID, 'name': 'fn-sync-desk', 'label': GROUP_LABEL, 'rights': []},
        {'public_id': TARGET_USER_GROUP_ID, 'name': 'fn-sync-target', 'label': 'Target', 'rights': []},
    ])
    database[CmdbObject.COLLECTION].insert_one({
        'public_id': MAPPED_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
        'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID},
        'fields': [{'name': PersonGroupField.NAME.value, 'value': GROUP_LABEL, 'type': 'text'},
                   {'name': PersonGroupField.MEMBERS.value, 'value': [], 'type': 'person'}],
    })
    write_sync_settings(SettingsManager(database_manager, database_name), ON)

    yield database

    person_ids = [person['public_id'] for person in database[CmdbObject.COLLECTION].find({'type_id': PERSON_TYPE_ID})]
    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': person_ids + [MAPPED_GROUP_ID]}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [USER_GROUP_ID, TARGET_USER_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'user_name': USER_NAME})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _create_user(rest_api, **extra: Any) -> Any:
    """POST /users/ - a user in the mapped user group"""
    return rest_api.post(f'{USERS_URL}/', json={'user_name': USER_NAME, 'password': 'pw', 'active': True,
                                                'group_ids': [USER_GROUP_ID], 'first_name': 'Ann',
                                                'last_name': 'Lee', **extra})


def _person(db: Any, user_id: int) -> dict[str, Any] | None:
    """The person linked to the user"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': user_id})


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's values by field name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


def _members(db: Any) -> list[int]:
    """The mapped person group's members"""
    return _values(db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID}))[PersonGroupField.MEMBERS.value]


class TestUsers:
    """POST, PUT and DELETE /users."""

    def test_a_created_user_gets_its_person_and_its_group(self, rest_api, db: Any) -> None:
        """In the target Type, in the mapped person group, with a CREATE log"""
        response = _create_user(rest_api)

        assert response.status_code == HTTPStatus.CREATED
        person = _person(db, response.get_json()['result_id'])
        assert person['type_id'] == PERSON_TYPE_ID
        assert _values(person)[PersonField.DISPLAY_NAME.value] == 'Ann Lee'
        assert _members(db) == [person['public_id']]
        create_log: dict[str, Any] = {'object_id': person['public_id'], 'action': LogAction.CREATE.value}
        assert db[CmdbMetaLog.COLLECTION].count_documents(create_log) == 1

    def test_an_updated_user_updates_its_person(self, rest_api, db: Any) -> None:
        """The email follows"""
        user_id: int = _create_user(rest_api).get_json()['result_id']

        response = rest_api.put(f'{USERS_URL}/{user_id}', json={'email': 'ann@example.org'})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(_person(db, user_id))[PersonField.EMAIL.value] == 'ann@example.org'

    def test_a_deleted_user_leaves_a_former_user(self, rest_api, db: Any) -> None:
        """Unlinked, deactivated, out of the mapped group"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        person_id: int = _person(db, user_id)['public_id']

        assert rest_api.delete(f'{USERS_URL}/{user_id}').status_code == HTTPStatus.ACCEPTED

        former = db[CmdbObject.COLLECTION].find_one({'public_id': person_id})
        assert 'system_ref' not in former and former['active'] is False
        assert _members(db) == []
        assert db[CmdbMetaLog.COLLECTION].count_documents(
            {'object_id': person_id, 'action': LogAction.EDIT.value, 'comment': 'Unlinked from user management'}) == 1

    def test_a_deleted_user_leaves_the_mapped_group_with_the_group_sync_off(
            self, rest_api, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Unlinked it would stay as a member added by hand - it leaves whatever the switch"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        assert _members(db) == [_person(db, user_id)['public_id']]
        write_sync_settings(SettingsManager(database_manager, database_name),
                            PersonSyncSettings(users=ON.users, groups=GroupSyncSettings(active=False)))

        assert rest_api.delete(f'{USERS_URL}/{user_id}').status_code == HTTPStatus.ACCEPTED

        assert _members(db) == []

    def test_a_user_deleted_while_the_sync_is_off_leaves_a_deletable_former_user(
            self, rest_api, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Unlinked on the delete - not left locked until the sync is switched on again"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        person_id: int = _person(db, user_id)['public_id']
        write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings())

        assert rest_api.delete(f'{USERS_URL}/{user_id}').status_code == HTTPStatus.ACCEPTED

        assert 'system_ref' not in db[CmdbObject.COLLECTION].find_one({'public_id': person_id})
        assert rest_api.delete(f'/objects/{person_id}').status_code == HTTPStatus.OK

    def test_a_deleted_users_override_goes_and_the_settings_stay_writable(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Kept, the override would name a missing user and refuse every later settings write"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        settings_manager = SettingsManager(database_manager, database_name)
        write_sync_settings(settings_manager, replace(ON, users=replace(ON.users,
                                                                        type_overrides={user_id: PERSON_TYPE_ID})))

        assert rest_api.delete(f'{USERS_URL}/{user_id}').status_code == HTTPStatus.ACCEPTED

        assert read_sync_settings(settings_manager).users.type_overrides == {}
        assert rest_api.put('/person_sync/groups', json={'active': False}).status_code == HTTPStatus.ACCEPTED

    def test_a_deleted_user_reports_the_config_item_count_once(self, rest_api, monkeypatch) -> None:
        """The former user's person is a ConfigItem now; creating the user reported nothing"""
        report = MagicMock(name='handle_sync_config_item_count')
        monkeypatch.setattr(f'{EVENTS_HELPER_PATH}.handle_sync_config_item_count', report)
        user_id: int = _create_user(rest_api).get_json()['result_id']
        report.assert_not_called()

        rest_api.delete(f'{USERS_URL}/{user_id}')

        report.assert_called_once()

    def test_a_failed_sync_stores_nothing(self, rest_api, db: Any) -> None:
        """An unusable target: 500, no user, no person"""
        db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'active': False}})

        response = _create_user(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert SYNC_FAILED_MESSAGE in response.get_json()['message']
        assert db[CmdbUser.COLLECTION].find_one({'user_name': USER_NAME}) is None
        assert db[CmdbObject.COLLECTION].count_documents({'type_id': PERSON_TYPE_ID}) == 0

    def test_with_the_sync_off_no_person_is_written(self, rest_api, db: Any, database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """The pass that switches it on catches up"""
        write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings())

        user_id: int = _create_user(rest_api).get_json()['result_id']

        assert _person(db, user_id) is None


class TestSyncPending:
    """A user's sync_pending mark: answered read-only, settled by the next sync that succeeds."""

    def _mark(self, db: Any, user_id: int) -> None:
        """Marks the user as a failed sign-in sync would"""
        db[CmdbUser.COLLECTION].update_one({'public_id': user_id}, {'$set': {CmdbUserKey.SYNC_PENDING.value: True}})

    def test_the_user_read_answers_the_mark(self, rest_api, db: Any) -> None:
        """False until marked, then True"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        assert rest_api.get(f'{USERS_URL}/{user_id}').get_json()['result'][CmdbUserKey.SYNC_PENDING.value] is False

        self._mark(db, user_id)

        assert rest_api.get(f'{USERS_URL}/{user_id}').get_json()['result'][CmdbUserKey.SYNC_PENDING.value] is True

    def test_a_body_cannot_set_the_mark(self, rest_api, db: Any) -> None:
        """Dropped from the body - read-only"""
        user_id: int = _create_user(rest_api, sync_pending=True).get_json()['result_id']

        rest_api.put(f'{USERS_URL}/{user_id}', json={CmdbUserKey.SYNC_PENDING.value: True})

        assert CmdbUserKey.SYNC_PENDING.value not in db[CmdbUser.COLLECTION].find_one({'public_id': user_id})

    def test_a_user_write_whose_sync_succeeds_settles_the_mark(self, rest_api, db: Any) -> None:
        """The route's sync caught the user up"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        self._mark(db, user_id)

        response = rest_api.put(f'{USERS_URL}/{user_id}', json={'email': 'ann@example.org'})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert CmdbUserKey.SYNC_PENDING.value not in db[CmdbUser.COLLECTION].find_one({'public_id': user_id})

    def test_a_user_write_whose_sync_fails_keeps_the_mark(self, rest_api, db: Any) -> None:
        """Undone with the write"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        self._mark(db, user_id)
        db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'active': False}})

        response = rest_api.put(f'{USERS_URL}/{user_id}', json={'email': 'ann@example.org'})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert db[CmdbUser.COLLECTION].find_one({'public_id': user_id})[CmdbUserKey.SYNC_PENDING.value] is True


class TestGroups:
    """PUT and DELETE /groups."""

    def test_a_new_label_renames_the_person_group(self, rest_api, db: Any) -> None:
        """The label is the person group's name"""
        response = rest_api.put(f'{GROUPS_URL}/{USER_GROUP_ID}', json={
            'public_id': USER_GROUP_ID, 'name': 'fn-sync-desk', 'label': NEW_LABEL, 'rights': []})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID}))[
            PersonGroupField.NAME.value] == NEW_LABEL

    def test_a_deleted_user_group_is_unmapped_and_its_moved_members_leave(self, rest_api, db: Any) -> None:
        """The person group stays, unlocked; the moved member's person is out of it"""
        user_id: int = _create_user(rest_api).get_json()['result_id']
        assert _members(db) == [_person(db, user_id)['public_id']]

        response = rest_api.delete(f'{GROUPS_URL}/{USER_GROUP_ID}', query_string={
            'action': GroupDeleteMode.MOVE.value, 'group_id': TARGET_USER_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert 'system_ref' not in group
        assert db[CmdbUser.COLLECTION].find_one({'public_id': user_id})['group_ids'] == [TARGET_USER_GROUP_ID]
