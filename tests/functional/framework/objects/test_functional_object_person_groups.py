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
Functional tests of ``GET`` / ``PATCH /objects/<public_id>/person_groups`` and of the sync link on person selections

The read answers the groups holding a person as selections, each with its ``system_ref``; a group or missing id is a
404. The change writes the groups' members - a group already as asked is left alone, each written group gets its edit
log - and refuses a group both added and removed or naming no group (400). The user sync's lock holds: a synced person
may not join a mapped group by hand (400), and a refusal undoes the groups written before it. The render and the
picker carry each selection's ``system_ref``
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

OBJECTS_URL: str = '/objects'
PICKER_URL: str = '/objects/selectable/persons'
PERSON_TYPE_ID: int = 9601
GROUP_TYPE_ID: int = 9602
SYNCED_PERSON_ID: int = 9611
HAND_PERSON_ID: int = 9612
LONER_PERSON_ID: int = 9613
UNMAPPED_GROUP_ID: int = 9621
MAPPED_GROUP_ID: int = 9622
EMPTY_GROUP_ID: int = 9623
MISSING_ID: int = 9699
OBJECT_IDS: list[int] = [SYNCED_PERSON_ID, HAND_PERSON_ID, LONER_PERSON_ID, UNMAPPED_GROUP_ID, MAPPED_GROUP_ID,
                         EMPTY_GROUP_ID]
SYNCED_USER_ID: int = 1
USER_GROUP_ID: int = 1
AUTHOR_ID: int = 1
USER_LINK: dict[str, Any] = {'kind': 'user', 'id': SYNCED_USER_ID}
GROUP_LINK: dict[str, Any] = {'kind': 'user_group', 'id': USER_GROUP_ID}
GROUP_MEMBERS_MESSAGE: str = 'synced members change only when a user joins or leaves'


def _person(public_id: int, name: str, link: dict[str, Any] | None) -> dict[str, Any]:
    """A person object - synced when it carries a link"""
    document: dict[str, Any] = {
        'public_id': public_id, 'type_id': PERSON_TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
        'version': '1.0.0', 'special_type': SpecialType.PERSON.value, 'multi_data_sections': [],
        'fields': [{'name': PersonField.DISPLAY_NAME.value, 'value': name, 'type': 'text'}],
    }

    if link is not None:
        document['system_ref'] = link

    return document


def _group(public_id: int, name: str, members: list[int], link: dict[str, Any] | None) -> dict[str, Any]:
    """A person group object - mapped when it carries a link"""
    document: dict[str, Any] = {
        'public_id': public_id, 'type_id': GROUP_TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
        'version': '1.0.0', 'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
        'fields': [
            {'name': PersonGroupField.NAME.value, 'value': name, 'type': 'text'},
            {'name': PersonGroupField.EMAIL.value, 'value': '', 'type': 'text'},
            {'name': PersonGroupField.MEMBERS.value, 'value': members, 'type': 'person'},
        ],
    }

    if link is not None:
        document['system_ref'] = link

    return document


@pytest.fixture(name='objects', autouse=True)
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two Types; a synced, a hand-added and a lonely person; an unmapped, a mapped and an empty group; both syncs on"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    for marker, type_id in ((SpecialType.PERSON, PERSON_TYPE_ID), (SpecialType.PERSON_GROUP, GROUP_TYPE_ID)):
        document = build_default_person_type(marker, f'fn-person-groups-{type_id}', type_id)
        document['system_type'] = False
        types.insert_one(document)

    objects.insert_many([
        _person(SYNCED_PERSON_ID, 'Ann', USER_LINK),
        _person(HAND_PERSON_ID, 'Cy', None),
        _person(LONER_PERSON_ID, 'Lo', None),
        _group(UNMAPPED_GROUP_ID, 'Ops', [HAND_PERSON_ID], None),
        _group(MAPPED_GROUP_ID, 'Administrator', [SYNCED_PERSON_ID, HAND_PERSON_ID], GROUP_LINK),
        _group(EMPTY_GROUP_ID, 'Empty', [], None),
    ])
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings(
        users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
        groups=GroupSyncSettings(active=True),
    ))

    yield objects

    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
    types.delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': OBJECT_IDS}})


def _members(objects: Any, group_id: int) -> list[int]:
    """A group's stored members"""
    document: dict[str, Any] = objects.find_one({'public_id': group_id})

    return next(entry['value'] for entry in document['fields'] if entry['name'] == PersonGroupField.MEMBERS.value)


def _url(person_id: int) -> str:
    """The person's groups"""
    return f'{OBJECTS_URL}/{person_id}/person_groups'


def _ids(response: Any) -> list[int]:
    """The group ids answered"""
    return [group['object_id'] for group in response.get_json()]


class TestTheRead:
    """GET /objects/<id>/person_groups"""

    def test_the_groups_holding_the_person_with_their_link(self, rest_api) -> None:
        """Ascending; a mapped group carries its user group's link, an unmapped one null"""
        response = rest_api.get(_url(HAND_PERSON_ID))

        assert response.status_code == HTTPStatus.OK
        assert [(group['object_id'], group['label'], group['kind'], group['system_ref'])
                for group in response.get_json()] == [
            (UNMAPPED_GROUP_ID, 'Ops', SpecialType.PERSON_GROUP.value, None),
            (MAPPED_GROUP_ID, 'Administrator', SpecialType.PERSON_GROUP.value, GROUP_LINK),
        ]

    def test_a_person_in_no_group(self, rest_api) -> None:
        """An empty list"""
        response = rest_api.get(_url(LONER_PERSON_ID))

        assert (response.status_code, response.get_json()) == (HTTPStatus.OK, [])

    @pytest.mark.parametrize('public_id', [UNMAPPED_GROUP_ID, MISSING_ID], ids=['a-group', 'missing'])
    def test_an_id_naming_no_person_is_a_404(self, rest_api, public_id: int) -> None:
        """Only a person has groups"""
        assert rest_api.get(_url(public_id)).status_code == HTTPStatus.NOT_FOUND


