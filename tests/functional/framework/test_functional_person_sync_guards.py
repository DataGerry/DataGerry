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
Functional tests of what the user sync keeps from being deleted or changed beneath it

Over HTTP: a linked person is not deleted - single, bulk (all or nothing) or through ``/persons``; a mapped person
group only while the group sync is off; an ordinary person goes. An empty target Type is not deleted, another empty
PERSON Type is. A target Type's update may not deactivate it or require a first name again; an update that keeps it
usable, and any update of another Type, goes through
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    write_sync_settings,
)
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_TYPE_ID: int = 9601
GROUP_TYPE_ID: int = 9602
EMPTY_TARGET_TYPE_ID: int = 9603
EMPTY_OTHER_TYPE_ID: int = 9604
TYPE_IDS: list[int] = [TARGET_TYPE_ID, GROUP_TYPE_ID, EMPTY_TARGET_TYPE_ID, EMPTY_OTHER_TYPE_ID]
SYNCED_PERSON_ID: int = 9611
HAND_PERSON_ID: int = 9612
MAPPED_GROUP_ID: int = 9613
OBJECT_IDS: list[int] = [SYNCED_PERSON_ID, HAND_PERSON_ID, MAPPED_GROUP_ID]
USER_ID: int = 1
USER_GROUP_ID: int = 1
AUTHOR_ID: int = 1
PERSON_DELETE_MESSAGE: str = 'cannot be deleted while it is linked'
GROUP_DELETE_MESSAGE: str = 'cannot be deleted while the user group sync is on'
TYPE_DELETE_MESSAGE: str = 'is a target of the user sync and cannot be deleted'
TYPE_CHANGE_MESSAGE: str = 'must stay one the sync can write into'


def _object(public_id: int, type_id: int, marker: SpecialType, fields: dict[str, Any],
            system_ref: dict[str, Any] | None) -> dict[str, Any]:
    """An object document of a person Type, linked when a system_ref is given"""
    document: dict[str, Any] = {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': AUTHOR_ID, 'version': '1.0.0',
        'special_type': marker.value, 'multi_data_sections': [],
        'fields': [{'name': name, 'value': value, 'type': 'person' if name == PersonGroupField.MEMBERS.value
                    else 'text'} for name, value in fields.items()],
    }

    if system_ref is not None:
        document['system_ref'] = system_ref

    return document


def _settings(group_sync: bool) -> PersonSyncSettings:
    """The user sync writing into TARGET_TYPE_ID, EMPTY_TARGET_TYPE_ID as the admin's override"""
    return PersonSyncSettings(
        users=UserSyncSettings(active=True, default_type_id=TARGET_TYPE_ID,
                               type_overrides={USER_ID: EMPTY_TARGET_TYPE_ID}),
        groups=GroupSyncSettings(active=group_sync),
    )


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types, a synced person, a person by hand and a mapped group; the user and group sync on"""
    database = database_manager.connector.client[database_name]
    markers = {TARGET_TYPE_ID: SpecialType.PERSON, GROUP_TYPE_ID: SpecialType.PERSON_GROUP,
               EMPTY_TARGET_TYPE_ID: SpecialType.PERSON, EMPTY_OTHER_TYPE_ID: SpecialType.PERSON}

    for type_id, marker in markers.items():
        document = build_default_person_type(marker, f'fn-sync-guard-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    names = {PersonField.DISPLAY_NAME.value: 'Ann Lee', PersonField.FIRST_NAME.value: 'Ann',
             PersonField.LAST_NAME.value: 'Lee'}
    database[CmdbObject.COLLECTION].insert_many([
        _object(SYNCED_PERSON_ID, TARGET_TYPE_ID, SpecialType.PERSON, names, {'kind': 'user', 'id': USER_ID}),
        _object(HAND_PERSON_ID, TARGET_TYPE_ID, SpecialType.PERSON, names, None),
        _object(MAPPED_GROUP_ID, GROUP_TYPE_ID, SpecialType.PERSON_GROUP,
                {PersonGroupField.NAME.value: 'Admins', PersonGroupField.MEMBERS.value: [HAND_PERSON_ID]},
                {'kind': 'user_group', 'id': USER_GROUP_ID}),
    ])
    write_sync_settings(SettingsManager(database_manager, database_name), _settings(True))

    yield database

    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': OBJECT_IDS}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': OBJECT_IDS}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _exists(db: Any, collection: str, public_id: int) -> bool:
    """Whether the document is still stored"""
    return db[collection].find_one({'public_id': public_id}) is not None


def _refused(response: Any, message: str) -> None:
    """A 400 carrying the guard's message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()
    assert message in response.get_json()['message']


