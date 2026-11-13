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
Functional tests for the person selector field kind on the CmdbType routes

Seeds a person and a group (objects of types carrying the markers) and an owning type whose ``owner`` selector holds
them. Pinned:

  - a type write with a broken selector is a 400 naming it; a group type keeps its ``members`` settings
  - narrowing to one object while an object holds several, and dropping a kind an object holds, are 400s naming the
    selector and change nothing - through the update route and through the type import
  - widening to several turns every stored value into a list, flat and in rows; narrowing to one that nothing
    contradicts turns lists into their only item
  - the usage pre-check answers the objects holding several and the kinds held, and 404s a name that is no selector
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import PersonSelectorError, TypeStructureError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    PERSON_SELECTOR_KIND_MESSAGE,
    PERSON_SELECTOR_NOT_DECLARED_MESSAGE,
    PERSON_SELECTOR_SINGLE_MESSAGE,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'
IMPORT_UPDATE_URL: str = '/import/type/update/'

OWNING_TYPE_ID: int = 48201
PERSON_TYPE_ID: int = 48202
GROUP_TYPE_ID: int = 48203
TYPE_IDS: list[int] = [OWNING_TYPE_ID, PERSON_TYPE_ID, GROUP_TYPE_ID]
CREATED_TYPE_NAME: str = 'selector-created'

PERSON_ID: int = 48211
GROUP_ID: int = 48212
HOLDS_SEVERAL_ID: int = 48221
HOLDS_ONE_ID: int = 48222
OBJECT_IDS: list[int] = [PERSON_ID, GROUP_ID, HOLDS_SEVERAL_ID, HOLDS_ONE_ID]

FIELD: str = 'owner'
SECTION: str = 'contacts'
BOTH: list[str] = ['PERSON', 'PERSON_GROUP']


def _selector(selectable: list[str] | None = None, multiple: bool = True) -> dict[str, Any]:
    """The owning type's selector"""
    return {'type': 'person', 'name': FIELD, 'label': 'Owner', 'selectable': selectable or BOTH, 'multiple': multiple}


def _owning_type(selector: dict[str, Any]) -> dict[str, Any]:
    """The owning type with the selector, as stored"""
    return make_type_doc(OWNING_TYPE_ID, 'selector-owner', fields=[selector])


