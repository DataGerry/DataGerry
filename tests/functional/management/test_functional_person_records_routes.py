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
Functional tests of ``/persons`` and ``/person_groups`` - a layer over the person and group objects

The two default person Types are seeded (and removed again). Pinned through the real REST app:

  - the record shape is the old one - ``public_id`` the object id, a person's ``groups`` the groups holding it, a
    group's ``group_members`` its members - and a create lands in the default Type
  - the client's filter (the frontend's ``$regex`` pipeline) and sort run on the record keys
  - a person write with ``groups`` edits the groups' members both ways; a group that is none is refused before
    anything is written
  - a group write judges its members like any person selection: an id naming no person is a 400
  - the delete takes the person out of every group; an id of the other kind is a 404
  - the object rights decide: a user without ``object.add`` cannot create, a person Type the reader may not READ
    is left out of the list and a 403 by id
  - without a default Type (a system the person migration never ran on) a create is a 400 and writes nothing - an
    ordinary Type carrying the marker is never taken instead
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.default_person_types import seed_default_person_types
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    DEFAULT_TYPE_MISSING_MESSAGE,
    RECORD_LABELS,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSONS_URL: str = '/persons'
GROUPS_URL: str = '/person_groups'

VIEWER_GROUP_ID: int = 96901
VIEWER_ID: int = 96902
VIEWER_NAME: str = 'person-records-viewer'

ADA: dict[str, Any] = {'display_name': 'Ada L', 'first_name': 'Ada', 'last_name': 'Lovelace',
                       'phone_number': '1', 'email': 'ada@example.com'}
BOB: dict[str, Any] = {'display_name': 'Bob B', 'first_name': 'Bob', 'last_name': 'Builder',
                       'phone_number': '', 'email': ''}
NAMELESS: dict[str, Any] = {'display_name': 'ann.lee'}
NEW_PHONE: str = '555-0100'


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The default person Types and a viewer; every person / group object and the Types removed after"""
    db = database_manager.connector.client[database_name]

    def _purge() -> None:
        db[CmdbObject.COLLECTION].delete_many({'special_type': {'$in': ['PERSON', 'PERSON_GROUP']}})
        db[CmdbType.COLLECTION].delete_many({'special_type': {'$in': ['PERSON', 'PERSON_GROUP']}})
        db[CmdbUserGroup.COLLECTION].delete_many({'public_id': VIEWER_GROUP_ID})
        db[CmdbUser.COLLECTION].delete_many({'public_id': VIEWER_ID})

    _purge()
    seed_default_person_types(TypesManager(database_manager, database_name))
    db[CmdbUserGroup.COLLECTION].insert_one({'public_id': VIEWER_GROUP_ID, 'name': VIEWER_NAME, 'label': VIEWER_NAME,
                                             'rights': ['base.framework.object.view']})
    db[CmdbUser.COLLECTION].insert_one({'public_id': VIEWER_ID, 'user_name': VIEWER_NAME, 'active': True,
                                        'group_ids': [VIEWER_GROUP_ID],
                                        'registration_time': datetime.now(timezone.utc)})
    yield db
    _purge()


@pytest.fixture(name='viewer')
def fixture_viewer() -> CmdbUser:
    """A user holding the object view right only"""
    return CmdbUser(public_id=VIEWER_ID, user_name=VIEWER_NAME, active=True, group_ids=[VIEWER_GROUP_ID])


def _create(rest_api, url: str, body: dict[str, Any]) -> int:
    """Creates a record, answering its id"""
    response = rest_api.post(f'{url}/', json=body)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), response.get_json()

    return response.get_json()['result_id']


def _read(rest_api, url: str, public_id: int, **kwargs: Any) -> Any:
    """Reads one record"""
    return rest_api.get(f'{url}/{public_id}', **kwargs)


def _members(db: Any, group_id: int) -> list[int]:
    """A group object's stored members"""
    document = db[CmdbObject.COLLECTION].find_one({'public_id': group_id})

    return next(entry['value'] for entry in document['fields'] if entry['name'] == 'members')


