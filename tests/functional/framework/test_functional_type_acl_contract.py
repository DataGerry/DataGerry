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
Functional tests for a CmdbType's ``acl`` on every write - access is managed through the access rules

``POST /types/`` and ``PUT /types/<id>`` still judge the block's shape (``get_type_acl_schema``, a 400), and accept
it only when it means what the Type answers: on a create the default block (then stored), on an update the block the
access rules decide (the stored block is then kept as it is). Any other block is a 400 naming Access & Data Rules.
The type import does not judge an uploaded ``acl`` at all: a new Type stores the default block, an updated one keeps
its stored block, and the report counts the imported entries that carried an activated one (``access_not_imported``).
The type listing answers the decided block, never the stored one
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import ACCESS_NOT_IMPORTED_NOTE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE,
)

from tests.functional.framework.test_functional_types_route import _type_payload
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
IMPORT_CREATE_URL: str = '/import/type/create/'
IMPORT_UPDATE_URL: str = '/import/type/update/'

STORED_TYPE_ID: int = 97601
CREATED_TYPE_NAME: str = 'acl-contract-created'
STORED_TYPE_NAME: str = 'acl-contract-stored'
IMPORTED_BAD_NAME: str = 'acl-contract-imported-bad'
IMPORTED_GOOD_NAME: str = 'acl-contract-imported-good'
ALL_TYPE_NAMES: list[str] = [CREATED_TYPE_NAME, STORED_TYPE_NAME, IMPORTED_BAD_NAME, IMPORTED_GOOD_NAME]

ACL_KEY: str = TypeSchemaKey.ACL.value
DEFAULT_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': {}}}
ACTIVATED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'2': ['READ', 'UPDATE']}}}
# Stored past the routes; no role restricts the Type, so it answers the default block
ORIGINAL_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'1': ['READ'], '2': ['READ']}}}

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
    """POST /types/ judges the block's shape, then accepts only the default"""

    @pytest.mark.parametrize('acl', MALFORMED_ACLS)
    def test_a_malformed_block_is_refused(self, rest_api, types, acl: Any) -> None:
        """A 400 naming the acl, and no type stored"""
        response = rest_api.post(TYPES_URL, json=_create_body(acl))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ACL_KEY in response.get_json()['message']
        assert types.count_documents({'name': CREATED_TYPE_NAME}) == 0

    @pytest.mark.parametrize('acl', [
        {'activated': False},
        {'activated': False, 'groups': None},
        {'activated': False, 'whatever': [1]},
        {'activated': False, 'groups': {'includes': {'2': ['READ']}}},
    ], ids=['flag-only', 'null-groups', 'unknown-key', 'off-with-groups'])
    def test_every_spelling_of_the_default_stores_the_default(self, rest_api, types, acl: Any) -> None:
        """Accepted; the complete default block is stored"""
        response = rest_api.post(TYPES_URL, json=_create_body(acl))

        assert response.status_code == HTTPStatus.CREATED
        assert types.find_one({'name': CREATED_TYPE_NAME})[ACL_KEY] == DEFAULT_ACL

    @pytest.mark.parametrize('acl', [ACTIVATED_ACL, {'activated': True, 'groups': {'includes': {'2': []}}}],
                             ids=['frontend-shape', 'granted-nothing'])
    def test_an_activated_block_is_refused(self, rest_api, types, acl: Any) -> None:
        """400 naming Access & Data Rules, nothing stored"""
        response = rest_api.post(TYPES_URL, json=_create_body(acl))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE
        assert types.count_documents({'name': CREATED_TYPE_NAME}) == 0


