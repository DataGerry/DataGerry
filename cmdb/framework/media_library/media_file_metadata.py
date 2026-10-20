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
Builds the metadata sub-document a MediaFile is stored with

A MediaFile is a GridFS file document, and everything DataGerry knows about it beyond its name and its
content lives in that document's ``metadata`` sub-document: which folder it sits in, whether it IS a
folder, and what it is attached to. The upload route assembles that metadata from the request and stamps
the server-owned parts onto it; this module turns the result into the document that is actually stored

The values are kept as they arrive, with the mime type as the single exception (see DEFAULT_MIME_TYPE).
In particular an unset reference_type stays None rather than becoming an empty string, so storing a
metadata does not change what it says
"""
from typing import Any

from cmdb.framework.media_library.media_file_keys import MediaFileMetadataKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DEFAULT_MIME_TYPE',
    'build_media_file_metadata',
]

# What a file is stored as when the upload carries no content type of its own - werkzeug answers an
# empty string for a form part without one, and an empty mime type is worse than a generic one
DEFAULT_MIME_TYPE: str = 'application/json'

# A folder flag that the request does not carry means "this is a file"
DEFAULT_IS_FOLDER: bool = False


def build_media_file_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the metadata sub-document of a MediaFile out of the metadata an upload arrived with

    Every key of MediaFileMetadataKey is present in the result, so a stored file always carries the whole
    sub-document: a key the request does not carry is stored as None, except the folder flag which
    defaults to False and the mime type which falls back to DEFAULT_MIME_TYPE. Keys the media library
    does not declare are dropped - the upload route refuses those with a 400 before the write ever
    happens, and dropping them here keeps a caller that bypasses the route from storing keys that
    nothing can read back

    Args:
        metadata (dict[str, Any]): The metadata as the upload route assembled it, i.e. what the client
            sent plus the server-owned author_id and mime_type

    Returns:
        dict[str, Any]: The metadata sub-document to store with the file
    """
    return {
        MediaFileMetadataKey.REFERENCE.value: metadata.get(MediaFileMetadataKey.REFERENCE.value),
        MediaFileMetadataKey.REFERENCE_TYPE.value: metadata.get(MediaFileMetadataKey.REFERENCE_TYPE.value),
        MediaFileMetadataKey.MIME_TYPE.value: (metadata.get(MediaFileMetadataKey.MIME_TYPE.value)
                                               or DEFAULT_MIME_TYPE),
        MediaFileMetadataKey.AUTHOR_ID.value: metadata.get(MediaFileMetadataKey.AUTHOR_ID.value),
        MediaFileMetadataKey.FOLDER.value: metadata.get(MediaFileMetadataKey.FOLDER.value, DEFAULT_IS_FOLDER),
        MediaFileMetadataKey.PARENT.value: metadata.get(MediaFileMetadataKey.PARENT.value),
        MediaFileMetadataKey.PERMISSION.value: metadata.get(MediaFileMetadataKey.PERMISSION.value),
    }
