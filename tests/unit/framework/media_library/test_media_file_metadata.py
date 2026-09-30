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
Unit tests for the MediaFile metadata builder

`build_media_file_metadata` turns the metadata an upload arrived with into the sub-document stored with
the file. Pinned here: that the result carries EVERY declared key (so a stored file always has the whole
sub-document), that the values arrive unchanged - including the deliberate None for an unset
reference_type - that the mime type falls back to DEFAULT_MIME_TYPE for a content-type-less upload, that
the permission is read under the name it is stored as, and that an undeclared key is dropped rather than
written or raised over
"""
from typing import Any

import pytest

from cmdb.framework.media_library import (
    DEFAULT_MIME_TYPE,
    MediaFileMetadataKey,
    build_media_file_metadata,
)
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 7
PARENT_ID: int = 42
REFERENCE_ID: int = 1337
REFERENCE_TYPE: str = 'object'
MIME_TYPE: str = 'text/plain'
PERMISSION: str = 'read'


def _full_metadata() -> dict[str, Any]:
    """Upload metadata carrying every declared key, as the route assembles it for an attachment."""
    return {
        MediaFileMetadataKey.AUTHOR_ID.value: AUTHOR_ID,
        MediaFileMetadataKey.MIME_TYPE.value: MIME_TYPE,
        MediaFileMetadataKey.PARENT.value: PARENT_ID,
        MediaFileMetadataKey.REFERENCE.value: REFERENCE_ID,
        MediaFileMetadataKey.REFERENCE_TYPE.value: REFERENCE_TYPE,
        MediaFileMetadataKey.FOLDER.value: False,
        MediaFileMetadataKey.PERMISSION.value: PERMISSION,
    }


class TestBuildMediaFileMetadataShape:
    """The result is always the complete metadata sub-document, whatever the request carried."""

    def test_every_declared_key_is_written(self) -> None:
        """A full payload produces exactly the key set MediaFileMetadataKey names."""
        result = build_media_file_metadata(_full_metadata())

        assert set(result) == {key.value for key in MediaFileMetadataKey}

    def test_an_empty_payload_still_produces_every_key(self) -> None:
        """Nothing in means the whole sub-document out, so no stored file misses a key."""
        result = build_media_file_metadata({})

        assert set(result) == {key.value for key in MediaFileMetadataKey}

    def test_the_input_is_not_modified(self) -> None:
        """The builder reads its argument - the route keeps using the dict it passed in."""
        metadata = _full_metadata()

        build_media_file_metadata(metadata)

        assert metadata == _full_metadata()


class TestBuildMediaFileMetadataValues:
    """Declared values reach the document unchanged."""

    def test_values_are_passed_through(self) -> None:
        """Every declared key keeps the value the request carried."""
        result = build_media_file_metadata(_full_metadata())

        assert result == _full_metadata()

    def test_a_folder_flag_is_kept(self) -> None:
        """Creating a folder stores folder=True."""
        result = build_media_file_metadata({MediaFileMetadataKey.FOLDER.value: True})

        assert result[MediaFileMetadataKey.FOLDER.value] is True

    def test_a_reference_list_is_kept(self) -> None:
        """A reference may arrive as a list; the builder does not reshape it."""
        references: list[int] = [1, 2]

        result = build_media_file_metadata({MediaFileMetadataKey.REFERENCE.value: references})

        assert result[MediaFileMetadataKey.REFERENCE.value] == references

    def test_the_permission_is_read_under_its_stored_name(self) -> None:
        """The key is 'permission' on the way in and out, never 'permissions'."""
        result = build_media_file_metadata({MediaFileMetadataKey.PERMISSION.value: PERMISSION})

        assert result[MediaFileMetadataKey.PERMISSION.value] == PERMISSION

    def test_a_stored_document_can_be_rebuilt_from_itself(self) -> None:
        """Feeding a stored sub-document back in yields the same document - the round trip is closed."""
        stored = build_media_file_metadata(_full_metadata())

        assert build_media_file_metadata(stored) == stored


class TestBuildMediaFileMetadataDefaults:
    """What an upload does not say is filled in the same way every time."""

    @pytest.mark.parametrize('missing_key', [
        MediaFileMetadataKey.AUTHOR_ID,
        MediaFileMetadataKey.PARENT,
        MediaFileMetadataKey.REFERENCE,
        MediaFileMetadataKey.REFERENCE_TYPE,
        MediaFileMetadataKey.PERMISSION,
    ])
    def test_an_absent_key_is_stored_as_none(self, missing_key: MediaFileMetadataKey) -> None:
        """An unset key is present and null, never absent."""
        metadata = _full_metadata()
        del metadata[missing_key.value]

        result = build_media_file_metadata(metadata)

        assert result[missing_key.value] is None

    def test_an_unset_reference_type_stays_none(self) -> None:
        """None is NOT normalised to the empty string - storing must not change what the metadata says."""
        result = build_media_file_metadata({MediaFileMetadataKey.REFERENCE_TYPE.value: None})

        assert result[MediaFileMetadataKey.REFERENCE_TYPE.value] is None

    def test_an_absent_folder_flag_means_a_file(self) -> None:
        """Without the flag the entry is a file, not a folder."""
        result = build_media_file_metadata({})

        assert result[MediaFileMetadataKey.FOLDER.value] is False

    @pytest.mark.parametrize('stored_mime_type', [None, ''])
    def test_a_missing_mime_type_falls_back_to_the_default(self, stored_mime_type: str | None) -> None:
        """werkzeug answers '' for a form part without a content type; '' is worse than a generic type."""
        result = build_media_file_metadata({MediaFileMetadataKey.MIME_TYPE.value: stored_mime_type})

        assert result[MediaFileMetadataKey.MIME_TYPE.value] == DEFAULT_MIME_TYPE

    def test_an_absent_mime_type_falls_back_to_the_default(self) -> None:
        """The key does not have to be there at all for the fallback to apply."""
        result = build_media_file_metadata({})

        assert result[MediaFileMetadataKey.MIME_TYPE.value] == DEFAULT_MIME_TYPE


class TestBuildMediaFileMetadataUnknownKeys:
    """Keys the media library does not declare never reach the database."""

    def test_an_undeclared_key_is_dropped(self) -> None:
        """A caller that bypasses the route cannot store a key nothing reads back."""
        result = build_media_file_metadata({**_full_metadata(), 'bogus': 'value'})

        assert 'bogus' not in result

    def test_an_undeclared_key_does_not_raise(self) -> None:
        """A TypeError here is turned into a failed insert by the manager."""
        result = build_media_file_metadata({'public_id': 5})

        assert set(result) == {key.value for key in MediaFileMetadataKey}
