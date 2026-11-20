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
Functional tests of the user sync's lock on the ``/objects`` write routes

A synced person's synced fields and active state are refused (400) on PUT, PATCH, the bulk PATCH, the state route and
the ``/persons`` layer -
also while the user sync is off - while its own phone number and an ordinary person stay writable. A mapped person
group's name and synced members are refused while the group sync is on; a hand-added person comes and goes, a synced
person may join an unmapped group, and with the group sync off the mapped group is free. Every refusal leaves the
stored object as it was. The caller is the administrator - no right lifts the lock
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

ROUTE_URL: str = '/objects'
PERSON_TYPE_ID: int = 9501
GROUP_TYPE_ID: int = 9502
SYNCED_PERSON_ID: int = 9511
OTHER_SYNCED_PERSON_ID: int = 9512
HAND_PERSON_ID: int = 9513
MAPPED_GROUP_ID: int = 9521
UNMAPPED_GROUP_ID: int = 9522
OBJECT_IDS: list[int] = [SYNCED_PERSON_ID, OTHER_SYNCED_PERSON_ID, HAND_PERSON_ID, MAPPED_GROUP_ID, UNMAPPED_GROUP_ID]
SYNCED_USER_ID: int = 1
OTHER_SYNCED_USER_ID: int = 9531
USER_GROUP_ID: int = 1
AUTHOR_ID: int = 1
GROUP_LABEL: str = 'Administrator'
LOCKED_MESSAGE: str = 'change only when the user changes'
ACTIVE_MESSAGE: str = 'active exactly while the user is'
GROUP_NAME_MESSAGE: str = "changes only when the user group's does"
GROUP_MEMBERS_MESSAGE: str = 'synced members change only when a user joins or leaves'


def _person(public_id: int, first_name: str, user_id: int | None) -> dict[str, Any]:
    """A person object - synced when it names a user"""
    values: dict[str, str] = {
        PersonField.DISPLAY_NAME.value: f'{first_name} Lee', PersonField.FIRST_NAME.value: first_name,
        PersonField.LAST_NAME.value: 'Lee', PersonField.PHONE_NUMBER.value: '', PersonField.EMAIL.value: '',
    }
    document: dict[str, Any] = {
        'public_id': public_id, 'type_id': PERSON_TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
        'version': '1.0.0', 'special_type': SpecialType.PERSON.value, 'multi_data_sections': [],
        'fields': [{'name': name, 'value': value, 'type': 'text'} for name, value in values.items()],
    }

    if user_id is not None:
        document['system_ref'] = {'kind': 'user', 'id': user_id}

    return document


def _group(public_id: int, members: list[int], user_group_id: int | None) -> dict[str, Any]:
    """A person group object - mapped when it names a user group"""
    document: dict[str, Any] = {
        'public_id': public_id, 'type_id': GROUP_TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
        'version': '1.0.0', 'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
        'fields': [
            {'name': PersonGroupField.NAME.value, 'value': GROUP_LABEL, 'type': 'text'},
            {'name': PersonGroupField.EMAIL.value, 'value': '', 'type': 'text'},
            {'name': PersonGroupField.MEMBERS.value, 'value': members, 'type': 'person'},
        ],
    }

    if user_group_id is not None:
        document['system_ref'] = {'kind': 'user_group', 'id': user_group_id}

    return document


def _write_settings(database_manager: MongoDatabaseManager, database_name: str, group_sync: bool) -> None:
    """Stores the sync settings: the user sync on, the group sync as given"""
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings(
        users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
        groups=GroupSyncSettings(active=group_sync),
    ))


@pytest.fixture(name='objects', autouse=True)
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The two Types, two synced persons, a person by hand, a mapped and an unmapped group; the group sync on"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    for marker, type_id in ((SpecialType.PERSON, PERSON_TYPE_ID), (SpecialType.PERSON_GROUP, GROUP_TYPE_ID)):
        document = build_default_person_type(marker, f'fn-sync-lock-{type_id}', type_id)
        document['system_type'] = False
        types.insert_one(document)

    objects.insert_many([
        _person(SYNCED_PERSON_ID, 'Ann', SYNCED_USER_ID),
        _person(OTHER_SYNCED_PERSON_ID, 'Bo', OTHER_SYNCED_USER_ID),
        _person(HAND_PERSON_ID, 'Cy', None),
        _group(MAPPED_GROUP_ID, [SYNCED_PERSON_ID, HAND_PERSON_ID], USER_GROUP_ID),
        _group(UNMAPPED_GROUP_ID, [HAND_PERSON_ID], None),
    ])
    _write_settings(database_manager, database_name, True)

    yield objects

    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
    types.delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': OBJECT_IDS}})


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """The stored document without its _id"""
    return objects.find_one({'public_id': public_id}, {'_id': 0})


