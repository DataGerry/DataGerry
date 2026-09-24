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
Unit tests for MediaFile and its BaseMediaFile base

One GridFS file document of the media library. Instances are built straight from a stored document
(`MediaFile(**grid._file)`), so the constructor takes GridFS' own camelCase key names and renames
them to the snake_case attributes the routes read; `to_json` turns one back into the body the read
routes answer with.

**The index contract.** A bare `INDEX_KEYS` declaring a
unique index over `name`, a key no GridFS document carries, and nothing ever built it: `MediaFile` is
absent from `framework/constants.__COLLECTIONS__` and cannot be added to it, because that loop indexes
a class's COLLECTION verbatim while `MediaFile.COLLECTION` is the GridFS *bucket* name. The tests
below now pin the corrected declaration - unique over `(filename, metadata.parent)`, the pair the
upload and update routes already treat as a file's identity - and the reconciliation lives in
`CollectionValidator.init_media_library_indexes`, with `updater_20260916` de-duplicating what existing
databases hold.

One finding is still open and still recorded rather than asserted: `REQUIRED_INIT_KEYS` also names
`name`. It is dead - `MediaFile` is not a `CmdbDAO`, so nothing reads it - and it was left alone
rather than folded into the index fix.
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo import IndexModel

from cmdb.framework.media_library import BaseMediaFile, MediaFile
from cmdb.framework.media_library.media_file_keys import (
    MediaFileKey,
    MediaFileMetadataKey,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
)

from cmdb.errors.cmdb_object import NoPublicIDError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 42
FILENAME: str = 'diagram.png'
CHUNK_SIZE: int = 261120
SIZE: int = 1024
UPLOAD_DATE: datetime = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
METADATA: dict[str, Any] = {'parent': 0, 'mime_type': 'image/png', 'author_id': 1}


def _media_file(**overrides: Any) -> MediaFile:
    """Builds a MediaFile from a GridFS-shaped document."""
    document: dict[str, Any] = {
        'filename': FILENAME,
        'chunkSize': CHUNK_SIZE,
        'uploadDate': UPLOAD_DATE,
        'metadata': dict(METADATA),
        'length': SIZE,
        'public_id': PUBLIC_ID,
        **overrides,
    }

    return MediaFile(**document)


class TestConstruction:
    """The GridFS document's own key names become this class's attributes."""

    def test_renames_the_gridfs_keys(self) -> None:
        """`chunkSize` / `uploadDate` / `length` are GridFS spellings, not DataGerry ones."""
        media_file = _media_file()

        assert media_file.chunk_size == CHUNK_SIZE
        assert media_file.upload_date == UPLOAD_DATE
        assert media_file.size == SIZE

    def test_keeps_the_filename_as_is(self) -> None:
        """`filename` is the one GridFS key whose name the class keeps."""
        assert _media_file().filename == FILENAME

    def test_the_remaining_keys_become_attributes(self) -> None:
        """`public_id` arrives through **kwargs and is set by the base class's sweep."""
        assert _media_file().public_id == PUBLIC_ID

    def test_an_unknown_key_is_carried_rather_than_refused(self) -> None:
        """
        A stored document may carry keys this version does not know

        The base sets every kwarg, so a GridFS document written by a newer version still loads
        instead of failing the read of the whole media library.
        """
        # pylint: disable=no-member  # the attribute is set by the base class's kwarg sweep
        assert _media_file(contentType='image/png').contentType == 'image/png'

    def test_public_id_defaults_to_none(self) -> None:
        """The base seeds it before the kwarg sweep, so `get_public_id` has something to refuse."""
        assert BaseMediaFile().public_id is None

    def test_the_metadata_sub_document_is_passed_through(self) -> None:
        """`build_media_file_metadata` shapes it on the way in; this class does not touch it."""
        assert _media_file().get_metadata() == METADATA


class TestGetPublicId:
    """The identifier every route addresses a file by."""

    def test_returns_the_assigned_id(self) -> None:
        """The ordinary case for a stored file."""
        assert _media_file().get_public_id() == PUBLIC_ID

    @pytest.mark.parametrize('value', [0, None], ids=['zero', 'unset'])
    def test_an_unassigned_id_is_refused(self, value: Any) -> None:
        """
        0 and None both mean "not stored yet", and neither addresses a file

        `to_json` reads through this, so returning a falsy id would put `public_id: 0` in a response
        and hand the frontend a link to nothing.
        """
        with pytest.raises(NoPublicIDError):
            _media_file(public_id=value).get_public_id()


