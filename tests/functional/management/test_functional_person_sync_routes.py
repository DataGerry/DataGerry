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
Functional tests: the person sync routes

Over HTTP: the settings read off by default; switching the user sync on mirrors every user and stores the settings,
a problem refuses with nothing written; switching it off deactivates the persons and the group sync; a linked person
keeps its Type; the group sync needs the user sync; mapping a user group to a new or an existing person group, refused
twice, and unmapping it; the resync; a user's person; a target change - the check, a move, a blocked person cancelling
or copied; the right. A Type ACL a test sets is also stored as the access rules it translates to
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_settings import read_sync_settings
from tests.utils.type_access_seed import remove_type_access_of_types, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

SYNC_URL: str = '/person_sync'
EVENTS_HELPER_PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper'
ADMIN_ID: int = 1
PERSON_TYPE_ID: int = 9801
OTHER_PERSON_TYPE_ID: int = 9802
GROUP_TYPE_ID: int = 9803
GROUP_ON: dict[str, Any] = {'active': True, 'default_type_id': GROUP_TYPE_ID}
GROUP_OFF: dict[str, Any] = {**GROUP_ON, 'active': False}
MISSING_TYPE_ID: int = 9899
USER_GROUP_ID: int = 9811
RIGHTLESS_GROUP_ID: int = 9812
RIGHTLESS_USER_ID: int = 9813
ADMIN_USER_ID: int = 1
EXISTING_GROUP_ID: int = 9821
PLAIN_OBJECT_ID: int = 9822
MISSING_ID: int = 9898
GROUP_LABEL: str = 'Field Service'
OWN_FIELD: str = 'badge'
SYNC_RIGHT_REFUSAL: str = 'User has not the required right base.user-management.sync.edit'

ON: dict[str, Any] = {'active': True, 'default_type_id': PERSON_TYPE_ID, 'type_overrides': []}
OFF: dict[str, Any] = {**ON, 'active': False}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two PERSON Types, a PERSON_GROUP Type, a user group, a rightless user, a free person group, a plain object"""
    database = database_manager.connector.client[database_name]

    for type_id, marker in ((PERSON_TYPE_ID, SpecialType.PERSON), (OTHER_PERSON_TYPE_ID, SpecialType.PERSON),
                            (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'fn-sync-routes-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': USER_GROUP_ID, 'name': 'fn-sync-field', 'label': GROUP_LABEL, 'rights': []},
        {'public_id': RIGHTLESS_GROUP_ID, 'name': 'fn-sync-none', 'label': 'None', 'rights': []},
    ])
    database[CmdbUser.COLLECTION].insert_one({
        'public_id': RIGHTLESS_USER_ID, 'user_name': 'fn-sync-rightless', 'active': True,
        'group_ids': [RIGHTLESS_GROUP_ID, USER_GROUP_ID], 'registration_time': datetime.now(timezone.utc),
    })
    database[CmdbObject.COLLECTION].insert_many([{
        'public_id': EXISTING_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
        'fields': [{'name': PersonGroupField.NAME.value, 'value': 'Old name', 'type': 'text'},
                   {'name': PersonGroupField.MEMBERS.value, 'value': [], 'type': 'person'}],
    }, {
        'public_id': PLAIN_OBJECT_ID, 'type_id': PERSON_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'special_type': SpecialType.PERSON.value, 'multi_data_sections': [], 'fields': [],
    }])

    yield database

    type_ids: list[int] = [PERSON_TYPE_ID, OTHER_PERSON_TYPE_ID, GROUP_TYPE_ID]
    remove_type_access_of_types(database, type_ids)
    object_ids = [document['public_id'] for document in database[CmdbObject.COLLECTION].find(
        {'$or': [{'type_id': {'$in': type_ids}}, {'system_ref': {'$exists': True}}]})]
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': object_ids}})
    database[CmdbMetaLog.COLLECTION].delete_many({'object_id': {'$in': object_ids}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': type_ids}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [USER_GROUP_ID, RIGHTLESS_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': RIGHTLESS_USER_ID})
    database[CmdbUser.COLLECTION].update_many({}, {'$unset': {CmdbUserKey.SYNC_PENDING.value: ''}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _person(db: Any, user_id: int) -> dict[str, Any] | None:
    """The person linked to the user"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': user_id})


