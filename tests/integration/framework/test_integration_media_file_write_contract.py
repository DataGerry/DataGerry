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
Integration tests for the MediaFile write rules against a real MongoDB GridFS

The route helpers with a real `MediaFilesManager`:

  - `abort_unless_usable_parent` walks a real folder chain: a move into the own subtree is refused at any
    depth, a move elsewhere passes, and a loop already stored above the target ends the walk
  - `unique_name_filter` is a filter GridFS honours: the entry itself is no clash, another entry of the
    name is, so `create_attachment_name` renames only then
  - `build_updated_file_data` + `update_file` store the same document twice over (re-run safe)
"""
from io import BytesIO
from typing import Any

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.framework.media_library import MediaFile, MediaFileMetadataKey
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import PARENT_CYCLE_MSG
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    abort_unless_usable_parent,
    build_updated_file_data,
    create_attachment_name,
    unique_name_filter,
)
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 1
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
NAME_PREFIX: str = 'dg-wci-'

# The depth of the seeded folder chain the walk climbs
CHAIN_DEPTH: int = 6

HTTP_BAD_REQUEST: int = 400


@pytest.fixture(name='manager')
def fixture_manager(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A MediaFilesManager on the test database, inside a request context; this module's entries purged"""
    files = database_manager.get_collection(FILES_COLLECTION, database_name)
    chunks = database_manager.get_collection(f'{MediaFile.COLLECTION}.chunks', database_name)

    def _purge() -> None:
        for doc in list(files.find({'filename': {'$regex': NAME_PREFIX}})):
            chunks.delete_many({'files_id': doc['_id']})
            files.delete_one({'_id': doc['_id']})

    _purge()

    with rest_api.application.test_request_context():
        yield MediaFilesManager(database_manager)

    _purge()


def _insert(manager: MediaFilesManager, name: str, parent: int | None = None, folder: bool = False) -> int:
    """Stores an entry and answers its public_id"""
    upload = FileStorage(stream=BytesIO(b'x'), filename=f'{NAME_PREFIX}{name}', content_type='text/plain')
    stored = manager.insert_file(upload, {
        MediaFileMetadataKey.AUTHOR_ID.value: AUTHOR_ID,
        MediaFileMetadataKey.PARENT.value: parent,
        MediaFileMetadataKey.FOLDER.value: folder,
    })

    return stored['public_id']


def _chain(manager: MediaFilesManager) -> list[int]:
    """A chain of nested folders, outermost first"""
    ids: list[int] = []

    for depth in range(CHAIN_DEPTH):
        ids.append(_insert(manager, f'level-{depth}', ids[-1] if ids else None, folder=True))

    return ids


def _stored(manager: MediaFilesManager, public_id: int) -> dict[str, Any]:
    """The stored document as the routes read it"""
    return manager.get_file(metadata={'public_id': public_id})


class TestParentWalk:
    """abort_unless_usable_parent over a real folder chain"""

    def test_a_move_into_the_own_subtree_is_refused_at_any_depth(self, manager: MediaFilesManager) -> None:
        """The outermost folder into its deepest descendant"""
        chain = _chain(manager)

        with pytest.raises(HTTPException) as exc_info:
            abort_unless_usable_parent(manager, chain[-1], moved_id=chain[0])

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert exc_info.value.description == PARENT_CYCLE_MSG

    def test_a_move_up_the_chain_passes(self, manager: MediaFilesManager) -> None:
        """The deepest folder next to the outermost one"""
        chain = _chain(manager)

        abort_unless_usable_parent(manager, chain[0], moved_id=chain[-1])

    def test_a_loop_already_stored_ends_the_walk(self, manager: MediaFilesManager,
                                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Two folders stored naming each other: the walk stops instead of spinning"""
        first = _insert(manager, 'loop-a', folder=True)
        second = _insert(manager, 'loop-b', first, folder=True)
        database_manager.get_collection(FILES_COLLECTION, database_name).update_one(
            {'public_id': first}, {'$set': {'metadata.parent': second}},
        )
        moved = _insert(manager, 'moved', folder=True)

        abort_unless_usable_parent(manager, first, moved_id=moved)


class TestUniqueNameFilter:
    """The filter excluding the entry itself, as GridFS evaluates it"""

    def test_the_entry_itself_is_no_clash(self, manager: MediaFilesManager) -> None:
        """A kept name stays"""
        file_id = _insert(manager, 'alone.txt')
        data = _stored(manager, file_id)

        assert create_attachment_name(data['filename'], 0, unique_name_filter(data), manager) == data['filename']

    def test_another_entry_of_the_name_is(self, manager: MediaFilesManager) -> None:
        """The second of two same-named files in one folder is renamed"""
        _insert(manager, 'twin.txt')
        data = {'public_id': -1, 'filename': f'{NAME_PREFIX}twin.txt', 'metadata': {'parent': None}}

        assert create_attachment_name(data['filename'], 0, unique_name_filter(data), manager) == \
            f'copy_(1)_{NAME_PREFIX}twin.txt'


class TestUpdateIsRerunSafe:
    """The same update twice stores the same document"""

    def test_a_repeated_update_changes_nothing_more(self, manager: MediaFilesManager) -> None:
        """Merge, store, merge again, store again"""
        file_id = _insert(manager, 'twice.txt')
        payload = {'public_id': file_id, 'filename': f'{NAME_PREFIX}twice-renamed.txt',
                   'metadata': {'folder': False, 'reference': [3], 'reference_type': 'object'}}

        manager.update_file(build_updated_file_data(_stored(manager, file_id), payload, AUTHOR_ID))
        first = _stored(manager, file_id)
        manager.update_file(build_updated_file_data(_stored(manager, file_id), payload, AUTHOR_ID))

        assert _stored(manager, file_id) == first
        assert first['metadata']['reference'] == [3]
