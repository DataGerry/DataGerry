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
Functional tests for the shape of a CmdbType's ``acl`` block on every write that stores one

``POST /types/``, ``PUT /types/<id>`` and the type import judge the block by the same rule
(``get_type_acl_schema``). Pinned:

  - a block the model cannot build (``groups`` / ``includes`` that is no object, a key that is no group id) is a
    400, not a 500, and stores nothing
  - a block the model would store scrambled (a permission list sent as a string, an unknown permission) or in a
    form the two access readers disagree on (a non-boolean ``activated``) is a 400 as well
  - every shape the frontend sends, and the partial shapes the create path completes, are still accepted
  - the import refuses such an entry in its partial report, and imports the entries beside it
  - the type listing answers a stored block in its stored form (string group keys, sorted permission lists)
    after reading it into the model, for every group it names
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError

from tests.functional.framework.test_functional_types_route import _type_payload
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
IMPORT_CREATE_URL: str = '/import/type/create/'

STORED_TYPE_ID: int = 97601
CREATED_TYPE_NAME: str = 'acl-contract-created'
STORED_TYPE_NAME: str = 'acl-contract-stored'
IMPORTED_BAD_NAME: str = 'acl-contract-imported-bad'
IMPORTED_GOOD_NAME: str = 'acl-contract-imported-good'
ALL_TYPE_NAMES: list[str] = [CREATED_TYPE_NAME, STORED_TYPE_NAME, IMPORTED_BAD_NAME, IMPORTED_GOOD_NAME]

ACL_KEY: str = TypeSchemaKey.ACL.value
ORIGINAL_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'2': ['READ']}}}

MALFORMED_ACLS: list[Any] = [
    pytest.param({'activated': True, 'groups': 42}, id='groups-no-object'),
    pytest.param({'activated': True, 'groups': {'includes': [1]}}, id='includes-no-object'),
    pytest.param({'activated': True, 'groups': {'includes': {'abc': ['READ']}}}, id='key-no-group-id'),
    pytest.param({'activated': True, 'groups': {'includes': {'1': 'READ,UPDATE'}}}, id='permissions-as-string'),
    pytest.param({'activated': True, 'groups': {'includes': {'1': ['read', 'X']}}}, id='unknown-permissions'),
    pytest.param({'activated': 'yes'}, id='flag-string'),
    pytest.param({'activated': 0, 'groups': {'includes': {}}}, id='flag-zero'),
]


@pytest.fixture(name='types', autouse=True)
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The types collection, purged of what these tests write before and after each test"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': STORED_TYPE_ID}, {'name': {'$in': ALL_TYPE_NAMES}}]})

    _purge()
    yield collection
    _purge()


def _create_body(acl: Any) -> dict[str, Any]:
    """A complete create body carrying the given acl"""
    body = _type_payload(STORED_TYPE_ID, 'ACL contract')
    body['name'] = CREATED_TYPE_NAME
    body[ACL_KEY] = acl

    return body


def _store_type(types: Any) -> dict[str, Any]:
    """Stores a type with a valid ACL, bypassing the routes, and answers its body"""
    body = _type_payload(STORED_TYPE_ID, 'ACL contract')
    body['name'] = STORED_TYPE_NAME
    body[ACL_KEY] = ORIGINAL_ACL
    types.insert_one(dict(body))

    return body


