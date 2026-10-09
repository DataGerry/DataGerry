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
Functional coverage for the MediaFile write contract, through POST and PUT /media_file/

Pinned:

  - the upload's metadata holds declared keys of their declared types, its file name follows the naming
    rule, and its parent is an existing folder - each refusal a 400 naming the reason
  - the update body is held to the update schema (a malformed one is a 400, it used to be a 500), its
    metadata is stored whole with the mime type kept, and the folder flag can not change
  - an update keeping its name keeps it (it used to rename the file to copy_(1)_<name>); a real clash
    is still renamed
  - a folder can not be moved into itself or its subtree, nor anything under a file or a missing folder;
    a refused move leaves the tree deletable
  - the frontend's request shapes still pass
"""
import json
import re
from io import BytesIO
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.media_library import MediaFile, MediaFileMetadataKey
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    FOLDER_FLAG_IMMUTABLE_MSG,
    PARENT_CYCLE_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/media_file/'
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
CHUNKS_COLLECTION: str = f'{MediaFile.COLLECTION}.chunks'
NAME_PREFIX: str = 'dg-wc-'
MISSING_ID: int = 987654
COPY_PREFIX: str = 'copy_(1)_'
STORED_MIME_TYPE: str = 'text/plain'


@pytest.fixture(name='files')
def fixture_files(database_manager: MongoDatabaseManager, database_name: str):
    """The GridFS files collection, purged of this module's entries before and after each test"""
    files = database_manager.get_collection(FILES_COLLECTION, database_name)
    chunks = database_manager.get_collection(CHUNKS_COLLECTION, database_name)

    def _purge() -> None:
        for doc in list(files.find({'filename': {'$regex': f'^({re.escape(COPY_PREFIX)})?{NAME_PREFIX}'}})):
            chunks.delete_many({'files_id': doc['_id']})
            files.delete_one({'_id': doc['_id']})

    _purge()
    yield files
    _purge()


def _upload(rest_api, name: str, metadata: dict[str, Any] | None = None):
    """Uploads a small text file under the module's name prefix"""
    form = {'file': (BytesIO(b'content'), f'{NAME_PREFIX}{name}'), 'metadata': json.dumps(metadata or {})}

    return rest_api.post(BASE_URL, data=form, content_type='multipart/form-data')


def _upload_id(rest_api, name: str, metadata: dict[str, Any] | None = None) -> int:
    """Uploads and answers the new entry's public_id"""
    response = _upload(rest_api, name, metadata)
    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return response.get_json()['result_id']


def _stored(files, public_id: int) -> dict[str, Any]:
    """The stored document, without its ObjectId and upload date"""
    return files.find_one({'public_id': public_id}, {'_id': 0, 'uploadDate': 0})


def _put(rest_api, body: Any, reference: bool = False):
    """Sends an update the way the file explorer does"""
    return rest_api.put(f'{BASE_URL}?attachment={json.dumps({"reference": reference})}', data=json.dumps(body),
                        content_type='application/json')


def _element(files, public_id: int, **metadata: Any) -> dict[str, Any]:
    """The frontend's FileElement for a stored entry, with metadata edits applied"""
    stored = _stored(files, public_id)
    stored['metadata'] = {**stored['metadata'], **metadata}

    return {**stored, 'size': 7, 'children': [], 'hasSubFolders': False, 'inProcess': False}