class TestObjectDeletes:
    """What the sync keeps."""

    def test_a_linked_person_is_not_deleted(self, rest_api, db: Any) -> None:
        """It goes when its user does"""
        _refused(rest_api.delete(f'/objects/{SYNCED_PERSON_ID}'), PERSON_DELETE_MESSAGE)
        assert _exists(db, CmdbObject.COLLECTION, SYNCED_PERSON_ID)

    def test_a_bulk_delete_holding_one_is_refused_whole(self, rest_api, db: Any) -> None:
        """All or nothing: the person by hand stays too"""
        _refused(rest_api.delete(f'/objects/delete/{HAND_PERSON_ID},{SYNCED_PERSON_ID}'), PERSON_DELETE_MESSAGE)
        assert _exists(db, CmdbObject.COLLECTION, HAND_PERSON_ID)

    def test_the_persons_layer_is_refused_too(self, rest_api, db: Any) -> None:
        """Its delete runs the same guard"""
        _refused(rest_api.delete(f'/persons/{SYNCED_PERSON_ID}'), PERSON_DELETE_MESSAGE)

    def test_a_mapped_group_is_not_deleted_while_the_group_sync_is_on(self, rest_api, db: Any) -> None:
        """Its members are the sync's"""
        _refused(rest_api.delete(f'/objects/{MAPPED_GROUP_ID}'), GROUP_DELETE_MESSAGE)

    def test_a_mapped_group_may_go_while_the_group_sync_is_off(self, rest_api, db: Any,
                                                               database_manager: MongoDatabaseManager,
                                                               database_name: str) -> None:
        """Off means unlocked; the mapping goes with it"""
        write_sync_settings(SettingsManager(database_manager, database_name), _settings(False))

        assert rest_api.delete(f'/objects/{MAPPED_GROUP_ID}').status_code == HTTPStatus.OK
        assert not _exists(db, CmdbObject.COLLECTION, MAPPED_GROUP_ID)

    def test_a_person_by_hand_goes(self, rest_api, db: Any) -> None:
        """An ordinary object; it also leaves the group's members"""
        assert rest_api.delete(f'/objects/{HAND_PERSON_ID}').status_code == HTTPStatus.OK
        assert not _exists(db, CmdbObject.COLLECTION, HAND_PERSON_ID)


class TestTypeDeletes:
    """A chosen target stays."""

    def test_an_empty_target_type_is_not_deleted(self, rest_api, db: Any) -> None:
        """The admin's override - a type without objects"""
        _refused(rest_api.delete(f'/types/{EMPTY_TARGET_TYPE_ID}'), TYPE_DELETE_MESSAGE)
        assert _exists(db, CmdbType.COLLECTION, EMPTY_TARGET_TYPE_ID)

    def test_another_empty_person_type_goes(self, rest_api, db: Any) -> None:
        """No target, no guard"""
        assert rest_api.delete(f'/types/{EMPTY_OTHER_TYPE_ID}').status_code == HTTPStatus.ACCEPTED


class TestTypeChanges:
    """A target stays one the sync can write into."""

    @staticmethod
    def _put(rest_api, type_id: int, change: Any) -> Any:
        """Reads the Type, changes it, writes it back"""
        payload: dict[str, Any] = rest_api.get(f'/types/{type_id}').get_json()['result']
        change(payload)

        return rest_api.put(f'/types/{type_id}', json=payload)

    @staticmethod
    def _require_first_name(payload: dict[str, Any]) -> None:
        """Flags the first name required again"""
        for type_field in payload['fields']:
            if type_field['name'] == PersonField.FIRST_NAME.value:
                type_field['required'] = True

    def test_deactivating_a_target_is_refused(self, rest_api, db: Any) -> None:
        """Its objects could no longer be written"""
        _refused(self._put(rest_api, EMPTY_TARGET_TYPE_ID, lambda payload: payload.update(active=False)),
                 TYPE_CHANGE_MESSAGE)
        assert db[CmdbType.COLLECTION].find_one({'public_id': EMPTY_TARGET_TYPE_ID})['active'] is True

    def test_requiring_a_name_again_on_a_target_is_refused(self, rest_api, db: Any) -> None:
        """A user may carry no first name"""
        _refused(self._put(rest_api, TARGET_TYPE_ID, self._require_first_name), TYPE_CHANGE_MESSAGE)

    def test_a_usable_change_of_a_target_goes_through(self, rest_api, db: Any) -> None:
        """A new label"""
        response = self._put(rest_api, TARGET_TYPE_ID, lambda payload: payload.update(label='Staff'))

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_another_person_type_is_free(self, rest_api, db: Any) -> None:
        """Deactivate it, require what you like"""
        def _change(payload: dict[str, Any]) -> None:
            payload['active'] = False
            self._require_first_name(payload)

        assert self._put(rest_api, EMPTY_OTHER_TYPE_ID, _change).status_code == HTTPStatus.ACCEPTED

    def test_a_type_holding_a_linked_person_is_guarded_like_a_target(self, rest_api, db: Any) -> None:
        """A person left outside the targets is still written where it lives - its Type may not be deactivated"""
        db[CmdbObject.COLLECTION].update_one({'public_id': SYNCED_PERSON_ID},
                                             {'$set': {'type_id': EMPTY_OTHER_TYPE_ID}})

        _refused(self._put(rest_api, EMPTY_OTHER_TYPE_ID, lambda payload: payload.update(active=False)),
                 TYPE_CHANGE_MESSAGE)
        assert db[CmdbType.COLLECTION].find_one({'public_id': EMPTY_OTHER_TYPE_ID})['active'] is True