def _object(db: Any, public_id: int) -> dict[str, Any]:
    """An object as stored"""
    return db[CmdbObject.COLLECTION].find_one({'public_id': public_id})


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's values by field name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


def _switch_on(rest_api) -> Any:
    """PUT /person_sync/users - on, into the first PERSON Type"""
    return rest_api.put(f'{SYNC_URL}/users', json=ON)


class TestUserSync:
    """GET / PUT /person_sync/users."""

    def test_the_settings_read_off_by_default(self, rest_api) -> None:
        """Never written: off, unchosen"""
        response = rest_api.get(f'{SYNC_URL}/users')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'] == {'active': False, 'default_type_id': None, 'type_overrides': []}

    def test_switching_on_mirrors_every_user_and_stores_the_settings(self, rest_api, db: Any,
                                                                      database_manager: MongoDatabaseManager,
                                                                      database_name: str) -> None:
        """The admin and the rightless user get a person; the counts are answered; GET reads the settings"""
        response = _switch_on(rest_api)

        assert response.status_code == HTTPStatus.ACCEPTED
        body: dict[str, Any] = response.get_json()
        assert body['result'] == ON
        assert body['created'] >= 2
        assert _person(db, ADMIN_ID)['type_id'] == PERSON_TYPE_ID
        assert _person(db, RIGHTLESS_USER_ID)['active'] is True
        assert read_sync_settings(SettingsManager(database_manager, database_name)).users.active is True
        assert rest_api.get(f'{SYNC_URL}/users').get_json()['result'] == ON

    def test_a_second_switch_on_writes_nothing(self, rest_api) -> None:
        """Every fingerprint unchanged"""
        _switch_on(rest_api)

        body: dict[str, Any] = _switch_on(rest_api).get_json()

        assert (body['created'], body['edited']) == (0, 0)

    def test_a_missing_target_is_refused_with_nothing_written(self, rest_api, db: Any) -> None:
        """400 naming the Type; no person, no settings"""
        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'default_type_id': MISSING_TYPE_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Type {MISSING_TYPE_ID} does not exist' in response.get_json()['message']
        assert _person(db, ADMIN_ID) is None
        assert rest_api.get(f'{SYNC_URL}/users').get_json()['result']['active'] is False

    def test_a_user_overridden_twice_is_refused(self, rest_api) -> None:
        """One override per user"""
        overrides: list[dict[str, int]] = [{'user_id': ADMIN_ID, 'type_id': PERSON_TYPE_ID},
                                           {'user_id': ADMIN_ID, 'type_id': OTHER_PERSON_TYPE_ID}]

        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'type_overrides': overrides})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Users [{ADMIN_ID}] carry more than one type override' in response.get_json()['message']

    def test_an_override_places_its_user_in_its_type(self, rest_api, db: Any) -> None:
        """The rightless user's person goes into the other Type"""
        overrides: list[dict[str, int]] = [{'user_id': RIGHTLESS_USER_ID, 'type_id': OTHER_PERSON_TYPE_ID}]

        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'type_overrides': overrides})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _person(db, RIGHTLESS_USER_ID)['type_id'] == OTHER_PERSON_TYPE_ID
        assert _person(db, ADMIN_ID)['type_id'] == PERSON_TYPE_ID

    def test_a_new_default_moves_the_persons_keeping_their_ids(self, rest_api, db: Any) -> None:
        """Nothing blocks: every person moves, its id kept, nothing created"""
        _switch_on(rest_api)
        person_id: int = _person(db, ADMIN_ID)['public_id']

        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'default_type_id': OTHER_PERSON_TYPE_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        body: dict[str, Any] = response.get_json()
        assert (body['created'], body['copied']) == (0, 0)
        assert body['moved'] >= 2
        moved: dict[str, Any] = _person(db, ADMIN_ID)
        assert (moved['public_id'], moved['type_id'], moved['active']) == (person_id, OTHER_PERSON_TYPE_ID, True)
        assert 'sync_hash' in moved

    def test_switching_off_deactivates_the_persons_and_the_group_sync(self, rest_api, db: Any) -> None:
        """Persons inactive and still linked; the group sync off with it"""
        _switch_on(rest_api)
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        response = rest_api.put(f'{SYNC_URL}/users', json=OFF)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['edited'] >= 2
        assert _person(db, ADMIN_ID)['active'] is False
        assert 'sync_hash' not in _person(db, ADMIN_ID)
        assert rest_api.get(f'{SYNC_URL}/groups').get_json()['result']['active'] is False

    def test_an_invalid_body_is_refused(self, rest_api) -> None:
        """Every key is required"""
        response = rest_api.put(f'{SYNC_URL}/users', json={'active': True})

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGroupSync:
    """GET / PUT /person_sync/groups."""

    def test_the_group_sync_needs_the_user_sync(self, rest_api) -> None:
        """400 while the user sync is off"""
        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'needs the user sync' in response.get_json()['message']

    def test_switching_on_names_the_mapped_groups_and_creates_the_others(self, rest_api, db: Any) -> None:
        """The adopted person group takes its user group's label; every other user group gets one in the default"""
        _switch_on(rest_api)
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)
        result: dict[str, Any] = response.get_json()['result']
        mapped: dict[int, int] = {entry['user_group_id']: entry['person_group_id'] for entry in result['mappings']}

        assert response.status_code == HTTPStatus.ACCEPTED
        assert (result['active'], result['default_type_id'], mapped[USER_GROUP_ID]) == (
            True, GROUP_TYPE_ID, EXISTING_GROUP_ID)
        assert set(mapped) == {group['public_id'] for group in db[CmdbUserGroup.COLLECTION].find()}
        assert {_object(db, person_group)['type_id'] for user_group, person_group in mapped.items()
                if user_group != USER_GROUP_ID} == {GROUP_TYPE_ID}
        assert response.get_json()['created'] == len(mapped) - 1
        assert _values(_object(db, EXISTING_GROUP_ID))[PersonGroupField.NAME.value] == GROUP_LABEL


