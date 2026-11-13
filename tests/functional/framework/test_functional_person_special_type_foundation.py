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
Functional tests for the foundation of the PERSON and PERSON_GROUP SpecialTypes, over the REST routes

PERSON and PERSON_GROUP have no schema yet, so they are seeded directly. Pinned:

  - the creation dialog does not offer them, their schema is a 400, and neither the create route nor the type import
    accepts them for a new Type
  - an update of a Type carrying one keeps its base fields: dropping one or changing its kind is a 400 and changes
    nothing; adding a field of its own is accepted - also through the type import
  - ``system_type`` is the server's: a create cannot set it, an update keeps the stored value, and the delete of a
    system Type is a 400; another Type with the same marker, not a system Type, is deleted as any other
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.type_constants import TypeStructureError
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import LOCKED_BASE_FIELDS, PersonField
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_SPECIAL_TYPE_NOT_CREATABLE_MESSAGE,
    TYPE_SYSTEM_TYPE_DELETE_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_constants import (
    SPECIAL_TYPE_NO_SCHEMA_MESSAGE,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SPECIAL_TYPES_URL: str = '/special_types'
TYPES_URL: str = '/types'
IMPORT_CREATE_URL: str = '/import/type/create/'
IMPORT_UPDATE_URL: str = '/import/type/update/'

SYSTEM_PERSON_TYPE_ID: int = 47801
OTHER_PERSON_TYPE_ID: int = 47802
GROUP_TYPE_ID: int = 47803
SEEDED_TYPE_IDS: list[int] = [SYSTEM_PERSON_TYPE_ID, OTHER_PERSON_TYPE_ID, GROUP_TYPE_ID]
CREATED_TYPE_NAMES: list[str] = ['foundation-person', 'foundation-plain']

EXTRA_FIELD: str = 'department'


def _fields(marker: SpecialType, *, kinds: dict[str, str] | None = None, drop: str | None = None,
            extra: bool = False) -> list[dict[str, Any]]:
    """The base fields of the marker - one dropped or one retyped on request - and optionally a field of its own"""
    kinds = kinds or {}
    fields: list[dict[str, Any]] = [
        {'type': kinds.get(name, kind.value), 'name': name, 'label': name.title()}
        for name, kind in LOCKED_BASE_FIELDS[marker].items() if name != drop
    ]

    if extra:
        fields.append({'type': 'text', 'name': EXTRA_FIELD, 'label': 'Department'})

    return fields


def _type_doc(public_id: int, marker: SpecialType, fields: list[dict[str, Any]] | None = None,
              system_type: bool = False) -> dict[str, Any]:
    """A Type carrying the marker, as it is stored"""
    document: dict[str, Any] = make_type_doc(
        public_id, f'foundation-{public_id}', special_type=marker.value,
        fields=fields if fields is not None else _fields(marker),
    )
    document[TypeSchemaKey.SYSTEM_TYPE.value] = system_type

    return document


def _payload(document: dict[str, Any]) -> dict[str, Any]:
    """A request body from a stored document: the creation time sent as text, as the frontend does"""
    return json.loads(json.dumps(document, default=str))


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """A system PERSON type, another PERSON type and a PERSON_GROUP type, purged before and after"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': {'$in': SEEDED_TYPE_IDS}},
                                        {'name': {'$in': CREATED_TYPE_NAMES}}]})

    _purge()
    collection.insert_many([
        _type_doc(SYSTEM_PERSON_TYPE_ID, SpecialType.PERSON, system_type=True),
        _type_doc(OTHER_PERSON_TYPE_ID, SpecialType.PERSON),
        _type_doc(GROUP_TYPE_ID, SpecialType.PERSON_GROUP),
    ])
    yield collection
    _purge()


def _stored(types: Any, public_id: int) -> dict[str, Any]:
    """The stored Type"""
    return types.find_one({'public_id': public_id})


def _import_errors(response: Any) -> list[str]:
    """Every error of a type-import report"""
    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


class TestNotOfferedYet:
    """No route lets a new Type carry PERSON or PERSON_GROUP"""

    @pytest.mark.parametrize('query', ['', '?available=true'], ids=['all', 'available'])
    def test_the_creation_dialog_does_not_offer_them(self, rest_api, query: str) -> None:
        """Neither listing names them - also with Types carrying them already stored"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/{query}')

        assert response.status_code == HTTPStatus.OK
        assert not {SpecialType.PERSON.value, SpecialType.PERSON_GROUP.value} & set(response.get_json())

    @pytest.mark.parametrize('marker', ['PERSON', 'PERSON_GROUP'])
    def test_their_schema_is_a_400(self, rest_api, marker: str) -> None:
        """A 400 naming them, not a 500"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/schema?special_type={marker}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == SPECIAL_TYPE_NO_SCHEMA_MESSAGE.format(special_type=marker)

    def test_the_create_route_refuses_them(self, rest_api, types) -> None:
        """Nothing is stored"""
        payload = _payload(make_type_doc(0, 'foundation-person', special_type='PERSON',
                                         fields=_fields(SpecialType.PERSON)))

        response = rest_api.post(f'{TYPES_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TYPE_SPECIAL_TYPE_NOT_CREATABLE_MESSAGE.format(special_type='PERSON')
        assert types.find_one({'name': 'foundation-person'}) is None

    def test_the_type_import_refuses_them(self, rest_api, types) -> None:
        """The entry is reported and not stored"""
        entry = _payload(make_type_doc(0, 'foundation-person', special_type='PERSON',
                                       fields=_fields(SpecialType.PERSON)))

        response = rest_api.post(IMPORT_CREATE_URL, data={'uploadFile': json.dumps([entry])},
                                 content_type='multipart/form-data')

        assert _import_errors(response) == [TypeImportError.SPECIAL_TYPE_NOT_CREATABLE.format(special_type='PERSON')]
        assert types.find_one({'name': 'foundation-person'}) is None


class TestBaseFieldsAreKept:
    """A Type carrying PERSON or PERSON_GROUP keeps the base fields of its marker"""

    @pytest.mark.parametrize('public_id, marker', [
        (OTHER_PERSON_TYPE_ID, SpecialType.PERSON), (GROUP_TYPE_ID, SpecialType.PERSON_GROUP),
    ], ids=['person', 'group'])
    def test_dropping_a_base_field_is_a_400(self, rest_api, types, public_id: int, marker: SpecialType) -> None:
        """Named, and the stored Type keeps it"""
        dropped: str = next(iter(LOCKED_BASE_FIELDS[marker]))
        payload = _payload(_type_doc(public_id, marker, fields=_fields(marker, drop=dropped)))

        response = rest_api.put(f'{TYPES_URL}/{public_id}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert TypeStructureError.BASE_FIELDS_MISSING.format(special_type=marker.value, names=[dropped]) \
            in response.get_json()['message']
        assert dropped in {field['name'] for field in _stored(types, public_id)['fields']}

    def test_changing_a_base_fields_kind_is_a_400(self, rest_api, types) -> None:
        """The user link stays a number"""
        payload = _payload(_type_doc(OTHER_PERSON_TYPE_ID, SpecialType.PERSON,
                                     fields=_fields(SpecialType.PERSON, kinds={PersonField.USER.value: 'text'})))

        response = rest_api.put(f'{TYPES_URL}/{OTHER_PERSON_TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert TypeStructureError.BASE_FIELDS_KIND_CHANGED.format(special_type='PERSON', fields=['user (number)']) \
            in response.get_json()['message']

    def test_adding_a_field_of_its_own_is_accepted(self, rest_api, types) -> None:
        """The base fields are a floor, not the whole Type"""
        payload = _payload(_type_doc(OTHER_PERSON_TYPE_ID, SpecialType.PERSON,
                                     fields=_fields(SpecialType.PERSON, extra=True)))

        response = rest_api.put(f'{TYPES_URL}/{OTHER_PERSON_TYPE_ID}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert EXTRA_FIELD in {field['name'] for field in _stored(types, OTHER_PERSON_TYPE_ID)['fields']}

    def test_the_type_import_update_keeps_them_too(self, rest_api, types) -> None:
        """The import writes Types without the update route, through the same structure rules"""
        entry = _payload(_type_doc(OTHER_PERSON_TYPE_ID, SpecialType.PERSON,
                                   fields=_fields(SpecialType.PERSON, drop=PersonField.EMAIL.value)))

        response = rest_api.post(IMPORT_UPDATE_URL, data={'uploadFile': json.dumps([entry])},
                                 content_type='multipart/form-data')

        assert any(TypeStructureError.BASE_FIELDS_MISSING.format(special_type='PERSON', names=['email']) in error
                   for error in _import_errors(response))
        assert PersonField.EMAIL.value in {field['name'] for field in _stored(types, OTHER_PERSON_TYPE_ID)['fields']}


class TestSystemType:
    """``system_type`` is the server's, and a system Type cannot be deleted"""

    def test_a_create_cannot_set_it(self, rest_api, types) -> None:
        """The request schema drops it; the stored Type is an ordinary one"""
        payload = _payload(make_type_doc(0, 'foundation-plain'))
        payload[TypeSchemaKey.SYSTEM_TYPE.value] = True

        response = rest_api.post(f'{TYPES_URL}/', json=payload)

        assert response.status_code == HTTPStatus.CREATED
        assert types.find_one({'name': 'foundation-plain'})[TypeSchemaKey.SYSTEM_TYPE.value] is False
        assert response.get_json()['raw'][TypeSchemaKey.SYSTEM_TYPE.value] is False

    @pytest.mark.parametrize('public_id, stored, sent', [
        (SYSTEM_PERSON_TYPE_ID, True, False), (OTHER_PERSON_TYPE_ID, False, True),
    ], ids=['kept-on', 'kept-off'])
    def test_an_update_keeps_the_stored_value(self, rest_api, types, public_id: int, stored: bool,
                                              sent: bool) -> None:
        """Whatever the body says"""
        payload = _payload(_type_doc(public_id, SpecialType.PERSON, fields=_fields(SpecialType.PERSON, extra=True)))
        payload[TypeSchemaKey.SYSTEM_TYPE.value] = sent

        response = rest_api.put(f'{TYPES_URL}/{public_id}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.get_json()['result'][TypeSchemaKey.SYSTEM_TYPE.value] is stored
        assert _stored(types, public_id)[TypeSchemaKey.SYSTEM_TYPE.value] is stored

    def test_a_system_type_cannot_be_deleted(self, rest_api, types) -> None:
        """A 400 naming it; the Type stays"""
        response = rest_api.delete(f'{TYPES_URL}/{SYSTEM_PERSON_TYPE_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TYPE_SYSTEM_TYPE_DELETE_MESSAGE.format(public_id=SYSTEM_PERSON_TYPE_ID)
        assert _stored(types, SYSTEM_PERSON_TYPE_ID) is not None

    def test_another_type_with_the_marker_is_deleted_as_any_other(self, rest_api, types) -> None:
        """Only the system Types are protected"""
        response = rest_api.delete(f'{TYPES_URL}/{OTHER_PERSON_TYPE_ID}')

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(types, OTHER_PERSON_TYPE_ID) is None