def _object(public_id: int, type_id: int, value: Any = None) -> dict[str, Any]:
    """An object holding the selector value flat"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': FIELD, 'type': 'person', 'value': value}], 'multi_data_sections': []}


def _payload(document: dict[str, Any]) -> dict[str, Any]:
    """A request body from a stored document"""
    return json.loads(json.dumps(document, default=str))


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The marker types, the owning type, a person, a group and two owning objects; purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'$or': [{'public_id': {'$in': TYPE_IDS}}, {'name': CREATED_TYPE_NAME}]})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_many([
        _owning_type(_selector(multiple=True)),
        make_type_doc(PERSON_TYPE_ID, 'selector-person', special_type='PERSON'),
        make_type_doc(GROUP_TYPE_ID, 'selector-group', special_type='PERSON_GROUP'),
    ])
    objects.insert_many([
        {'public_id': PERSON_ID, 'type_id': PERSON_TYPE_ID, 'fields': []},
        {'public_id': GROUP_ID, 'type_id': GROUP_TYPE_ID, 'fields': []},
        _object(HOLDS_SEVERAL_ID, OWNING_TYPE_ID, [PERSON_ID, GROUP_ID]),
        _object(HOLDS_ONE_ID, OWNING_TYPE_ID, [PERSON_ID]),
    ])
    yield types, objects
    _purge()


def _stored_value(objects: Any, public_id: int) -> Any:
    """The selector value an object holds"""
    return objects.find_one({'public_id': public_id})['fields'][0]['value']


def _put(rest_api: Any, selector: dict[str, Any]) -> Any:
    """Saves the owning type with the given selector"""
    return rest_api.put(f'{TYPES_URL}/{OWNING_TYPE_ID}', json=_payload(_owning_type(selector)))


def test_a_broken_selector_is_refused_on_create(rest_api, seeded) -> None:
    """Named; nothing is stored"""
    types, _ = seeded
    broken: dict[str, Any] = {'type': 'person', 'name': FIELD, 'label': 'Owner', 'selectable': ['RACK']}
    payload = _payload(make_type_doc(0, CREATED_TYPE_NAME, fields=[broken]))

    response = rest_api.post(f'{TYPES_URL}/', json=payload)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    message: str = response.get_json()['message']
    assert PersonSelectorError.SELECTABLE.format(name=FIELD, allowed=BOTH) in message
    assert PersonSelectorError.MULTIPLE.format(name=FIELD) in message
    assert types.find_one({'name': CREATED_TYPE_NAME}) is None


def test_a_group_type_keeps_its_members_settings(rest_api, seeded) -> None:
    """A group type without its members selector cannot be saved"""
    del seeded
    payload = _payload(make_type_doc(GROUP_TYPE_ID, 'selector-group', special_type='PERSON_GROUP'))

    response = rest_api.put(f'{TYPES_URL}/{GROUP_TYPE_ID}', json=payload)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'members' in response.get_json()['message']
    assert TypeStructureError.BASE_FIELDS_MISSING.format(special_type='PERSON_GROUP', names=['email', 'members',
                                                                                             'name']) \
        in response.get_json()['message']


def test_one_object_while_an_object_holds_several_is_refused(rest_api, seeded) -> None:
    """Named with the object; the values stay"""
    _, objects = seeded

    response = _put(rest_api, _selector(multiple=False))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == PERSON_SELECTOR_SINGLE_MESSAGE.format(name=FIELD,
                                                                                   object_ids=[HOLDS_SEVERAL_ID])
    assert _stored_value(objects, HOLDS_SEVERAL_ID) == [PERSON_ID, GROUP_ID]


def test_dropping_a_kind_an_object_holds_is_refused(rest_api, seeded) -> None:
    """An object holds a group"""
    del seeded

    response = _put(rest_api, _selector(selectable=['PERSON']))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == PERSON_SELECTOR_KIND_MESSAGE.format(name=FIELD, kinds=['PERSON_GROUP'])


def test_narrowing_to_one_nothing_contradicts_takes_the_only_item(rest_api, seeded) -> None:
    """Once no object holds several, the lists become ids"""
    _, objects = seeded
    objects.delete_one({'public_id': HOLDS_SEVERAL_ID})

    response = _put(rest_api, _selector(multiple=False))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert _stored_value(objects, HOLDS_ONE_ID) == PERSON_ID


def test_widening_to_several_wraps_the_stored_ids(rest_api, seeded) -> None:
    """From one to several: an id becomes a one-item list, None an empty one"""
    types, objects = seeded
    types.replace_one({'public_id': OWNING_TYPE_ID}, _owning_type(_selector(multiple=False)))
    objects.update_one({'public_id': HOLDS_ONE_ID}, {'$set': {'fields.0.value': PERSON_ID}})
    objects.update_one({'public_id': HOLDS_SEVERAL_ID}, {'$set': {'fields.0.value': None}})

    response = _put(rest_api, _selector(multiple=True))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert _stored_value(objects, HOLDS_ONE_ID) == [PERSON_ID]
    assert _stored_value(objects, HOLDS_SEVERAL_ID) == []


def test_the_type_import_refuses_the_same_narrowing(rest_api, seeded) -> None:
    """Through the same blocker"""
    _, objects = seeded
    entry = _payload(_owning_type(_selector(multiple=False)))

    response = rest_api.post(IMPORT_UPDATE_URL, data={'uploadFile': json.dumps([entry])},
                             content_type='multipart/form-data')

    errors: list[str] = [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]
    assert errors == [PERSON_SELECTOR_SINGLE_MESSAGE.format(name=FIELD, object_ids=[HOLDS_SEVERAL_ID])]
    assert _stored_value(objects, HOLDS_SEVERAL_ID) == [PERSON_ID, GROUP_ID]


def test_the_usage_pre_check(rest_api, seeded) -> None:
    """The objects holding several and the kinds held"""
    del seeded

    response = rest_api.get(f'{TYPES_URL}/person_field_usage/{OWNING_TYPE_ID}/{FIELD}')

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == {'objects_with_several': [HOLDS_SEVERAL_ID], 'kinds_used': BOTH}


def test_the_usage_pre_check_404s_a_name_that_is_no_selector(rest_api, seeded) -> None:
    """Named"""
    del seeded

    response = rest_api.get(f'{TYPES_URL}/person_field_usage/{OWNING_TYPE_ID}/nothing')

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.get_json()['message'] == PERSON_SELECTOR_NOT_DECLARED_MESSAGE.format(public_id=OWNING_TYPE_ID,
                                                                                          name='nothing')