class TestGroupSyncDefault:
    """The group sync's default Type - stored, answered, judged."""

    def test_it_is_stored_and_answered_while_off(self, rest_api) -> None:
        """Chosen while off: judged, kept"""
        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_OFF)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert rest_api.get(f'{SYNC_URL}/groups').get_json()['result']['default_type_id'] == GROUP_TYPE_ID

    def test_the_body_must_carry_it(self, rest_api) -> None:
        """Every key is required"""
        assert rest_api.put(f'{SYNC_URL}/groups', json={'active': False}).status_code == HTTPStatus.BAD_REQUEST

    def test_on_without_it_is_refused(self, rest_api) -> None:
        """Named"""
        _switch_on(rest_api)
        response = rest_api.put(f'{SYNC_URL}/groups', json={'active': True, 'default_type_id': None})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'default person group Type' in response.get_json()['message']

    @pytest.mark.parametrize('active', [True, False], ids=['on', 'off'])
    def test_a_person_type_is_refused_on_or_off(self, rest_api, active: bool) -> None:
        """No PERSON_GROUP marker"""
        _switch_on(rest_api)
        response = rest_api.put(f'{SYNC_URL}/groups', json={'active': active, 'default_type_id': PERSON_TYPE_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'PERSON_GROUP' in response.get_json()['message']


class TestMappings:
    """PUT /person_sync/groups/<user_group_id> - adopting an existing person group; there is no unmap."""

    def test_a_re_map_unlinks_the_created_group_and_adopts_the_existing_one(self, rest_api, db: Any) -> None:
        """The sync's own group stays, unlinked and logged; the adopted one is linked and synced at once"""
        _switch_on(rest_api)
        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)
        created_id: int = db[CmdbObject.COLLECTION].find_one(
            {'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}})['public_id']

        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['result']['person_group_id'] == EXISTING_GROUP_ID
        created: dict[str, Any] = _object(db, created_id)
        assert 'system_ref' not in created and _values(created)[PersonGroupField.NAME.value] == GROUP_LABEL
        assert db[CmdbMetaLog.COLLECTION].count_documents(
            {'object_id': created_id, 'comment': 'Unlinked from user management'}) == 1
        assert _values(_object(db, EXISTING_GROUP_ID)) == {
            PersonGroupField.NAME.value: GROUP_LABEL,
            PersonGroupField.MEMBERS.value: [_person(db, RIGHTLESS_USER_ID)['public_id']],
        }

    def test_adopting_the_mapped_group_again_changes_nothing(self, rest_api, db: Any) -> None:
        """202, nothing written"""
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})
        before: dict[str, Any] = _object(db, EXISTING_GROUP_ID)

        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert (response.status_code, _object(db, EXISTING_GROUP_ID)) == (HTTPStatus.ACCEPTED, before)

    def test_an_existing_person_group_is_linked_unchanged_while_the_group_sync_is_off(self, rest_api, db: Any) -> None:
        """Its name stays until the group sync writes it"""
        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        stored: dict[str, Any] = _object(db, EXISTING_GROUP_ID)
        assert stored['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert _values(stored)[PersonGroupField.NAME.value] == 'Old name'

    def test_an_adopted_group_takes_the_members_when_the_group_sync_goes_on(self, rest_api, db: Any) -> None:
        """The user group's member's person; the name from the label"""
        _switch_on(rest_api)
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _values(_object(db, EXISTING_GROUP_ID)) == {
            PersonGroupField.NAME.value: GROUP_LABEL,
            PersonGroupField.MEMBERS.value: [_person(db, RIGHTLESS_USER_ID)['public_id']],
        }

    def test_switching_on_names_the_synced_persons_that_left(self, rest_api, db: Any) -> None:
        """A synced person added by hand whose user is not in the user group leaves - and the answer says so"""
        _switch_on(rest_api)
        admin_person: int = _person(db, ADMIN_USER_ID)['public_id']
        db[CmdbObject.COLLECTION].update_one(
            {'public_id': EXISTING_GROUP_ID, 'fields.name': PersonGroupField.MEMBERS.value},
            {'$set': {'fields.$.value': [admin_person]}})
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        response = rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['left'] == [{'person_group_id': EXISTING_GROUP_ID, 'person_ids': [admin_person]}]
        assert admin_person not in _values(_object(db, EXISTING_GROUP_ID))[PersonGroupField.MEMBERS.value]

    def test_a_type_the_callers_acl_denies_is_a_403(self, rest_api, db: Any) -> None:
        """The sync writes as the system - the caller is judged on what it chose; nothing is mapped"""
        db[CmdbType.COLLECTION].update_one({'public_id': GROUP_TYPE_ID}, {'$set': {'acl': {
            'activated': True, 'groups': {'includes': {str(RIGHTLESS_GROUP_ID): ['READ']}}}}})
        store_type_access(db, [GROUP_TYPE_ID])

        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert rest_api.get(f'{SYNC_URL}/groups').get_json()['result']['mappings'] == []

    def test_a_deactivated_person_group_is_refused(self, rest_api, db: Any) -> None:
        """Activate it first - nothing is mapped"""
        db[CmdbObject.COLLECTION].update_one({'public_id': EXISTING_GROUP_ID}, {'$set': {'active': False}})

        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'Person group {EXISTING_GROUP_ID} is deactivated' in response.get_json()['message']
        assert 'system_ref' not in _object(db, EXISTING_GROUP_ID)

    @pytest.mark.parametrize('body, expected', [
        ({'person_group_id': PLAIN_OBJECT_ID}, f'Object {PLAIN_OBJECT_ID} is no person group'),
        ({'person_group_id': MISSING_ID}, f'Object {MISSING_ID} does not exist'),
    ])
    def test_an_unusable_target_is_refused(self, rest_api, db: Any, body: dict[str, int], expected: str) -> None:
        """400 naming why; nothing linked"""
        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert expected in response.get_json()['message']
        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group'}) == 0

    def test_a_type_id_creates_nothing(self, rest_api, db: Any) -> None:
        """The sync creates person groups in its default - a mapping only adopts: 400, nothing linked"""
        response = rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'type_id': GROUP_TYPE_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group'}) == 0

    def test_a_missing_user_group_is_a_404(self, rest_api) -> None:
        """Nothing to map"""
        response = rest_api.put(f'{SYNC_URL}/groups/{MISSING_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_there_is_no_unmap(self, rest_api, db: Any) -> None:
        """DELETE is no route of it - the link stays"""
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        response = rest_api.delete(f'{SYNC_URL}/groups/{USER_GROUP_ID}')

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert _object(db, EXISTING_GROUP_ID)['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}


@pytest.fixture(name='reported')
def fixture_reported(monkeypatch) -> MagicMock:
    """Replaces the ConfigItem report the sync's callbacks make; yields the stub to assert on"""
    report = MagicMock(name='handle_sync_config_item_count')
    monkeypatch.setattr(f'{EVENTS_HELPER_PATH}.handle_sync_config_item_count', report)

    return report


class TestConfigItemReport:
    """A sync that links or unlinks a stored object reports the ConfigItem count once; creating linked ones does not"""

    def test_switching_on_creates_persons_and_reports_nothing(self, rest_api, reported: MagicMock) -> None:
        """New persons never were ConfigItems"""
        assert _switch_on(rest_api).status_code == HTTPStatus.ACCEPTED

        reported.assert_not_called()

    def test_the_person_groups_the_sync_creates_report_nothing(self, rest_api, reported: MagicMock) -> None:
        """Created linked - no ConfigItem came or went"""
        _switch_on(rest_api)

        rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON)

        reported.assert_not_called()

    def test_linking_an_existing_group_reports_once(self, rest_api, reported: MagicMock) -> None:
        """A stored ConfigItem became a linked object"""
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})

        reported.assert_called_once()
        assert reported.call_args.args[0].public_id == ADMIN_ID

    def test_a_re_map_reports_once(self, rest_api, db: Any, reported: MagicMock) -> None:
        """The unlinked group a ConfigItem again, the adopted one not any more - one report"""
        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': EXISTING_GROUP_ID})
        db[CmdbObject.COLLECTION].insert_one({**{key: value for key, value in _object(db, EXISTING_GROUP_ID).items()
                                                 if key not in ('_id', 'system_ref')}, 'public_id': MISSING_ID})
        reported.reset_mock()

        rest_api.put(f'{SYNC_URL}/groups/{USER_GROUP_ID}', json={'person_group_id': MISSING_ID})

        reported.assert_called_once()
        db[CmdbObject.COLLECTION].delete_one({'public_id': MISSING_ID})


class TestRenderedLink:
    """The rendered object says that user management owns it."""

    def test_a_synced_person_renders_its_link(self, rest_api, db: Any) -> None:
        """object_information.system_ref, as stored"""
        _switch_on(rest_api)
        person_id: int = _person(db, RIGHTLESS_USER_ID)['public_id']

        response = rest_api.get(f'/objects/{person_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['object_information']['system_ref'] == {'kind': 'user', 'id': RIGHTLESS_USER_ID}

    def test_a_synced_object_renders_the_group_sync_switch(self, rest_api, db: Any) -> None:
        """object_information.group_sync_active follows the stored switch"""
        _switch_on(rest_api)
        person_id: int = _person(db, RIGHTLESS_USER_ID)['public_id']

        assert rest_api.get(f'/objects/{person_id}').get_json()['object_information']['group_sync_active'] is False

        assert rest_api.put(f'{SYNC_URL}/groups', json=GROUP_ON).status_code == HTTPStatus.ACCEPTED

        assert rest_api.get(f'/objects/{person_id}').get_json()['object_information']['group_sync_active'] is True

    def test_a_plain_object_renders_no_link(self, rest_api) -> None:
        """Absent, not null - the switch too"""
        response = rest_api.get(f'/objects/{PLAIN_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert not {'system_ref', 'group_sync_active'} & set(response.get_json()['object_information'])


class TestResync:
    """POST /person_sync/resync."""

    def test_a_resync_while_off_is_refused(self, rest_api) -> None:
        """Nothing to sync"""
        response = rest_api.post(f'{SYNC_URL}/resync')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_resync_catches_up_and_clears_the_pending_marks(self, rest_api, db: Any) -> None:
        """A person removed behind the sync's back is created again; the mark goes"""
        _switch_on(rest_api)
        db[CmdbObject.COLLECTION].delete_one({'system_ref.kind': 'user', 'system_ref.id': RIGHTLESS_USER_ID})
        db[CmdbUser.COLLECTION].update_one({'public_id': RIGHTLESS_USER_ID},
                                           {'$set': {CmdbUserKey.SYNC_PENDING.value: True}})

        response = rest_api.post(f'{SYNC_URL}/resync')

        assert response.status_code == HTTPStatus.ACCEPTED
        answer: dict[str, Any] = response.get_json()
        assert (answer['created'], answer['edited'], answer['left']) == (1, 0, [])
        assert answer['result'] == ON
        assert _person(db, RIGHTLESS_USER_ID) is not None
        assert CmdbUserKey.SYNC_PENDING.value not in db[CmdbUser.COLLECTION].find_one({'public_id': RIGHTLESS_USER_ID})


class TestUserPerson:
    """GET /users/<user_id>/person."""

    def test_a_user_without_a_person_answers_none(self, rest_api) -> None:
        """The sync never ran"""
        response = rest_api.get(f'/users/{ADMIN_ID}/person')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'] == {'user_id': ADMIN_ID, 'person_id': None, 'type_id': None}

    def test_a_synced_user_answers_its_person(self, rest_api, db: Any) -> None:
        """The link"""
        _switch_on(rest_api)

        response = rest_api.get(f'/users/{ADMIN_ID}/person')

        assert response.get_json()['result'] == {
            'user_id': ADMIN_ID, 'person_id': _person(db, ADMIN_ID)['public_id'], 'type_id': PERSON_TYPE_ID,
        }

    def test_a_person_in_an_unreadable_type_is_a_403(self, rest_api, db: Any) -> None:
        """The Type's ACL grants the rightless user's groups nothing"""
        _switch_on(rest_api)
        db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'acl': {
            'activated': True, 'groups': {'includes': {str(ADMIN_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}},
        }}})
        store_type_access(db, [PERSON_TYPE_ID])
        rightless: CmdbUser = CmdbUser(public_id=RIGHTLESS_USER_ID, user_name='fn-sync-rightless', active=True,
                                       group_ids=[RIGHTLESS_GROUP_ID, USER_GROUP_ID])

        response = rest_api.get(f'/users/{RIGHTLESS_USER_ID}/person', user=rightless)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert 'may not read' in response.get_json()['message']

    def test_a_missing_user_is_a_404(self, rest_api) -> None:
        """No user, no person"""
        assert rest_api.get(f'/users/{MISSING_ID}/person').status_code == HTTPStatus.NOT_FOUND

    def test_a_user_reads_its_own_but_not_another(self, rest_api) -> None:
        """The owner carve-out of base.user-management.user.view"""
        rightless: CmdbUser = CmdbUser(public_id=RIGHTLESS_USER_ID, user_name='fn-sync-rightless', active=True,
                                       group_ids=[RIGHTLESS_GROUP_ID])

        own = rest_api.get(f'/users/{RIGHTLESS_USER_ID}/person', user=rightless)
        other = rest_api.get(f'/users/{ADMIN_ID}/person', user=rightless)

        assert own.status_code == HTTPStatus.OK
        assert other.status_code == HTTPStatus.FORBIDDEN


class TestRight:
    """Every /person_sync route checks base.user-management.sync.edit."""

    @pytest.mark.parametrize('method, path, body', [
        ('get', '/users', None),
        ('put', '/users', ON),
        ('get', '/groups', None),
        ('put', '/groups', GROUP_OFF),
        ('put', f'/groups/{USER_GROUP_ID}', {'person_group_id': EXISTING_GROUP_ID}),
        ('post', '/resync', None),
        ('post', '/users/check', ON),
    ])
    def test_a_user_without_the_right_is_refused(self, rest_api, method: str, path: str,
                                                 body: dict[str, Any] | None) -> None:
        """403 naming the right"""
        rightless: CmdbUser = CmdbUser(public_id=RIGHTLESS_USER_ID, user_name='fn-sync-rightless', active=True,
                                       group_ids=[RIGHTLESS_GROUP_ID])

        response = getattr(rest_api, method)(f'{SYNC_URL}{path}', json=body, user=rightless)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == SYNC_RIGHT_REFUSAL


def _block_admin(db: Any) -> int:
    """Gives the first PERSON Type an own field and the admin's person a value in it - the other Type lacks it"""
    db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID},
                                       {'$push': {'fields': {'type': 'text', 'name': OWN_FIELD, 'label': 'Badge'}}})
    person: dict[str, Any] = _person(db, ADMIN_ID)
    db[CmdbObject.COLLECTION].update_one({'public_id': person['public_id']},
                                         {'$push': {'fields': {'name': OWN_FIELD, 'value': 'B-7', 'type': 'text'}}})

    return person['public_id']