class TestTheChange:
    """PATCH /objects/<id>/person_groups"""

    def test_the_person_joins_and_leaves(self, rest_api, objects: Any) -> None:
        """Appended to the joined group, taken out of the left one; the answer is the groups afterwards"""
        response = rest_api.patch(_url(HAND_PERSON_ID), json={'add': [EMPTY_GROUP_ID], 'remove': [UNMAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.OK
        assert _ids(response) == [MAPPED_GROUP_ID, EMPTY_GROUP_ID]
        assert _members(objects, EMPTY_GROUP_ID) == [HAND_PERSON_ID]
        assert _members(objects, UNMAPPED_GROUP_ID) == []
        assert _members(objects, MAPPED_GROUP_ID) == [SYNCED_PERSON_ID, HAND_PERSON_ID]

    def test_each_written_group_gets_its_edit_log(self, rest_api, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """The object pipeline's log; a group already as asked is not written"""
        logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

        response = rest_api.patch(_url(HAND_PERSON_ID), json={'add': [EMPTY_GROUP_ID, UNMAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.OK
        assert logs.count_documents({'object_id': EMPTY_GROUP_ID}) == 1
        assert logs.count_documents({'object_id': UNMAPPED_GROUP_ID}) == 0

    def test_a_synced_person_may_join_an_unmapped_group(self, rest_api, objects: Any) -> None:
        """The lock covers mapped groups only"""
        response = rest_api.patch(_url(SYNCED_PERSON_ID), json={'add': [UNMAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.OK
        assert _members(objects, UNMAPPED_GROUP_ID) == [HAND_PERSON_ID, SYNCED_PERSON_ID]

    def test_a_synced_person_may_not_leave_a_mapped_group(self, rest_api, objects: Any) -> None:
        """Its user group decides"""
        response = rest_api.patch(_url(SYNCED_PERSON_ID), json={'remove': [MAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert GROUP_MEMBERS_MESSAGE in response.get_json()['message']
        assert _members(objects, MAPPED_GROUP_ID) == [SYNCED_PERSON_ID, HAND_PERSON_ID]

    def test_a_refusal_undoes_the_groups_written_before_it(self, rest_api, objects: Any) -> None:
        """All or nothing: the unmapped group (the lower id, written first) is put back"""
        before: dict[str, Any] = objects.find_one({'public_id': UNMAPPED_GROUP_ID}, {'_id': 0})

        response = rest_api.patch(_url(SYNCED_PERSON_ID), json={'add': [UNMAPPED_GROUP_ID],
                                                                'remove': [MAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert objects.find_one({'public_id': UNMAPPED_GROUP_ID}, {'_id': 0}) == before

    def test_a_hand_added_person_comes_and_goes_in_a_mapped_group(self, rest_api, objects: Any) -> None:
        """Only the synced members are locked"""
        response = rest_api.patch(_url(HAND_PERSON_ID), json={'remove': [MAPPED_GROUP_ID]})

        assert response.status_code == HTTPStatus.OK
        assert _members(objects, MAPPED_GROUP_ID) == [SYNCED_PERSON_ID]

    @pytest.mark.parametrize('body', [
        {'add': [EMPTY_GROUP_ID], 'remove': [EMPTY_GROUP_ID]},
        {'add': [MISSING_ID]},
        {'add': [LONER_PERSON_ID]},
        {'add': ['x']},
    ], ids=['both', 'missing', 'a-person', 'not-an-id'])
    def test_an_unusable_change_is_a_400(self, rest_api, objects: Any, body: dict[str, Any]) -> None:
        """Nothing written"""
        response = rest_api.patch(_url(HAND_PERSON_ID), json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _members(objects, EMPTY_GROUP_ID) == []

    def test_a_change_of_no_person_is_a_404(self, rest_api, objects: Any) -> None:
        """A group has no groups"""
        response = rest_api.patch(_url(UNMAPPED_GROUP_ID), json={'add': [EMPTY_GROUP_ID]})

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert _members(objects, EMPTY_GROUP_ID) == []


class TestTheSyncLinkOnSelections:
    """Each person selection says whether user management mirrors it"""

    def test_the_render_of_a_group_carries_each_members_link(self, rest_api) -> None:
        """The synced member its user's link, the hand-added one null"""
        response = rest_api.get(f'{OBJECTS_URL}/{MAPPED_GROUP_ID}')

        assert response.status_code == HTTPStatus.OK
        members = next(field for field in response.get_json()['fields']
                       if field['name'] == PersonGroupField.MEMBERS.value)
        assert [(person['object_id'], person['system_ref']) for person in members['persons']] == [
            (SYNCED_PERSON_ID, USER_LINK), (HAND_PERSON_ID, None),
        ]

    def test_the_picker_carries_each_link(self, rest_api) -> None:
        """Persons and groups alike"""
        response = rest_api.get(f'{PICKER_URL}?ids={SYNCED_PERSON_ID},{HAND_PERSON_ID},{MAPPED_GROUP_ID}')

        assert response.status_code == HTTPStatus.OK
        assert {result['object_id']: result['system_ref'] for result in response.get_json()['results']} == {
            SYNCED_PERSON_ID: USER_LINK, HAND_PERSON_ID: None, MAPPED_GROUP_ID: GROUP_LINK,
        }