def _patch(rest_api, public_id: int, name: str, value: Any) -> Any:
    """PATCH one field of one object"""
    return rest_api.patch(f'{ROUTE_URL}/{public_id}', json={'fields': [{'name': name, 'value': value}]})


def _refused(response: Any, message: str) -> None:
    """A 400 carrying the lock's message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert message in response.get_json()['message']


class TestASyncedPerson:
    """Its synced fields and active state are its user's."""

    @pytest.mark.parametrize('name', [PersonField.FIRST_NAME.value, PersonField.EMAIL.value,
                                      PersonField.DISPLAY_NAME.value])
    def test_a_patch_of_a_synced_field_is_refused(self, rest_api, objects: Any, name: str) -> None:
        """Nothing is written"""
        before = _stored(objects, SYNCED_PERSON_ID)

        _refused(_patch(rest_api, SYNCED_PERSON_ID, name, 'changed@example.org'), LOCKED_MESSAGE)
        assert _stored(objects, SYNCED_PERSON_ID) == before

    def test_a_put_of_a_synced_field_is_refused(self, rest_api, objects: Any) -> None:
        """The full replace too"""
        fields = [{'name': entry['name'], 'value': 'Changed' if entry['name'] == PersonField.LAST_NAME.value
                   else entry['value']} for entry in _stored(objects, SYNCED_PERSON_ID)['fields']]

        _refused(rest_api.put(f'{ROUTE_URL}/{SYNCED_PERSON_ID}', json={'fields': fields}), LOCKED_MESSAGE)

    def test_its_own_phone_number_is_writable(self, rest_api, objects: Any) -> None:
        """The person's own field"""
        response = _patch(rest_api, SYNCED_PERSON_ID, PersonField.PHONE_NUMBER.value, '555-0100')

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = {entry['name']: entry['value'] for entry in _stored(objects, SYNCED_PERSON_ID)['fields']}
        assert stored[PersonField.PHONE_NUMBER.value] == '555-0100'

    def test_the_state_route_is_refused(self, rest_api, objects: Any) -> None:
        """The person is active exactly while its user is"""
        _refused(rest_api.put(f'{ROUTE_URL}/state/{SYNCED_PERSON_ID}', json=False), ACTIVE_MESSAGE)
        assert _stored(objects, SYNCED_PERSON_ID)['active'] is True

    def test_a_bulk_change_of_the_active_state_is_refused_whole(self, rest_api, objects: Any) -> None:
        """All or nothing: the ordinary person keeps its state too"""
        response = rest_api.patch(f'{ROUTE_URL}/', json={'active': False},
                                  query_string={'objectIDs': [HAND_PERSON_ID, SYNCED_PERSON_ID]})

        _refused(response, ACTIVE_MESSAGE)
        assert _stored(objects, SYNCED_PERSON_ID)['active'] is True
        assert _stored(objects, HAND_PERSON_ID)['active'] is True

    def test_it_stays_locked_while_the_user_sync_is_off(self, rest_api, database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
        """Switching the sync on again overwrites nothing anyone edited"""
        write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings())

        _refused(_patch(rest_api, SYNCED_PERSON_ID, PersonField.FIRST_NAME.value, 'Bo'), LOCKED_MESSAGE)

    def test_a_person_written_by_hand_is_free(self, rest_api, objects: Any) -> None:
        """An ordinary object"""
        assert _patch(rest_api, HAND_PERSON_ID, PersonField.FIRST_NAME.value, 'Di').status_code == HTTPStatus.ACCEPTED
        assert rest_api.put(f'{ROUTE_URL}/state/{HAND_PERSON_ID}', json=False).status_code == HTTPStatus.ACCEPTED


