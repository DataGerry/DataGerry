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
Functional coverage for the filter of GET /media_file/ - the file list - over HTTP

Pinned:
  - ``metadata`` is optional: without it (and without ``searchTerm``) every file is listed - it used to be a 500
  - an unreadable ``metadata`` (no JSON, no object) is a 400 naming the problem - no JSON used to be a 500
  - a search never reads ``metadata``, so a search without it, or with a broken one, works
  - the search matches its term literally: a ``.`` / ``(`` / ``[`` in a name is found by itself, matches nothing else,
    and an unbalanced ``(`` no longer fails the read
  - the filter holds declared keys with plain values: an operator object, an undeclared key, a boolean or text
    reference are each a 400 with their message
  - a read past its time budget answers the shared 503
  - the frontend's request shapes still pass
"""
import json
import re
from io import BytesIO
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager.media_files_manager import MediaFileManagerGetError
from cmdb.framework.media_library import MediaFile
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.interface.request_limits_constants import MILLISECONDS_PER_SECOND, QUERY_TIME_LIMIT_RESPONSE_MESSAGE
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    METADATA_FILTER_REFERENCE_MSG,
    METADATA_FILTER_UNREADABLE_MSG,
    METADATA_FILTER_VALUE_MSG,
    UNKNOWN_METADATA_KEYS_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/media_file/'
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
CHUNKS_COLLECTION: str = f'{MediaFile.COLLECTION}.chunks'
NAME_PREFIX: str = 'dg-lf-'
DOTTED_NAME: str = f'{NAME_PREFIX}a.b'
LOOKALIKE_NAME: str = f'{NAME_PREFIX}axb'
BRACKET_NAME: str = f'{NAME_PREFIX}report (1)'
MESSAGE_KEY: str = 'message'


@pytest.fixture(name='files', autouse=True)
def fixture_files(database_manager: MongoDatabaseManager, database_name: str):
    """The GridFS files collection, purged of this module's entries before and after each test"""
    files = database_manager.get_collection(FILES_COLLECTION, database_name)
    chunks = database_manager.get_collection(CHUNKS_COLLECTION, database_name)

    def _purge() -> None:
        for doc in list(files.find({'filename': {'$regex': f'^{re.escape(NAME_PREFIX)}'}})):
            chunks.delete_many({'files_id': doc['_id']})
            files.delete_one({'_id': doc['_id']})

    _purge()
    yield files
    _purge()


def _upload(rest_api, name: str) -> None:
    """Uploads a small text file into the library's root"""
    form = {'file': (BytesIO(b'content'), name), 'metadata': json.dumps({})}
    response = rest_api.post(BASE_URL, data=form, content_type='multipart/form-data')
    assert response.status_code == HTTPStatus.CREATED, response.get_json()


def _list(rest_api, **query: Any) -> Any:
    """GET the list with these query parameters"""
    return rest_api.get(f'{BASE_URL}?{urlencode(query)}')


def _names(response: Any) -> set[str]:
    """The listed names of this module's files"""
    return {row['filename'] for row in response.get_json()['results'] if row['filename'].startswith(NAME_PREFIX)}


def _refused(response: Any, message: str) -> None:
    """A 400 with the message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()[MESSAGE_KEY] == message


def test_without_metadata_every_file_is_listed(rest_api) -> None:
    """It used to be a 500"""
    _upload(rest_api, DOTTED_NAME)

    response = _list(rest_api)

    assert response.status_code == HTTPStatus.OK
    assert _names(response) == {DOTTED_NAME}


def test_metadata_that_is_no_json_is_a_400(rest_api) -> None:
    """It used to be a 500"""
    _refused(_list(rest_api, metadata='{not json'), METADATA_FILTER_UNREADABLE_MSG)


@pytest.mark.parametrize('metadata', ['[1, 2]', '"parent"', 'null', '5'], ids=['list', 'string', 'null', 'number'])
def test_metadata_that_is_no_object_is_a_400(rest_api, metadata: str) -> None:
    """With the message that says so, not 'not provided'"""
    _refused(_list(rest_api, metadata=metadata), METADATA_FILTER_UNREADABLE_MSG)


@pytest.mark.parametrize('metadata', [None, '{not json'], ids=['absent', 'broken'])
def test_a_search_does_not_read_metadata(rest_api, metadata: str | None) -> None:
    """Absent or broken, the search answers"""
    _upload(rest_api, DOTTED_NAME)
    query: dict[str, Any] = {'searchTerm': NAME_PREFIX}
    if metadata is not None:
        query['metadata'] = metadata

    response = _list(rest_api, **query)

    assert response.status_code == HTTPStatus.OK
    assert _names(response) == {DOTTED_NAME}


def test_a_dot_is_matched_literally(rest_api) -> None:
    """a.b finds a.b, not axb"""
    _upload(rest_api, DOTTED_NAME)
    _upload(rest_api, LOOKALIKE_NAME)

    assert _names(_list(rest_api, searchTerm=DOTTED_NAME)) == {DOTTED_NAME}


@pytest.mark.parametrize('term', ['report (1)', '(1', '[', '1)'], ids=['brackets', 'open', 'bracket', 'close'])
def test_brackets_are_matched_literally(rest_api, term: str) -> None:
    """An unbalanced one used to fail the read with a 400"""
    _upload(rest_api, BRACKET_NAME)

    response = _list(rest_api, searchTerm=term)

    assert response.status_code == HTTPStatus.OK
    assert _names(response) == ({BRACKET_NAME} if term != '[' else set())


@pytest.mark.parametrize('metadata, message', [
    ({'parent': {'$ne': None}}, METADATA_FILTER_VALUE_MSG.format(key='parent')),
    ({'mime_type': {'$regex': '.*'}}, METADATA_FILTER_VALUE_MSG.format(key='mime_type')),
    ({'colour': 'red'}, UNKNOWN_METADATA_KEYS_MSG.format(keys='colour')),
    ({'reference': True}, METADATA_FILTER_REFERENCE_MSG),
    ({'reference': '7'}, METADATA_FILTER_REFERENCE_MSG),
], ids=['ne', 'regex', 'undeclared-key', 'boolean-reference', 'text-reference'])
def test_a_filter_off_the_metadata_is_a_400(rest_api, metadata: dict[str, Any], message: str) -> None:
    """Each with its message"""
    _refused(_list(rest_api, metadata=json.dumps(metadata)), message)


@pytest.mark.parametrize('metadata', [
    {'folder': False}, {'folder': True}, {'parent': 1, 'folder': False},
    {'reference': 5, 'reference_type': 'object'}, {'reference': [5, 6]},
], ids=['files', 'folders', 'folder-content', 'attachments', 'reference-list'])
def test_the_frontend_filters_pass(rest_api, metadata: dict[str, Any]) -> None:
    """What the file explorer and the attachment dialogs send"""
    assert _list(rest_api, metadata=json.dumps(metadata)).status_code == HTTPStatus.OK


def test_a_read_past_its_budget_is_the_shared_503(rest_api, monkeypatch) -> None:
    """Not the list's 400"""
    def _too_slow(*_args: Any, **_kwargs: Any) -> Any:
        timeout = DocumentQueryTimeLimitError('stopped', QUERY_TIME_LIMIT_MS)
        raise MediaFileManagerGetError(timeout) from timeout

    monkeypatch.setattr(MediaFilesManager, 'get_many_media_files', _too_slow)

    response = _list(rest_api, metadata=json.dumps({'folder': False}))

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.get_json()[MESSAGE_KEY] == QUERY_TIME_LIMIT_RESPONSE_MESSAGE.format(
        seconds=QUERY_TIME_LIMIT_MS // MILLISECONDS_PER_SECOND,
    )