class TestCreate:
    """POST /types/ judges the block before the create path completes it"""

    @pytest.mark.parametrize('acl', MALFORMED_ACLS)
    def test_a_malformed_block_is_refused(self, rest_api, types, acl: Any) -> None:
        """A 400 naming the acl, and no type stored"""
        response = rest_api.post(TYPES_URL, json=_create_body(acl))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ACL_KEY in response.get_json()['message']
        assert types.count_documents({'name': CREATED_TYPE_NAME}) == 0

    @pytest.mark.parametrize('acl, stored', [
        ({'activated': True, 'groups': {'includes': {'2': ['READ', 'UPDATE']}}},
         {'activated': True, 'groups': {'includes': {'2': ['READ', 'UPDATE']}}}),
        ({'activated': False}, {'activated': False, 'groups': {'includes': {}}}),
        ({'activated': False, 'groups': None}, {'activated': False, 'groups': {'includes': {}}}),
        ({'activated': True, 'groups': {'includes': {'2': []}}},
         {'activated': True, 'groups': {'includes': {'2': []}}}),
        ({'activated': False, 'whatever': [1]}, {'activated': False, 'groups': {'includes': {}}}),
    ], ids=['frontend-shape', 'flag-only', 'null-groups', 'granted-nothing', 'unknown-key'])
    def test_the_shapes_in_use_are_stored_complete(self, rest_api, types, acl: Any, stored: Any) -> None:
        """Accepted, and completed to the one stored shape"""
        response = rest_api.post(TYPES_URL, json=_create_body(acl))

        assert response.status_code == HTTPStatus.CREATED
        assert types.find_one({'name': CREATED_TYPE_NAME})[ACL_KEY] == stored


class TestUpdate:
    """PUT /types/<id> judges the block before the model is built from it"""

    @pytest.mark.parametrize('acl', MALFORMED_ACLS)
    def test_a_malformed_block_is_refused_and_the_stored_acl_kept(self, rest_api, types, acl: Any) -> None:
        """A 400 before the model is built, and nothing written"""
        body = _store_type(types)

        response = rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, ACL_KEY: acl})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert types.find_one({'public_id': STORED_TYPE_ID})[ACL_KEY] == ORIGINAL_ACL

    def test_a_well_formed_change_is_applied(self, rest_api, types) -> None:
        """Granting a second group still works"""
        body = _store_type(types)
        # Each permission list is stored sorted, so the expectation is written sorted
        changed = {'activated': True, 'groups': {'includes': {'2': ['READ'], '1': ['DELETE', 'READ']}}}

        response = rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, ACL_KEY: changed})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert types.find_one({'public_id': STORED_TYPE_ID})[ACL_KEY] == changed


class TestRead:
    """GET /types/ reads each type into the model and answers the block it writes back"""

    def test_the_listing_answers_the_stored_form(self, rest_api, types) -> None:
        """Every group keeps its permissions, keyed by string, each list sorted"""
        body = _store_type(types)
        # Group 1 is the admin's, which needs READ to see the type in the listing at all
        unsorted = {'activated': True, 'groups': {'includes': {
            '1': ['UPDATE', 'READ'], '2': ['DELETE', 'CREATE'], '11': ['DELETE'],
        }}}
        types.update_one({'public_id': STORED_TYPE_ID}, {'$set': {ACL_KEY: unsorted}})

        response = rest_api.get(f'{TYPES_URL}?filter={json.dumps({"public_id": body["public_id"]})}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'][0][ACL_KEY] == {
            'activated': True,
            'groups': {'includes': {'1': ['READ', 'UPDATE'], '2': ['CREATE', 'DELETE'], '11': ['DELETE']}},
        }


class TestImport:
    """The type import refuses the entry the routes would refuse, and keeps the rest of the batch"""

    def test_a_malformed_block_refuses_only_its_entry(self, rest_api, types) -> None:
        """Reported in the partial report with what is wrong and where"""
        bad = make_type_doc(0, IMPORTED_BAD_NAME)
        bad.pop('public_id')
        bad[ACL_KEY] = {'activated': True, 'groups': {'includes': {'1': 'READ,UPDATE'}}}
        good = make_type_doc(0, IMPORTED_GOOD_NAME)
        good.pop('public_id')

        response = rest_api.post(
            IMPORT_CREATE_URL,
            data={'uploadFile': json.dumps([bad, good], default=str)},
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        errors = [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]
        assert len(errors) == 1
        assert errors[0].startswith(TypeImportError.INVALID_ACL.value.split('{', 1)[0])
        assert 'acl.groups.includes.1' in errors[0]
        assert types.count_documents({'name': IMPORTED_BAD_NAME}) == 0
        assert types.count_documents({'name': IMPORTED_GOOD_NAME}) == 1
