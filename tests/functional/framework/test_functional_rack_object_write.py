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
Functional tests for the Rack invariants on the CmdbObject write routes

A field's `required` marker is honoured by the frontend form only, so these tests go through the REST
routes an API client would use: POST /objects/, PUT /objects/<id> and PATCH /objects/<id> must all
refuse a blank Rackname and a non-positive / non-whole height, and must store a valid height as an int
whatever type the client sent. Also asserts the rejection is reported under the Rack feature's name,
not IPAM's, and that an ordinary type is unaffected
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.framework.rack.rack_constants import ABORT_PREFIX
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

RACK_TYPE_ID: int = 9451
PLAIN_TYPE_ID: int = 9452

OBJECT_ID_FOR_CREATE: int = 9461
OBJECT_ID_FOR_UPDATE: int = 9462
OBJECT_ID_FOR_PATCH: int = 9463
OBJECT_ID_PLAIN: int = 9464
ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_PATCH,
    OBJECT_ID_PLAIN,
]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

VALID_NAME: str = 'rack-a'
VALID_HEIGHT: int = 42
PLAIN_FIELD: str = 'plain-field'


def _rack_type_doc() -> dict[str, Any]:
    """The Rack CmdbType, with every governed field surfaced by a section (the PUT path needs that)"""
    field_names = [
        RackField.NAME.value,
        RackField.NUMBER.value,
        RackField.HEIGHT.value,
        RackField.NOTES.value,
    ]

    return {
        'public_id': RACK_TYPE_ID,
        'name': 'rack-write-type',
        'label': 'Rack',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'text', 'name': RackField.NUMBER.value, 'label': 'Racknumber'},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
            {'type': 'textarea', 'name': RackField.NOTES.value, 'label': 'Notes'},
        ],
        'render_meta': {
            'icon': 'fa-server',
            'sections': [{
                'type': 'section',
                'name': RackSection.INFORMATION.value,
                'label': 'Information',
                'fields': field_names,
            }],
            'summary': {'fields': [RackField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _plain_type_doc() -> dict[str, Any]:
    """An ordinary type, to prove the Rack rules do not leak onto everything else"""
    return {
        'public_id': PLAIN_TYPE_ID,
        'name': 'rack-write-plain',
        'label': 'Plain',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': PLAIN_FIELD, 'label': 'Plain'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [PLAIN_FIELD]}],
            'summary': {'fields': [PLAIN_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _rack_payload(public_id: int, name: Any = VALID_NAME, height: Any = VALID_HEIGHT) -> dict[str, Any]:
    """Builds a Rack object payload for POST / PUT"""
    return {
        'public_id': public_id,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'value': name},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'value': height},
        ],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Rack type and an ordinary type for the module"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': [RACK_TYPE_ID, PLAIN_TYPE_ID]}})
    types.insert_many([_rack_type_doc(), _plain_type_doc()])

    yield

    types.delete_many({'public_id': {'$in': [RACK_TYPE_ID, PLAIN_TYPE_ID]}})


@pytest.fixture(autouse=True)
def _clean_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the test objects before and after each test"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    yield

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _insert_rack_object(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a valid Rack object directly, bypassing the route validation"""
    doc = _rack_payload(public_id)
    doc['creation_time'] = datetime.now(timezone.utc)
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(doc)


def _stored_height(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> Any:
    """Reads a stored Rack object's height field value back"""
    stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
        {'public_id': public_id}
    )

    return next(
        field['value'] for field in stored['fields'] if field['name'] == RackField.HEIGHT.value
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      CREATE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateRackObject:
    """POST /objects/ enforces the Rack invariants an API client could otherwise bypass"""

    def test_creates_a_valid_rack(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A valid rack is accepted and stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rack_payload(OBJECT_ID_FOR_CREATE))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert _stored_height(database_manager, database_name, OBJECT_ID_FOR_CREATE) == VALID_HEIGHT

    @pytest.mark.parametrize('name', [None, '', '   '], ids=repr)
    def test_rejects_a_blank_name(self, rest_api, name: Any) -> None:
        """A missing or whitespace-only Rackname is refused, despite 'required' being frontend-only"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rack_payload(OBJECT_ID_FOR_CREATE, name=name))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('height', [0, -1, 3.5, 'abc', None, ''], ids=repr)
    def test_rejects_an_invalid_height(self, rest_api, height: Any) -> None:
        """Zero, negative, fractional, non-numeric and absent heights are all refused"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rack_payload(OBJECT_ID_FOR_CREATE, height=height))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_rejection_is_reported_under_the_rack_feature(self, rest_api) -> None:
        """
        A Rack problem must not be reported to the user as an IPAM failure

        The IPAM formatter hardcodes its own prefix, which is why Rack has a separate one.
        """
        response = rest_api.post(f'{ROUTE_URL}/', json=_rack_payload(OBJECT_ID_FOR_CREATE, height=0))

        body = response.get_data(as_text=True)
        assert ABORT_PREFIX in body
        assert 'IPAM validation failed' not in body

    @pytest.mark.parametrize('sent, expected', [('42', 42), (42.0, 42)], ids=str)
    def test_stores_the_height_as_an_int(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
        sent: Any,
        expected: int,
    ) -> None:
        """A string or float height is canonicalised, so the stored type does not depend on the client"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rack_payload(OBJECT_ID_FOR_CREATE, height=sent))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = _stored_height(database_manager, database_name, OBJECT_ID_FOR_CREATE)
        assert stored == expected
        assert isinstance(stored, int)

    def test_an_ordinary_type_is_unaffected(self, rest_api) -> None:
        """The Rack rules apply to Rack objects only"""
        payload = {
            'public_id': OBJECT_ID_PLAIN,
            'type_id': PLAIN_TYPE_ID,
            'active': True,
            'author_id': SEED_AUTHOR_ID,
            'version': SEED_VERSION,
            'fields': [{'type': 'text', 'name': PLAIN_FIELD, 'value': ''}],
        }

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   UPDATE / PATCH                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateRackObject:
    """PUT and PATCH run through the same enforcement as the insert"""

    def test_put_rejects_an_invalid_height(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A full update may not lower the height below one"""
        _insert_rack_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)

        response = rest_api.put(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}',
            json=_rack_payload(OBJECT_ID_FOR_UPDATE, height=0),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_height(database_manager, database_name, OBJECT_ID_FOR_UPDATE) == VALID_HEIGHT

    def test_put_rejects_a_blank_name(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A full update may not blank the Rackname"""
        _insert_rack_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)

        response = rest_api.put(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}',
            json=_rack_payload(OBJECT_ID_FOR_UPDATE, name='   '),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_put_accepts_a_valid_change(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A valid height change goes through"""
        _insert_rack_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)

        response = rest_api.put(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}',
            json=_rack_payload(OBJECT_ID_FOR_UPDATE, height=24),
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _stored_height(database_manager, database_name, OBJECT_ID_FOR_UPDATE) == 24

    def test_patch_rejects_an_invalid_height(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The partial-update route is covered too

        PATCH merges the subset onto the stored object and then runs the shared update pipeline, so
        the invariants must hold there as well.
        """
        _insert_rack_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

        response = rest_api.patch(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
            json={'fields': [{'name': RackField.HEIGHT.value, 'value': -5}]},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_height(database_manager, database_name, OBJECT_ID_FOR_PATCH) == VALID_HEIGHT
