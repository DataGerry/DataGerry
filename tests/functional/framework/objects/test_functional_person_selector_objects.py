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
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Functional tests for the person selector on the CmdbObject routes

Seeds a person type, a group type, a person type only the admin group may READ, an owning type with ``owner`` (one
person, required) and ``members`` (several persons and groups), and an editor whose group holds the object rights.
Pinned:

  - a write storing a sound selection is accepted; a wrong shape, an unknown id and a kind the selector does not select
    are 400s; a hidden person is a 403 for the editor
  - the render answers the editor the readable selections with their labels and withholds the hidden one; the editor
    sending back what it saw keeps the hidden person stored
  - deleting a person lets every selector go of it; deleting the only person a required selector holds is a 400
    naming the holder
  - the picker answers the editor the visible persons and groups, searches, resolves ids and refuses unusable kinds
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_selector.person_selector_constants import (
    PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE,
    PersonPickerError,
    PersonSelectorWriteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
PICKER_URL: str = '/objects/selectable/persons'

PERSON_TYPE: int = 48401
GROUP_TYPE: int = 48402
HIDDEN_TYPE: int = 48403
OWNING_TYPE: int = 48404
TYPE_IDS: list[int] = [PERSON_TYPE, GROUP_TYPE, HIDDEN_TYPE, OWNING_TYPE]

ADA: int = 48411
BOB: int = 48412
OPS: int = 48413
EVE: int = 48414
HOLDER: int = 48421
CREATED: int = 48422
OBJECT_IDS: list[int] = [ADA, BOB, OPS, EVE, HOLDER, CREATED]

EDITOR_GROUP: int = 48431
EDITOR: int = 48432
OWNER: str = 'owner'
MEMBERS: str = 'members'


def _type(public_id: int, name: str, marker: str = '', fields: list[dict[str, Any]] | None = None,
          admin_only: bool = False) -> dict[str, Any]:
    """A type document; a person or group type labels by its base field"""
    fields = fields or [{'type': 'text', 'name': 'display_name' if marker == 'PERSON' else 'name', 'label': 'Label'}]

    return {
        'public_id': public_id, 'name': name, 'label': name.title(), 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker, 'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [field['name'] for field in fields]},
        ]},
        'acl': {'activated': True, 'groups': {'includes': {
            str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE'],
        }}}
        if admin_only else {'activated': False, 'groups': {'includes': None}},
    }


def _labelled(public_id: int, type_id: int, label: str) -> dict[str, Any]:
    """A person or group object"""
    label_field: str = 'name' if type_id == GROUP_TYPE else 'display_name'

    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': [{'name': label_field, 'type': 'text',
                                                                     'value': label}]}


def _owning(public_id: int, owner: Any, members: Any) -> dict[str, Any]:
    """An owning object payload"""
    return {'public_id': public_id, 'type_id': OWNING_TYPE, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': OWNER, 'type': 'person', 'value': owner},
                       {'name': MEMBERS, 'type': 'person', 'value': members}]}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The types, the persons, a holder and the editor; purged before and after"""
    collections = {kind: database_manager.get_collection(kind.COLLECTION, database_name)
                   for kind in (CmdbType, CmdbObject, CmdbUserGroup, CmdbUser)}

    def _purge() -> None:
        collections[CmdbType].delete_many({'public_id': {'$in': TYPE_IDS}})
        collections[CmdbObject].delete_many({'public_id': {'$in': OBJECT_IDS}})
        collections[CmdbUserGroup].delete_many({'public_id': EDITOR_GROUP})
        collections[CmdbUser].delete_many({'public_id': EDITOR})

    _purge()
    selectors: list[dict[str, Any]] = [
        {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON'], 'multiple': False,
         'required': True},
        {'type': 'person', 'name': MEMBERS, 'label': 'Members', 'selectable': ['PERSON', 'PERSON_GROUP'],
         'multiple': True},
    ]
    collections[CmdbType].insert_many([
        _type(PERSON_TYPE, 'fn-person', 'PERSON'), _type(GROUP_TYPE, 'fn-group', 'PERSON_GROUP'),
        _type(HIDDEN_TYPE, 'fn-hidden', 'PERSON', admin_only=True), _type(OWNING_TYPE, 'fn-owning', fields=selectors),
    ])
    collections[CmdbObject].insert_many([
        _labelled(ADA, PERSON_TYPE, 'Ada'), _labelled(BOB, PERSON_TYPE, 'Bob'), _labelled(OPS, GROUP_TYPE, 'Ops'),
        _labelled(EVE, HIDDEN_TYPE, 'Eve'), {**_owning(HOLDER, ADA, [EVE, BOB]),
                                             'creation_time': datetime.now(timezone.utc)},
    ])
    collections[CmdbUserGroup].insert_one({'public_id': EDITOR_GROUP, 'name': 'fn-editors', 'label': 'Editors',
                                           'rights': [right.value for right in ObjectRightName]})
    collections[CmdbUser].insert_one({'public_id': EDITOR, 'user_name': 'fn-editor', 'active': True,
                                      'group_id': EDITOR_GROUP, 'registration_time': datetime.now(timezone.utc)})
    yield collections[CmdbObject]
    _purge()


def _editor() -> dict[str, Any]:
    """The request kwargs sending the editor"""
    return {'user': CmdbUser(public_id=EDITOR, user_name='fn-editor', active=True, group_id=EDITOR_GROUP)}


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """The stored selector values"""
    return {entry['name']: entry['value'] for entry in objects.find_one({'public_id': public_id})['fields']}


class TestWrite:
    """POST /objects/ and PUT /objects/<id>"""

    def test_a_sound_selection_is_stored(self, rest_api, seeded) -> None:
        """A person in owner, a person and a group in members"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_owning(CREATED, ADA, [BOB, OPS]))

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, CREATED) == {OWNER: ADA, MEMBERS: [BOB, OPS]}

    @pytest.mark.parametrize('owner, members, message', [
        ([ADA], [], PersonSelectorWriteError.SHAPE_SINGLE.format(name=OWNER)),
        (ADA, [BOB, BOB], PersonSelectorWriteError.SHAPE_MULTIPLE.format(name=MEMBERS)),
        (ADA, [999999], PersonSelectorWriteError.UNKNOWN.format(name=MEMBERS, ids=[999999])),
        (OPS, [], PersonSelectorWriteError.NOT_SELECTABLE.format(name=OWNER, kinds=['PERSON'], ids=[OPS])),
    ], ids=['single-as-list', 'repeated', 'unknown', 'group-in-person-selector'])
    def test_a_refused_selection_is_a_400(self, rest_api, seeded, owner: Any, members: Any, message: str) -> None:
        """Nothing is stored"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_owning(CREATED, owner, members))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == message
        assert seeded.find_one({'public_id': CREATED}) is None

    def test_a_hidden_person_is_a_403_for_the_editor(self, rest_api, seeded) -> None:
        """The editor's group may not read it"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_owning(CREATED, ADA, [EVE]), **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == PersonSelectorWriteError.NOT_READABLE.format(name=MEMBERS, ids=[EVE])
        assert seeded.find_one({'public_id': CREATED}) is None


