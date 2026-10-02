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
Functional tests for the request size limits and the 16 MB document answer, through the real REST app

  - a body above ``RequestSizeLimit.MAX_CONTENT_LENGTH`` is a 413 in the JSON envelope, before any route runs
  - a write whose document would exceed MongoDB's 16 MB limit is the one 400 - on a route that maps its write
    error by hand (``/types``) and on one that maps it through ``handle_manager_errors`` (``/isms/threats``) - and
    nothing is stored
  - the upload routes take what they are for: a type import above Werkzeug's 500 KB form-field cap, a media file
    above the JSON body limit
"""
import json
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsThreat
from cmdb.framework.media_library import MediaFile
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE, MEBIBYTE, RequestSizeLimit

from tests.functional.framework.test_functional_types_route import _type_payload
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
THREATS_URL: str = '/isms/threats/'
TYPE_IMPORT_URL: str = '/import/type/create/'
MEDIA_URL: str = '/media_file/'

STORED_TYPE_ID: int = 97801
TYPE_NAME: str = 'size-limit-type'
THREAT_NAME: str = 'size-limit-threat'
IMPORTED_NAME_PREFIX: str = 'size-limit-imported-'
MEDIA_FILENAME: str = 'size-limit-upload.bin'
AUTHOR_ID: int = 1

# Past MongoDB's 16 MB document limit, under the JSON body limit
OVERSIZE_TEXT: str = 'x' * (17 * MEBIBYTE)
# The number of imported types whose upload passes Werkzeug's 500 KB form-field cap
IMPORTED_TYPE_COUNT: int = 60
IMPORTED_DESCRIPTION: str = 'y' * 10_000
WERKZEUG_DEFAULT_FORM_MEMORY: int = 500_000


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the threat routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The collections these tests write, purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    threats = database_manager.get_collection(IsmsThreat.COLLECTION, database_name)
    media_files = database_manager.get_collection(f'{MediaFile.COLLECTION}.files', database_name)
    media_chunks = database_manager.get_collection(f'{MediaFile.COLLECTION}.chunks', database_name)

    def _purge() -> None:
        types.delete_many({'$or': [{'public_id': STORED_TYPE_ID}, {'name': TYPE_NAME},
                                   {'name': {'$regex': f'^{IMPORTED_NAME_PREFIX}'}}]})
        threats.delete_many({'name': THREAT_NAME})

        for stored in list(media_files.find({'filename': MEDIA_FILENAME})):
            media_chunks.delete_many({'files_id': stored['_id']})
            media_files.delete_one({'_id': stored['_id']})

    _purge()
    yield {'types': types, 'threats': threats, 'media_files': media_files}
    _purge()


def _type_body(**overrides: Any) -> dict[str, Any]:
    """A complete type body"""
    body = _type_payload(STORED_TYPE_ID, 'Size limit')
    body['name'] = TYPE_NAME
    body.update(overrides)

    return body


def _assert_too_large(response: Any) -> None:
    """The one 400 of the document size limit"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()
    assert response.get_json()['message'] == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE


class TestTheBodyLimit:
    """Werkzeug answers before any route reads the body"""

    def test_a_body_above_the_limit_is_a_413_in_the_envelope(self, rest_api, collections) -> None:
        """The JSON envelope the frontend reads, and nothing stored"""
        oversize: str = json.dumps(_type_body(description='z' * (RequestSizeLimit.MAX_CONTENT_LENGTH + 1)))

        response = rest_api.post(TYPES_URL, data=oversize, content_type='application/json')

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.get_json()['status'] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert collections['types'].count_documents({'name': TYPE_NAME}) == 0


class TestTheDocumentLimit:
    """A document MongoDB would refuse is the caller's 400, not a database failure"""

    def test_a_type_create_past_16_mb(self, rest_api, collections) -> None:
        """A route that maps its write error by hand"""
        _assert_too_large(rest_api.post(TYPES_URL, json=_type_body(description=OVERSIZE_TEXT)))
        assert collections['types'].count_documents({'name': TYPE_NAME}) == 0

    def test_a_type_update_past_16_mb(self, rest_api, collections) -> None:
        """The update's arm, and the stored type unchanged"""
        body = _type_body()
        collections['types'].insert_one(dict(body))

        _assert_too_large(rest_api.put(f'{TYPES_URL}{STORED_TYPE_ID}', json={**body, 'description': OVERSIZE_TEXT}))
        assert collections['types'].find_one({'public_id': STORED_TYPE_ID}).get('description') is None

    def test_a_threat_create_past_16_mb(self, rest_api, collections) -> None:
        """A route whose write error is mapped by handle_manager_errors"""
        response = rest_api.post(THREATS_URL, json={
            'name': THREAT_NAME, 'source': None, 'identifier': None, 'description': OVERSIZE_TEXT,
        })

        _assert_too_large(response)
        assert collections['threats'].count_documents({'name': THREAT_NAME}) == 0


class TestTheUploadRoutes:
    """The routes that take a file take more than a JSON body"""

    def test_a_type_import_above_werkzeugs_form_field_cap(self, rest_api, collections) -> None:
        """The upload is one JSON string in a form field, which Werkzeug caps at 500 KB unless told otherwise"""
        entries: list[dict[str, Any]] = []

        for index in range(IMPORTED_TYPE_COUNT):
            entry = make_type_doc(0, f'{IMPORTED_NAME_PREFIX}{index}')
            entry.pop('public_id')
            entry['description'] = IMPORTED_DESCRIPTION
            entries.append(entry)

        upload: str = json.dumps(entries, default=str)
        assert len(upload) > WERKZEUG_DEFAULT_FORM_MEMORY

        response = rest_api.post(TYPE_IMPORT_URL, data={'uploadFile': upload}, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['success_imports'] == IMPORTED_TYPE_COUNT

    def test_a_media_file_above_the_json_body_limit(self, rest_api, collections) -> None:
        """Stored in GridFS, so not held to the 16 MB document limit either"""
        content: bytes = b'm' * (RequestSizeLimit.MAX_CONTENT_LENGTH + MEBIBYTE)

        response = rest_api.post(MEDIA_URL, data={
            'file': (BytesIO(content), MEDIA_FILENAME),
            'metadata': json.dumps({'author_id': AUTHOR_ID}),
        }, content_type='multipart/form-data')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), response.get_json()
        assert collections['media_files'].find_one({'filename': MEDIA_FILENAME})['length'] == len(content)