class TestUpdate:
    """PUT /types/<id> accepts the block the Type answers with, and keeps the stored one"""

    @pytest.mark.parametrize('acl', MALFORMED_ACLS)
    def test_a_malformed_block_is_refused_and_the_stored_acl_kept(self, rest_api, types, acl: Any) -> None:
        """A 400 before the model is built, and nothing written"""
        body = _store_type(types)

        response = rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, ACL_KEY: acl})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert types.find_one({'public_id': STORED_TYPE_ID})[ACL_KEY] == ORIGINAL_ACL

    def test_the_answered_block_sent_back_is_accepted_and_the_stored_kept(self, rest_api, types) -> None:
        """What GET answers (the default - no role restricts it) goes back unchanged; the stored block stays"""
        body = _store_type(types)
        answered: dict[str, Any] = rest_api.get(f'{TYPES_URL}{STORED_TYPE_ID}').get_json()['result'][ACL_KEY]

        response = rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, ACL_KEY: answered, 'label': 'Edited'})

        assert (answered, response.status_code) == (DEFAULT_ACL, HTTPStatus.ACCEPTED)
        stored: dict[str, Any] = types.find_one({'public_id': STORED_TYPE_ID})
        assert (stored['label'], stored[ACL_KEY]) == ('Edited', ORIGINAL_ACL)

    @pytest.mark.parametrize('acl', [ORIGINAL_ACL, ACTIVATED_ACL], ids=['the-stored-block', 'a-change'])
    def test_any_other_block_is_refused(self, rest_api, types, acl: Any) -> None:
        """Even the stored one - it is not what the Type answers; nothing written"""
        body = _store_type(types)

        response = rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, ACL_KEY: acl, 'label': 'Edited'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE
        assert types.find_one({'public_id': STORED_TYPE_ID})['label'] != 'Edited'


class TestRead:
    """GET /types/ answers the acl the access rules decide - the stored block decides nothing"""

    def test_the_listing_answers_the_decided_block_not_the_stored_one(self, rest_api, types) -> None:
        """An activated stored block, no role restricting the Type: the default block, switched off"""
        body = _store_type(types)
        stored = {'activated': True, 'groups': {'includes': {
            '1': ['UPDATE', 'READ'], '2': ['DELETE', 'CREATE'], '11': ['DELETE'],
        }}}
        types.update_one({'public_id': STORED_TYPE_ID}, {'$set': {ACL_KEY: stored}})

        response = rest_api.get(f'{TYPES_URL}?filter={json.dumps({"public_id": body["public_id"]})}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'][0][ACL_KEY] == {'activated': False, 'groups': {'includes': {}}}
        assert types.find_one({'public_id': STORED_TYPE_ID})[ACL_KEY] == stored


class TestImport:
    """The type import takes no acl over, and reports the activated ones"""

    @staticmethod
    def _upload(rest_api, url: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """The import's answer"""
        response = rest_api.post(url, data={'uploadFile': json.dumps(entries, default=str)},
                                 content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK

        return response.get_json()

    def test_a_create_stores_the_default_whatever_the_upload_carried(self, rest_api, types) -> None:
        """Even a malformed block is not judged; the activated one is counted and named in the summary"""
        bad = make_type_doc(0, IMPORTED_BAD_NAME)
        bad.pop('public_id')
        bad[ACL_KEY] = {'activated': True, 'groups': {'includes': {'1': 'READ,UPDATE'}}}
        good = make_type_doc(0, IMPORTED_GOOD_NAME)
        good.pop('public_id')
        good[ACL_KEY] = DEFAULT_ACL

        answer = self._upload(rest_api, IMPORT_CREATE_URL, [bad, good])

        assert (answer['success_imports'], answer['failed_imports'], answer['access_not_imported']) == (2, [], 1)
        assert ACCESS_NOT_IMPORTED_NOTE.format(count=1) in answer['message']
        assert [document[ACL_KEY] for document in types.find({'name': {'$in': ALL_TYPE_NAMES}})] == [
            DEFAULT_ACL, DEFAULT_ACL]

    def test_an_update_keeps_the_stored_block(self, rest_api, types) -> None:
        """The uploaded activated acl is counted, the stored one stays"""
        body = _store_type(types)

        answer = self._upload(rest_api, IMPORT_UPDATE_URL, [{**body, ACL_KEY: ACTIVATED_ACL, 'label': 'Imported'}])

        assert (answer['success_imports'], answer['access_not_imported']) == (1, 1)
        stored: dict[str, Any] = types.find_one({'public_id': STORED_TYPE_ID})
        assert (stored['label'], stored[ACL_KEY]) == ('Imported', ORIGINAL_ACL)

    def test_nothing_activated_reports_nothing(self, rest_api, types) -> None:
        """No note, a zero count"""
        good = make_type_doc(0, IMPORTED_GOOD_NAME)
        good.pop('public_id')

        answer = self._upload(rest_api, IMPORT_CREATE_URL, [good])

        assert answer['access_not_imported'] == 0 and 'Access & Data Rules' not in answer['message']