@pytest.mark.usefixtures('files')
class TestUploadContract:
    """POST /media_file/ refuses unusable metadata before anything is stored"""

    @pytest.mark.parametrize(('key', 'value'), [
        ('folder', 'yes'), ('parent', 'abc'), ('reference', 'x'), ('reference', True), ('author_id', [1]),
    ])
    def test_a_wrongly_typed_value_is_a_400_naming_the_key(self, rest_api, files, key: str, value: Any) -> None:
        """Each was stored as sent, or answered "Metadata was not provided!" """
        response = _upload(rest_api, f'typed-{key}.txt', {key: value})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert key in response.get_json()['message']
        assert files.count_documents({'filename': f'{NAME_PREFIX}typed-{key}.txt'}) == 0

    def test_a_missing_parent_is_a_400(self, rest_api, files) -> None:
        """A file inside a folder that does not exist was stored"""
        response = _upload(rest_api, 'orphan.txt', {'parent': MISSING_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert files.count_documents({'filename': f'{NAME_PREFIX}orphan.txt'}) == 0

    def test_a_file_as_parent_is_a_400(self, rest_api) -> None:
        """Nothing sits inside a file"""
        file_id = _upload_id(rest_api, 'host.txt')

        assert _upload(rest_api, 'inside.txt', {'parent': file_id}).status_code == HTTPStatus.BAD_REQUEST

    def test_an_upload_into_a_folder_passes(self, rest_api, files) -> None:
        """The new-folder dialog and the explorer upload send {folder, parent}"""
        folder_id = _upload_id(rest_api, 'dir', {'folder': True, 'parent': None})
        file_id = _upload_id(rest_api, 'in-dir.txt', {'folder': False, 'parent': folder_id})

        assert _stored(files, file_id)['metadata']['parent'] == folder_id

    def test_an_attachment_upload_passes(self, rest_api, files) -> None:
        """The attachment dialog sends one reference and its type"""
        file_id = _upload_id(rest_api, 'attached.txt', {'reference': 12, 'reference_type': 'object'})

        assert _stored(files, file_id)['metadata']['reference'] == 12


class TestUpdateContract:
    """PUT /media_file/ holds its body to the update schema and stores the metadata whole"""

    @pytest.mark.parametrize('body', [None, [1], 'text'])
    def test_a_body_that_is_not_an_object_is_a_400(self, rest_api, body: Any) -> None:
        """null used to answer 500"""
        assert _put(rest_api, body).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize(('key', 'value'), [
        ('metadata', [1]), ('public_id', 'id'), ('filename', 7), ('filename', ''), ('filename', 'a/b'),
    ])
    def test_an_unusable_value_is_a_400_and_nothing_changes(self, rest_api, files, key: str, value: Any) -> None:
        """A list as metadata used to answer 500; the names used to be stored"""
        file_id = _upload_id(rest_api, f'u-{key}.txt')
        before = _stored(files, file_id)

        response = _put(rest_api, {**_element(files, file_id), key: value})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert key in response.get_json()['message']
        assert _stored(files, file_id) == before

    def test_an_undeclared_metadata_key_is_a_400(self, rest_api, files) -> None:
        """It used to be stored"""
        file_id = _upload_id(rest_api, 'evil.txt')

        response = _put(rest_api, _element(files, file_id, evil=1))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'evil' not in _stored(files, file_id)['metadata']

    def test_the_metadata_is_stored_whole_and_the_mime_type_kept(self, rest_api, files) -> None:
        """A partial sub-document used to be stored as sent, the client's mime type with it"""
        file_id = _upload_id(rest_api, 'whole.txt', {'reference': 3, 'reference_type': 'object'})
        body = {**_element(files, file_id), 'metadata': {'folder': False, 'mime_type': 'evil/x'}}

        assert _put(rest_api, body).status_code == HTTPStatus.OK

        metadata = _stored(files, file_id)['metadata']
        assert set(metadata) == {key.value for key in MediaFileMetadataKey}
        assert metadata['mime_type'] == STORED_MIME_TYPE
        assert metadata['reference'] is None

    def test_the_folder_flag_can_not_change(self, rest_api, files) -> None:
        """A folder holding files would orphan them as a 'file'"""
        folder_id = _upload_id(rest_api, 'flag-dir', {'folder': True})

        response = _put(rest_api, _element(files, folder_id, folder=False))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == FOLDER_FLAG_IMMUTABLE_MSG
        assert _stored(files, folder_id)['metadata']['folder'] is True

    def test_attaching_a_reference_list_passes(self, rest_api, files) -> None:
        """The attachment dialogs send the reference list with attachment={"reference": true}"""
        file_id = _upload_id(rest_api, 'refs.txt')

        response = _put(rest_api, _element(files, file_id, reference=[4, 5], reference_type='object'), True)

        assert response.status_code == HTTPStatus.OK
        assert _stored(files, file_id)['metadata']['reference'] == [4, 5]


class TestUpdateKeepsItsName:
    """The uniqueness check no longer finds the entry itself"""

    def test_a_move_into_the_current_folder_keeps_the_name(self, rest_api, files) -> None:
        """The move dialog offers the folder the file is in - this renamed it to copy_(1)_<name>"""
        folder_id = _upload_id(rest_api, 'keep-dir', {'folder': True})
        file_id = _upload_id(rest_api, 'keep.txt', {'parent': folder_id})

        response = _put(rest_api, _element(files, file_id, parent=folder_id))

        assert response.status_code == HTTPStatus.OK
        assert _stored(files, file_id)['filename'] == f'{NAME_PREFIX}keep.txt'

    def test_a_real_clash_is_still_renamed(self, rest_api, files) -> None:
        """Renaming onto another file's name in the same folder"""
        _upload_id(rest_api, 'taken.txt')
        file_id = _upload_id(rest_api, 'other.txt')

        response = _put(rest_api, {**_element(files, file_id), 'filename': f'{NAME_PREFIX}taken.txt'})

        assert response.status_code == HTTPStatus.OK
        assert _stored(files, file_id)['filename'] == f'{COPY_PREFIX}{NAME_PREFIX}taken.txt'


class TestMoveRules:
    """A move needs an existing folder outside the moved entry's subtree"""

    @pytest.fixture(name='tree')
    def fixture_tree(self, rest_api) -> dict[str, int]:
        """outer > inner, plus a sibling folder and a file at the root"""
        outer = _upload_id(rest_api, 'outer', {'folder': True})
        inner = _upload_id(rest_api, 'inner', {'folder': True, 'parent': outer})
        sibling = _upload_id(rest_api, 'sibling', {'folder': True})
        plain = _upload_id(rest_api, 'plain.txt')

        return {'outer': outer, 'inner': inner, 'sibling': sibling, 'plain': plain}

    @pytest.mark.parametrize('target', ['outer', 'inner'])
    def test_a_folder_can_not_move_into_itself_or_below(self, rest_api, files, tree, target: str) -> None:
        """It used to vanish from the tree and its delete answered 500"""
        response = _put(rest_api, _element(files, tree['outer'], parent=tree[target]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PARENT_CYCLE_MSG
        assert _stored(files, tree['outer'])['metadata']['parent'] is None
        assert rest_api.delete(f"{BASE_URL}{tree['outer']}").status_code == HTTPStatus.OK

    @pytest.mark.parametrize('target', ['plain', 'missing'])
    def test_a_move_under_a_file_or_a_missing_folder_is_a_400(self, rest_api, files, tree, target: str) -> None:
        """Only a folder can hold entries"""
        parent = tree.get(target, MISSING_ID)

        assert _put(rest_api, _element(files, tree['inner'], parent=parent)).status_code == HTTPStatus.BAD_REQUEST

    def test_a_move_into_another_branch_passes(self, rest_api, files, tree) -> None:
        """The ordinary move"""
        response = _put(rest_api, _element(files, tree['inner'], parent=tree['sibling']))

        assert response.status_code == HTTPStatus.OK
        assert _stored(files, tree['inner'])['metadata']['parent'] == tree['sibling']

    def test_an_entry_that_stays_put_keeps_a_stored_parent(self, rest_api, files, tree) -> None:
        """Only a move is judged: a rename of an entry stored under a vanished folder still works"""
        files.update_one({'public_id': tree['plain']}, {'$set': {'metadata.parent': MISSING_ID}})

        response = _put(rest_api, {**_element(files, tree['plain']), 'filename': f'{NAME_PREFIX}renamed.txt'})

        assert response.status_code == HTTPStatus.OK
        assert _stored(files, tree['plain'])['filename'] == f'{NAME_PREFIX}renamed.txt'