def test_a_person_is_created_in_the_default_type_and_read_in_the_old_shape(rest_api, db) -> None:
    """Every record key; groups empty; the object a PERSON of the system Type"""
    person = _create(rest_api, PERSONS_URL, ADA)

    record = _read(rest_api, PERSONS_URL, person).get_json()['result']
    stored = db[CmdbObject.COLLECTION].find_one({'public_id': person})
    default_type = db[CmdbType.COLLECTION].find_one({'special_type': 'PERSON', 'system_type': True})

    assert record == {'public_id': person, **ADA, 'groups': []}
    assert (stored['type_id'], stored['special_type']) == (default_type['public_id'], SpecialType.PERSON.value)


def test_a_person_needs_a_display_name_only(rest_api) -> None:
    """First and last name may be left out, as on the PERSON Type - only the display name is required"""
    person = _create(rest_api, PERSONS_URL, NAMELESS)

    record = _read(rest_api, PERSONS_URL, person).get_json()['result']

    assert record['display_name'] == NAMELESS['display_name']
    assert not record.get('first_name') and not record.get('last_name')


def test_a_nameless_person_saves_a_change_of_its_own(rest_api) -> None:
    """The record sent back without names - as a synced person without names reads - saves"""
    person = _create(rest_api, PERSONS_URL, NAMELESS)

    response = rest_api.put(f'{PERSONS_URL}/{person}', json={**NAMELESS, 'phone_number': NEW_PHONE})

    assert response.status_code == HTTPStatus.ACCEPTED
    assert _read(rest_api, PERSONS_URL, person).get_json()['result']['phone_number'] == NEW_PHONE


def test_a_person_without_a_display_name_is_refused(rest_api) -> None:
    """The one name a person must have"""
    response = rest_api.post(f'{PERSONS_URL}/', json={'first_name': 'Ada', 'last_name': 'Lovelace'})

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_the_list_filters_and_sorts_on_the_record_keys(rest_api) -> None:
    """The frontend's $regex pipeline over display_name; sorted by it"""
    _create(rest_api, PERSONS_URL, BOB)
    _create(rest_api, PERSONS_URL, ADA)
    search = [{'$match': {'$or': [{'display_name': {'$regex': 'b', '$options': 'i'}},
                                  {'email': {'$regex': 'ada', '$options': 'i'}}]}}]

    response = rest_api.get(f'{PERSONS_URL}/', query_string={
        'filter': json.dumps(search), 'sort': 'display_name', 'order': 1, 'limit': 0})
    body = response.get_json()

    assert response.status_code == HTTPStatus.OK
    assert [record['display_name'] for record in body['results']] == ['Ada L', 'Bob B']
    assert body['total'] == 2


