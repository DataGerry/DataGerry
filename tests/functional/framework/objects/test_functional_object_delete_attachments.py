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
Functional coverage of what deleting a CmdbObject does to its attachments

Over the single and the bulk delete route: the deleted objects' ids leave every attached media file's reference and
every file stays in the library. Pinned:

  - an upload's reference (one id) becomes an empty list; a file attached to several objects keeps the others
  - the bulk delete detaches its whole selection at once
  - a file of another reference kind, and a file attached only to an object that stays, are not touched
  - a failed detach is logged and the delete still succeeds
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import MediaFilesManager
from cmdb.manager.media_files_manager import MEDIA_FILES_COLLECTION
from cmdb.models.object_model import CmdbObject
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
from tests.functional.framework.objects.objects_route_helpers import (
    ROUTE_URL,
    drop_object,
    insert_object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

DELETED_OBJECT_ID: int = 9481
SECOND_DELETED_OBJECT_ID: int = 9482
BYSTANDER_ID: int = 9483
OBJECT_IDS: list[int] = [DELETED_OBJECT_ID, SECOND_DELETED_OBJECT_ID, BYSTANDER_ID]

UPLOAD_FILE_ID: int = 9491          # uploaded to the deleted object: one id
SHARED_FILE_ID: int = 9492          # attached to the deleted object and the bystander
BOTH_DELETED_FILE_ID: int = 9493    # attached to both deleted objects
OTHER_KIND_FILE_ID: int = 9494      # the deleted object's id under another reference kind
BYSTANDER_FILE_ID: int = 9495       # attached to the bystander alone
FILE_IDS: list[int] = [UPLOAD_FILE_ID, SHARED_FILE_ID, BOTH_DELETED_FILE_ID, OTHER_KIND_FILE_ID, BYSTANDER_FILE_ID]

OBJECT_KIND: str = 'object'
OTHER_KIND: str = 'report'
OBJECT_VALUE: str = 'attachment-cascade'


def _file(public_id: int, reference: int | list[int], reference_type: str = OBJECT_KIND) -> dict[str, Any]:
    """A stored media file document with the given reference"""
    return {
        'public_id': public_id, 'filename': f'attachment-{public_id}.txt', 'length': 0, 'chunkSize': 255,
        'metadata': {'reference': reference, 'reference_type': reference_type, 'folder': False, 'parent': None},
    }


@pytest.fixture(name='files')
def fixture_files(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Three objects and five media files referencing them; everything removed afterwards"""
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    files.delete_many({'public_id': {'$in': FILE_IDS}})

    for object_id in OBJECT_IDS:
        insert_object_doc(database_manager, database_name, object_id, OBJECT_VALUE)

    files.insert_many([
        _file(UPLOAD_FILE_ID, DELETED_OBJECT_ID),
        _file(SHARED_FILE_ID, [DELETED_OBJECT_ID, BYSTANDER_ID]),
        _file(BOTH_DELETED_FILE_ID, [DELETED_OBJECT_ID, SECOND_DELETED_OBJECT_ID]),
        _file(OTHER_KIND_FILE_ID, DELETED_OBJECT_ID, OTHER_KIND),
        _file(BYSTANDER_FILE_ID, BYSTANDER_ID),
    ])

    yield files

    files.delete_many({'public_id': {'$in': FILE_IDS}})
    for object_id in OBJECT_IDS:
        drop_object(database_manager, database_name, object_id)


def _references(files: Any) -> dict[int, Any]:
    """file id -> its stored reference, for every fixture file still stored"""
    return {document['public_id']: document['metadata']['reference']
            for document in files.find({'public_id': {'$in': FILE_IDS}})}


def _object_stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> bool:
    """Whether the object is still stored"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents(
        {'public_id': public_id},
    ) == 1


def test_the_single_delete_detaches_the_object_and_keeps_every_file(rest_api, files) -> None:
    """One id becomes an empty list, a list loses only the deleted id; the others are untouched"""
    response = rest_api.delete(f'{ROUTE_URL}/{DELETED_OBJECT_ID}')

    assert response.status_code == HTTPStatus.OK
    assert _references(files) == {
        UPLOAD_FILE_ID: [],
        SHARED_FILE_ID: [BYSTANDER_ID],
        BOTH_DELETED_FILE_ID: [SECOND_DELETED_OBJECT_ID],
        OTHER_KIND_FILE_ID: DELETED_OBJECT_ID,
        BYSTANDER_FILE_ID: BYSTANDER_ID,
    }


def test_the_bulk_delete_detaches_the_whole_selection(rest_api, files) -> None:
    """A file attached to both deleted objects loses both ids"""
    response = rest_api.delete(f'{ROUTE_URL}/delete/{DELETED_OBJECT_ID},{SECOND_DELETED_OBJECT_ID}')

    assert response.status_code == HTTPStatus.OK
    assert _references(files) == {
        UPLOAD_FILE_ID: [],
        SHARED_FILE_ID: [BYSTANDER_ID],
        BOTH_DELETED_FILE_ID: [],
        OTHER_KIND_FILE_ID: DELETED_OBJECT_ID,
        BYSTANDER_FILE_ID: BYSTANDER_ID,
    }


@pytest.mark.parametrize('url', [
    f'{ROUTE_URL}/{DELETED_OBJECT_ID}', f'{ROUTE_URL}/delete/{DELETED_OBJECT_ID}',
], ids=['single', 'bulk'])
def test_a_failed_detach_does_not_fail_the_delete(rest_api, files, monkeypatch: pytest.MonkeyPatch,
                                                  database_manager: MongoDatabaseManager, database_name: str,
                                                  url: str) -> None:
    """The object is already gone; its files keep their reference"""
    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise MediaFileManagerUpdateError('update failed')

    monkeypatch.setattr(MediaFilesManager, 'detach_objects', _fail)

    response = rest_api.delete(url)

    assert response.status_code == HTTPStatus.OK
    assert not _object_stored(database_manager, database_name, DELETED_OBJECT_ID)
    assert _references(files)[UPLOAD_FILE_ID] == DELETED_OBJECT_ID