class TestRenderAndUpdate:
    """GET /objects/<id> and an update sending back what was rendered"""

    def test_the_editor_sees_the_readable_selections_labelled(self, rest_api, seeded) -> None:
        """Eve is withheld"""
        del seeded
        response = rest_api.get(f'{OBJECTS_URL}/{HOLDER}', **_editor())

        assert response.status_code == HTTPStatus.OK
        fields = {field['name']: field for field in response.get_json()['fields']}
        assert fields[MEMBERS]['value'] == [BOB]
        assert [(person['object_id'], person['label'], person['kind']) for person in fields[MEMBERS]['persons']] == [
            (BOB, 'Bob', 'PERSON')]
        assert fields[OWNER]['persons'][0]['label'] == 'Ada'

    def test_the_admin_sees_every_selection(self, rest_api, seeded) -> None:
        """Nothing is denied to the admin group"""
        del seeded
        fields = {field['name']: field for field in rest_api.get(f'{OBJECTS_URL}/{HOLDER}').get_json()['fields']}

        assert fields[MEMBERS]['value'] == [EVE, BOB]

    def test_sending_back_what_was_seen_keeps_the_hidden_person(self, rest_api, seeded) -> None:
        """The editor adds Ops; Eve, whom it never saw, stays"""
        response = rest_api.put(f'{OBJECTS_URL}/{HOLDER}', json=_owning(HOLDER, ADA, [BOB, OPS]), **_editor())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(seeded, HOLDER) == {OWNER: ADA, MEMBERS: [BOB, OPS, EVE]}


class TestDelete:
    """DELETE /objects/<id> of a selected person"""

    def test_deleting_a_person_lets_the_selectors_go_of_it(self, rest_api, seeded) -> None:
        """Bob leaves the members list"""
        response = rest_api.delete(f'{OBJECTS_URL}/{BOB}')

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, HOLDER) == {OWNER: ADA, MEMBERS: [EVE]}

    def test_deleting_the_only_owner_is_refused(self, rest_api, seeded) -> None:
        """The holder's owner is required; Ada stays"""
        response = rest_api.delete(f'{OBJECTS_URL}/{ADA}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE.format(object_ids=[HOLDER],
                                                                                                hidden=0)
        assert seeded.find_one({'public_id': ADA}) is not None


class TestPicker:
    """GET /objects/selectable/persons"""

    @staticmethod
    def _labels(response: Any) -> list[str]:
        """The labels answered, ours only"""
        return [result['label'] for result in response.get_json()['results'] if result['object_id'] in OBJECT_IDS]

    @pytest.mark.usefixtures('seeded')
    def test_the_editor_gets_the_visible_persons_and_groups(self, rest_api) -> None:
        """Not Eve"""
        response = rest_api.get(f'{PICKER_URL}?limit=100', **_editor())

        assert response.status_code == HTTPStatus.OK
        assert self._labels(response) == ['Ada', 'Bob', 'Ops']

    @pytest.mark.usefixtures('seeded')
    def test_search_kinds_and_ids(self, rest_api) -> None:
        """A search, groups only, ids resolved"""
        assert self._labels(rest_api.get(f'{PICKER_URL}?search=bo', **_editor())) == ['Bob']
        assert self._labels(rest_api.get(f'{PICKER_URL}?kinds=PERSON_GROUP', **_editor())) == ['Ops']
        assert self._labels(rest_api.get(f'{PICKER_URL}?ids={ADA},{EVE}', **_editor())) == ['Ada']

    @pytest.mark.usefixtures('seeded')
    def test_an_unusable_kind_is_a_400(self, rest_api) -> None:
        """Named"""
        response = rest_api.get(f'{PICKER_URL}?kinds=RACK')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PersonPickerError.KINDS.value
