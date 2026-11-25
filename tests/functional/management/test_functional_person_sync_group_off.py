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
Functional tests: the user group sync switched off, a user group unmapped, a mapped user group deleted

Over HTTP, from both syncs on with one mapped person group holding a synced and a hand-added person. Switching the
group sync off keeps the mapping, the name, the members and the persons' active state, and unlocks the group; while
off, a user leaving the user group or the user group renamed leaves the person group as it is; switching back on
restores the name and the synced members and keeps the hand-added one. A re-map (the user group adopts another
person group) or deleting the user group removes the link only: members kept, persons active, the group free
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
# -------------------------------------------------------------------------------------------------------------------- #

SYNC_URL: str = '/person_sync'
PERSON_TYPE_ID: int = 9901
GROUP_TYPE_ID: int = 9902
GROUP_ON: dict[str, Any] = {'active': True, 'default_type_id': GROUP_TYPE_ID}
GROUP_OFF: dict[str, Any] = {**GROUP_ON, 'active': False}
USER_GROUP_ID: int = 9911
OTHER_USER_GROUP_ID: int = 9912
USER_ID: int = 9921
MAPPED_GROUP_ID: int = 9931
ADOPTED_GROUP_ID: int = 9981
HAND_PERSON_ID: int = 9932
LABEL: str = 'Night Shift'
HAND_NAME: str = 'Renamed by hand'
MEMBERS: str = PersonGroupField.MEMBERS.value
NAME: str = PersonGroupField.NAME.value