def test_a_group_holds_its_members_and_a_person_reads_its_groups(rest_api, db) -> None:
    """group_members are the group object's members; the person's groups are derived"""
    ada, bob = _create(rest_api, PERSONS_URL, ADA), _create(rest_api, PERSONS_URL, BOB)
    group = _create(rest_api, GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': [ada, bob]})

    assert _members(db, group) == [ada, bob]
    assert _read(rest_api, GROUPS_URL, group).get_json()['result']['group_members'] == [ada, bob]
    assert _read(rest_api, PERSONS_URL, ada).get_json()['result']['groups'] == [group]


def test_a_person_write_with_groups_edits_the_members_both_ways(rest_api, db) -> None:
    """Joins the new group, leaves the old one"""
    ada = _create(rest_api, PERSONS_URL, ADA)
    ops = _create(rest_api, GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': [ada]})
    dev = _create(rest_api, GROUPS_URL, {'name': 'Dev', 'email': '', 'group_members': []})

    response = rest_api.put(f'{PERSONS_URL}/{ada}', json={**ADA, 'groups': [dev]})

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
    assert (_members(db, ops), _members(db, dev)) == ([], [ada])
    assert response.get_json()['result']['groups'] == [dev]


def test_a_group_that_is_none_is_refused_before_anything_is_written(rest_api, db) -> None:
    """A person id is no group; the person keeps its values"""
    ada = _create(rest_api, PERSONS_URL, ADA)
    bob = _create(rest_api, PERSONS_URL, BOB)

    response = rest_api.put(f'{PERSONS_URL}/{ada}', json={**ADA, 'display_name': 'Changed', 'groups': [bob]})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert str(bob) in response.get_json()['message']
    assert _read(rest_api, PERSONS_URL, ada).get_json()['result']['display_name'] == ADA['display_name']


def test_a_group_member_that_is_no_person_is_refused(rest_api) -> None:
    """The members selector selects persons only"""
    ops = _create(rest_api, GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': []})

    response = rest_api.post(f'{GROUPS_URL}/', json={'name': 'Dev', 'email': '', 'group_members': [ops]})

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_the_delete_takes_the_person_out_of_every_group(rest_api, db) -> None:
    """The deleted record answered; the members scrubbed"""
    ada, bob = _create(rest_api, PERSONS_URL, ADA), _create(rest_api, PERSONS_URL, BOB)
    group = _create(rest_api, GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': [ada, bob]})

    response = rest_api.delete(f'{PERSONS_URL}/{ada}')

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
    assert response.get_json()['raw']['display_name'] == ADA['display_name']
    assert _members(db, group) == [bob]


def test_an_id_of_the_other_kind_is_a_404(rest_api) -> None:
    """A group is no person, a person no group"""
    ada = _create(rest_api, PERSONS_URL, ADA)
    group = _create(rest_api, GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': []})

    assert _read(rest_api, PERSONS_URL, group).status_code == HTTPStatus.NOT_FOUND
    assert _read(rest_api, GROUPS_URL, ada).status_code == HTTPStatus.NOT_FOUND
    assert rest_api.delete(f'{GROUPS_URL}/{ada}').status_code == HTTPStatus.NOT_FOUND


def test_the_object_rights_decide(rest_api, viewer: CmdbUser) -> None:
    """object.view reads, object.add is needed to create"""
    _create(rest_api, PERSONS_URL, ADA)

    assert rest_api.get(f'{PERSONS_URL}/', user=viewer).status_code == HTTPStatus.OK
    assert rest_api.post(f'{PERSONS_URL}/', json=BOB, user=viewer).status_code == HTTPStatus.FORBIDDEN


def test_a_person_type_the_reader_may_not_read_is_hidden(rest_api, db, viewer: CmdbUser) -> None:
    """Left out of the list, 403 by id"""
    ada = _create(rest_api, PERSONS_URL, ADA)
    db[CmdbType.COLLECTION].update_one({'special_type': 'PERSON', 'system_type': True}, {'$set': {'acl': {
        'activated': True, 'groups': {'includes': {'1': ['CREATE', 'READ', 'UPDATE', 'DELETE']}}}}})

    listed = rest_api.get(f'{PERSONS_URL}/', user=viewer).get_json()

    assert ada not in [record['public_id'] for record in listed['results']]
    assert _read(rest_api, PERSONS_URL, ada, user=viewer).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url, body, marker', [
    (PERSONS_URL, ADA, SpecialType.PERSON),
    (GROUPS_URL, {'name': 'Ops', 'email': '', 'group_members': []}, SpecialType.PERSON_GROUP),
], ids=['person', 'group'])
def test_a_create_without_a_default_type_is_a_400(rest_api, db, url: str, body: dict[str, Any],
                                                  marker: SpecialType) -> None:
    """The defaults gone, an ordinary Type with the marker kept: 400 naming the record, no object written"""
    db[CmdbType.COLLECTION].update_many({'special_type': marker.value}, {'$set': {'system_type': False}})

    response = rest_api.post(f'{url}/', json=body)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == DEFAULT_TYPE_MISSING_MESSAGE.format(label=RECORD_LABELS[marker])
    assert not db[CmdbObject.COLLECTION].count_documents({'special_type': marker.value})
