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
Document-key enums for a stored MediaFile

A MediaFile is a GridFS file document, so its keys are the ones GridFS writes (``filename``,
``uploadDate``, ``_id``) plus the DataGerry ones stored alongside them (``public_id``) and the
``metadata`` sub-document the library uses as its tree and reference bookkeeping.

These live in the framework package rather than with the REST routes because both the routes AND
``MediaFilesManager`` address the same document, and a manager may not import from the interface layer
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MediaFileKey',
    'MediaFileMetadataKey',
]

# GridFS keeps a file's chunks in '<collection>.chunks' and its file documents in '<collection>.files'.
# Only the latter is addressable as a normal collection, which is what an update has to target
GRIDFS_FILES_SUFFIX: str = '.files'


class MediaFileKey(BaseStrEnum):
    """
    Keys of a stored MediaFile document (a GridFS file document)

    UPLOAD_DATE is written by GridFS when the CONTENT is stored; it is not a "last modified" stamp and
    a metadata-only edit leaves it alone

    Attributes:
        PUBLIC_ID: DataGerry's identifier for the file, assigned on insert
        FILENAME: The file's name, unique per metadata.parent folder
        METADATA: The metadata sub-document (see MediaFileMetadataKey)
        UPLOAD_DATE: When GridFS stored the file's content
    """
    PUBLIC_ID = 'public_id'
    FILENAME = 'filename'
    METADATA = 'metadata'
    UPLOAD_DATE = 'uploadDate'


class MediaFileMetadataKey(BaseStrEnum):
    """
    Keys inside a MediaFile's metadata sub-document

    PARENT is the folder the file sits in - the media library is a tree, and the pair
    (filename, metadata.parent) is what has to stay unique
    """
    AUTHOR_ID = 'author_id'
    MIME_TYPE = 'mime_type'
    PARENT = 'parent'
    REFERENCE = 'reference'
    REFERENCE_TYPE = 'reference_type'