class TestGetFilename:
    """The file's name, as shown in the library and used for the copy-suffixing."""

    def test_returns_the_name(self) -> None:
        """The ordinary case."""
        assert _media_file().get_filename() == FILENAME

    def test_a_missing_name_is_an_empty_string(self) -> None:
        """
        None would reach the frontend as a blank row it cannot act on

        An empty string at least renders and can be renamed; the uniqueness suffixing in
        `create_attachment_name` also does string work on this value.
        """
        assert _media_file(filename=None).get_filename() == ""


class TestTheRemainingGetters:
    """The plain reads `to_json` and the routes are built from."""

    def test_get_chunk_size(self) -> None:
        """
        GridFS' chunk width, 255 KiB by default

        Has no caller in `cmdb/` today - it is the one getter of this set that nothing reads - but it
        is part of a coherent accessor set over the stored document, so it is covered rather than
        removed.
        """
        assert _media_file().get_chunk_size() == CHUNK_SIZE

    def test_get_upload_date(self) -> None:
        """When the CONTENT was stored - a metadata-only edit leaves it alone."""
        assert _media_file().get_upload_date() == UPLOAD_DATE

    def test_get_size(self) -> None:
        """The content length in bytes."""
        assert _media_file().get_size() == SIZE


class TestToJson:
    """The body the read routes answer with."""

    def test_emits_the_public_shape(self) -> None:
        """Note what is absent: the chunk size and GridFS' internal `_id` are not part of it."""
        assert MediaFile.to_json(_media_file()) == {
            'public_id': PUBLIC_ID,
            'filename': FILENAME,
            'size': SIZE,
            'upload_date': UPLOAD_DATE,
            'metadata': METADATA,
        }

    def test_it_refuses_a_file_with_no_public_id(self) -> None:
        """It serialises through `get_public_id`, so an unstored file cannot be answered with."""
        with pytest.raises(NoPublicIDError):
            MediaFile.to_json(_media_file(public_id=None))


class TestGetIndexKeys:
    """
    The declared indexes, combined with the base's `public_id` index

    Called on every boot: `CollectionValidator.init_media_library_indexes` asks the
    class for them and reconciles them onto `media.libary.files`, the collection GridFS keeps the file
    documents in.
    """

    def test_combines_the_class_and_super_keys(self) -> None:
        """A subclass's own indexes do not replace the `public_id` index every media file needs."""
        assert len(MediaFile.get_index_keys()) == len(MediaFile.INDEX_KEYS) + len(MediaFile.SUPER_INDEX_KEYS)

    def test_it_answers_index_models(self) -> None:
        """`create_indexes` takes pymongo IndexModels, not the raw dicts."""
        assert all(isinstance(index, IndexModel) for index in MediaFile.get_index_keys())

    def test_the_base_alone_answers_only_the_public_id_index(self) -> None:
        """`BaseMediaFile.INDEX_KEYS` is empty, so a subclass that declares none still gets that one."""
        assert len(BaseMediaFile.get_index_keys()) == len(BaseMediaFile.SUPER_INDEX_KEYS)

    def test_the_declared_index_names_fields_a_document_carries(self) -> None:
        """
        Every indexed key has to exist on a stored document, or the index indexes nothing

        This replaces the pin that recorded the opposite: `INDEX_KEYS` named `name`, which no GridFS
        document has, so a unique index over it would have let the collection hold exactly one file.
        """
        media_file = _media_file()

        assert not hasattr(media_file, 'name')
        assert hasattr(media_file, 'filename')
        assert MediaFileMetadataKey.PARENT.value in media_file.metadata

    def test_the_index_is_the_filename_parent_pair(self) -> None:
        """A file's identity is its name INSIDE its folder - the same name in two folders is legal."""
        declared = {key for index in MediaFile.INDEX_KEYS for key, _ in index['keys']}

        assert declared == {MediaFileKey.FILENAME.value, MEDIA_FILE_PARENT_PATH}

    def test_the_filename_index_is_unique(self) -> None:
        """Uniqueness is the point: without it the clash check is a read-then-write two uploads pass."""
        declaration = next(
            index for index in MediaFile.INDEX_KEYS
            if index['name'] == MEDIA_FILE_FILENAME_PARENT_INDEX_NAME
        )

        assert declaration['unique'] is True

    def test_the_index_is_declared_on_the_pair_in_order(self) -> None:
        """`filename` leads, so the index also serves a lookup by name alone (its prefix)."""
        declaration = next(
            index for index in MediaFile.INDEX_KEYS
            if index['name'] == MEDIA_FILE_FILENAME_PARENT_INDEX_NAME
        )

        assert [key for key, _ in declaration['keys']] == [
            MediaFileKey.FILENAME.value,
            MEDIA_FILE_PARENT_PATH,
        ]