class TestRelocation:
    """A target change: POST /person_sync/users/check and on_blocked."""

    def test_the_check_names_every_relocation_and_writes_nothing(self, rest_api, db: Any) -> None:
        """The admin's person is blocked by its own value; nothing moves"""
        _switch_on(rest_api)
        admin_person: int = _block_admin(db)

        response = rest_api.post(f'{SYNC_URL}/users/check', json={**ON, 'default_type_id': OTHER_PERSON_TYPE_ID})

        assert response.status_code == HTTPStatus.OK
        result: dict[str, Any] = response.get_json()['result']
        assert result['blocked'] == 1
        admin_relocation = next(item for item in result['relocations'] if item['user_id'] == ADMIN_ID)
        assert admin_relocation['person_id'] == admin_person
        assert (admin_relocation['from_type_id'], admin_relocation['to_type_id']) == (PERSON_TYPE_ID,
                                                                                     OTHER_PERSON_TYPE_ID)
        assert OWN_FIELD in admin_relocation['blockers'][0]
        assert _person(db, ADMIN_ID)['type_id'] == PERSON_TYPE_ID

    def test_a_blocked_person_cancels_the_change(self, rest_api, db: Any) -> None:
        """400 naming the person; nobody moved, the settings unchanged"""
        _switch_on(rest_api)
        admin_person: int = _block_admin(db)

        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'default_type_id': OTHER_PERSON_TYPE_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert f'person {admin_person} of user {ADMIN_ID}' in response.get_json()['message']
        assert _person(db, RIGHTLESS_USER_ID)['type_id'] == PERSON_TYPE_ID
        assert rest_api.get(f'{SYNC_URL}/users').get_json()['result']['default_type_id'] == PERSON_TYPE_ID

    def test_copy_leaves_a_deactivated_copy_and_moves_the_rest(self, rest_api, db: Any) -> None:
        """The admin gets a new person; the old one is unlinked and inactive; the others move"""
        _switch_on(rest_api)
        admin_person: int = _block_admin(db)

        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'default_type_id': OTHER_PERSON_TYPE_ID,
                                                            'on_blocked': 'copy'})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['copied'] == 1
        old: dict[str, Any] = _object(db, admin_person)
        new: dict[str, Any] = _person(db, ADMIN_ID)
        assert (old['active'], 'system_ref' in old) == (False, False)
        assert (new['type_id'], new['active']) == (OTHER_PERSON_TYPE_ID, True)
        assert new['public_id'] != admin_person
        assert _person(db, RIGHTLESS_USER_ID)['type_id'] == OTHER_PERSON_TYPE_ID

    def test_an_unknown_choice_is_refused(self, rest_api) -> None:
        """cancel or copy"""
        response = rest_api.put(f'{SYNC_URL}/users', json={**ON, 'on_blocked': 'move'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