class TestAMappedPersonGroup:
    """Its name and synced members are its user group's - while the group sync is on."""

    def test_its_name_is_refused(self, rest_api, objects: Any) -> None:
        """The user group's label decides it"""
        _refused(_patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.NAME.value, 'Desk'), GROUP_NAME_MESSAGE)

    def test_a_synced_member_is_not_removed(self, rest_api, objects: Any) -> None:
        """Nothing is written"""
        before = _stored(objects, MAPPED_GROUP_ID)

        _refused(_patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.MEMBERS.value, [HAND_PERSON_ID]),
                 GROUP_MEMBERS_MESSAGE)
        assert _stored(objects, MAPPED_GROUP_ID) == before

    def test_a_synced_person_is_not_added_by_hand(self, rest_api, objects: Any) -> None:
        """Only its user joining the user group adds it"""
        members = [SYNCED_PERSON_ID, HAND_PERSON_ID, OTHER_SYNCED_PERSON_ID]

        _refused(_patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.MEMBERS.value, members), GROUP_MEMBERS_MESSAGE)

    def test_a_hand_added_person_comes_and_goes(self, rest_api, objects: Any) -> None:
        """The group's own member"""
        response = _patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.MEMBERS.value, [SYNCED_PERSON_ID])

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_its_own_email_is_writable(self, rest_api, objects: Any) -> None:
        """Not synced"""
        response = _patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.EMAIL.value, 'desk@example.org')

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_a_synced_person_may_join_an_unmapped_group(self, rest_api, objects: Any) -> None:
        """Only the mapped groups are fixed"""
        response = _patch(rest_api, UNMAPPED_GROUP_ID, PersonGroupField.MEMBERS.value,
                          [HAND_PERSON_ID, OTHER_SYNCED_PERSON_ID])

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_with_the_group_sync_off_it_is_free(self, rest_api, objects: Any, database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """Off means unlocked: name and members"""
        _write_settings(database_manager, database_name, False)

        assert _patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.NAME.value, 'Desk').status_code == HTTPStatus.ACCEPTED
        assert _patch(rest_api, MAPPED_GROUP_ID, PersonGroupField.MEMBERS.value,
                      [HAND_PERSON_ID]).status_code == HTTPStatus.ACCEPTED


class TestThePersonsLayer:
    """``/persons`` writes through the object pipeline, so the lock holds there too."""

    def test_a_synced_persons_name_is_refused(self, rest_api, objects: Any) -> None:
        """The record's first name is the user's"""
        record = {'display_name': 'Ann Lee', 'first_name': 'Anna', 'last_name': 'Lee', 'groups': [MAPPED_GROUP_ID]}

        _refused(rest_api.put(f'/persons/{SYNCED_PERSON_ID}', json=record), LOCKED_MESSAGE)

    def test_leaving_a_mapped_group_through_the_record_is_refused(self, rest_api, objects: Any) -> None:
        """The membership write is a group update - the group's synced members are locked"""
        record = {'display_name': 'Ann Lee', 'first_name': 'Ann', 'last_name': 'Lee', 'groups': []}

        _refused(rest_api.put(f'/persons/{SYNCED_PERSON_ID}', json=record), GROUP_MEMBERS_MESSAGE)
        assert SYNCED_PERSON_ID in next(entry['value'] for entry in _stored(objects, MAPPED_GROUP_ID)['fields']
                                        if entry['name'] == PersonGroupField.MEMBERS.value)

    def test_a_refused_group_undoes_the_record_and_the_other_groups(self, rest_api, objects: Any) -> None:
        """All or none: the person's phone number (written first) and the unmapped group are put back"""
        person_before = _stored(objects, SYNCED_PERSON_ID)
        unmapped_before = _stored(objects, UNMAPPED_GROUP_ID)
        record = {'display_name': 'Ann Lee', 'first_name': 'Ann', 'last_name': 'Lee', 'phone_number': '555-0199',
                  'groups': [UNMAPPED_GROUP_ID]}

        _refused(rest_api.put(f'/persons/{SYNCED_PERSON_ID}', json=record), GROUP_MEMBERS_MESSAGE)
        assert _stored(objects, SYNCED_PERSON_ID) == person_before
        assert _stored(objects, UNMAPPED_GROUP_ID) == unmapped_before