@pytest.fixture(name='db', autouse=True)
def fixture_db(rest_api, database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Both syncs on through the routes; the person group mapped, holding the user's person and a hand-added one"""
    database = database_manager.connector.client[database_name]

    for type_id, marker in ((PERSON_TYPE_ID, SpecialType.PERSON), (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'fn-sync-off-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': USER_GROUP_ID, 'name': 'fn-sync-night', 'label': LABEL, 'rights': []},
        {'public_id': OTHER_USER_GROUP_ID, 'name': 'fn-sync-day', 'label': 'Day Shift', 'rights': []},
    ])
    database[CmdbUser.COLLECTION].insert_one({
        'public_id': USER_ID, 'user_name': 'fn-sync-off', 'active': True,
        'group_ids': [USER_GROUP_ID, OTHER_USER_GROUP_ID], 'registration_time': datetime.now(timezone.utc),
    })
    database[CmdbObject.COLLECTION].insert_many([{
        'public_id': HAND_PERSON_ID, 'type_id': PERSON_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'special_type': SpecialType.PERSON.value, 'multi_data_sections': [],
        'fields': [{'name': 'display_name', 'value': 'Hand', 'type': 'text'}],
    }, {
        'public_id': MAPPED_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
        'fields': [{'name': NAME, 'value': 'old', 'type': 'text'},
                   {'name': MEMBERS, 'value': [HAND_PERSON_ID], 'type': 'person'}],
    }])
    rest_api.put(f'{SYNC_URL}/users', json={'active': True, 'default_type_id': PERSON_TYPE_ID, 'type_overrides': []})
    # Adopted before the group sync goes on, which gives every other user group a person group of its own
    assert rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}',
                        json={'person_group_id': MAPPED_GROUP_ID}).status_code == HTTPStatus.ACCEPTED
    rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

    yield database

    object_ids = [document['public_id'] for document in database[CmdbObject.COLLECTION].find(
        {'$or': [{'type_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}}, {'system_ref': {'$exists': True}}]})]
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': object_ids}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': object_ids}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [USER_GROUP_ID, OTHER_USER_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': USER_ID})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _group(db: Any) -> dict[str, Any]:
    """The mapped person group as stored"""
    return db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})


def _values(db: Any) -> dict[str, Any]:
    """Its values by field name"""
    return {entry['name']: entry['value'] for entry in _group(db)['fields']}


def _person_id(db: Any) -> int:
    """The user's person"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': USER_ID})['public_id']


def _person_active(db: Any) -> bool:
    """Whether the user's person is active"""
    return db[CmdbObject.COLLECTION].find_one({'public_id': _person_id(db)})['active']


def _patch(rest_api, name: str, value: Any) -> Any:
    """PATCH one field of the mapped person group"""
    return rest_api.patch(f'/objects/{MAPPED_GROUP_ID}', json={'fields': [{'name': name, 'value': value}]})


def test_the_group_starts_synced_and_locked(rest_api, db: Any) -> None:
    """The label, both members; a hand rename refused"""
    assert _values(db)[NAME] == LABEL
    assert sorted(_values(db)[MEMBERS]) == sorted([_person_id(db), HAND_PERSON_ID])
    assert _patch(rest_api, NAME, HAND_NAME).status_code == HTTPStatus.BAD_REQUEST


class TestGroupSyncOff:
    """PUT /person_sync/groups {active: false}."""

    def test_everything_is_kept(self, rest_api, db: Any) -> None:
        """The mapping listed, the link, the name, the members, the person active"""
        before: dict[str, Any] = _values(db)

        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert {'user_group_id': USER_GROUP_ID, 'person_group_id': MAPPED_GROUP_ID} in response.get_json()['result'][
            'mappings']
        assert _group(db)['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert _values(db) == before
        assert _person_active(db) is True

    def test_the_group_is_free(self, rest_api, db: Any) -> None:
        """Its name and its synced member may change by hand"""
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)

        assert _patch(rest_api, NAME, HAND_NAME).status_code == HTTPStatus.ACCEPTED
        assert _patch(rest_api, MEMBERS, [HAND_PERSON_ID]).status_code == HTTPStatus.ACCEPTED
        assert _values(db)[NAME] == HAND_NAME

    def test_a_user_leaving_the_user_group_leaves_the_group_as_it_is(self, rest_api, db: Any) -> None:
        """The hooks do not touch person groups while the group sync is off"""
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)
        members: list[int] = _values(db)[MEMBERS]

        response = rest_api.put(f'/users/{USER_ID}', json={'group_ids': [OTHER_USER_GROUP_ID]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(db)[MEMBERS] == members

    def test_renaming_the_user_group_leaves_the_name_as_it_is(self, rest_api, db: Any) -> None:
        """The label is synced only while the group sync is on"""
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)

        response = rest_api.put(f'/groups/{USER_GROUP_ID}', json={
            'public_id': USER_GROUP_ID, 'name': 'fn-sync-night', 'label': 'Late Shift', 'rights': []})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(db)[NAME] == LABEL

    def test_switching_back_on_restores_the_name_and_the_synced_members(self, rest_api, db: Any) -> None:
        """The hand-added person stays; the synced one is back; the label wins"""
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)
        _patch(rest_api, NAME, HAND_NAME)
        _patch(rest_api, MEMBERS, [HAND_PERSON_ID])

        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(db)[NAME] == LABEL
        assert sorted(_values(db)[MEMBERS]) == sorted([_person_id(db), HAND_PERSON_ID])


class TestUnmap:
    """A re-map (the user group adopts another person group) and DELETE /groups/<id>, with the group sync on."""

    @staticmethod
    def _re_map(rest_api, db: Any) -> None:
        """The user group adopts another person group; the mapped one is unlinked"""
        db[CmdbObject.COLLECTION].insert_one({
            'public_id': ADOPTED_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True,
            'version': '1.0.0', 'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
            'fields': [{'name': NAME, 'value': 'adopted', 'type': 'text'}, {'name': MEMBERS, 'value': [],
                                                                            'type': 'person'}]})

        assert rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}',
                            json={'person_group_id': ADOPTED_GROUP_ID}).status_code == HTTPStatus.ACCEPTED

    def test_a_re_map_removes_the_previous_link_only(self, rest_api, db: Any) -> None:
        """Members kept, person active, the group free"""
        before: dict[str, Any] = _values(db)

        self._re_map(rest_api, db)

        assert 'system_ref' not in _group(db)
        assert _values(db) == before
        assert _person_active(db) is True
        assert _patch(rest_api, NAME, HAND_NAME).status_code == HTTPStatus.ACCEPTED

    def test_an_unlinked_group_is_left_alone_by_the_sync(self, rest_api, db: Any) -> None:
        """A resync and a user leaving change nothing on it"""
        self._re_map(rest_api, db)
        before: dict[str, Any] = _values(db)

        rest_api.put(f'/users/{USER_ID}', json={'group_ids': [OTHER_USER_GROUP_ID]})
        rest_api.post(f'{SYNC_URL}/resync')

        assert _values(db) == before

    def test_deleting_the_user_group_unmaps_it(self, rest_api, db: Any) -> None:
        """The link goes; the members and the person stay"""
        before: dict[str, Any] = _values(db)

        response = rest_api.delete(f'/groups/{USER_GROUP_ID}', query_string={
            'action': GroupDeleteMode.MOVE.value, 'group_id': OTHER_USER_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert 'system_ref' not in _group(db)
        assert _values(db) == before
        assert _person_active(db) is True
