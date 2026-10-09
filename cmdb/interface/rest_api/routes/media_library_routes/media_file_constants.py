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
Rights and request keys of the MediaFile REST routes

The DOCUMENT-key enums live in `cmdb.framework.media_library.media_file_keys`, because
`MediaFilesManager` addresses the same document and a manager may not import from the interface layer.
They are re-exported here so a route reads its keys from one module
"""
from cmdb.utils import BaseStrEnum
from cmdb.framework.media_library.media_file_keys import MediaFileKey, MediaFileMetadataKey
from cmdb.models.right_model.right_constants import ObjectRightName
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DOWNLOAD_MIMETYPE',
    'UNPAGED_LIMIT',
    'BODY_NOT_AN_OBJECT_MSG',
    'METADATA_NOT_AN_OBJECT_MSG',
    'UNKNOWN_METADATA_KEYS_MSG',
    'UPLOAD_FILENAME_MSG',
    'PARENT_NOT_FOUND_MSG',
    'PARENT_NOT_A_FOLDER_MSG',
    'PARENT_CYCLE_MSG',
    'FOLDER_FLAG_IMMUTABLE_MSG',
    'MediaFileRight',
    'MediaFileRequestKey',
    'MediaFileKey',
    'MediaFileMetadataKey',
]

# The list route's page size when the request names none: every match. The attachment dialogs and the
# object's attachment badge send no limit and need the whole list; a client that pages says so
UNPAGED_LIMIT: int = 0

# What a download is answered as, whatever the stored mime type - the browser saves it rather than
# rendering it
DOWNLOAD_MIMETYPE: str = 'application/octet-stream'

# Refusals of a write: the update body / upload metadata shape, the uploaded file's name, and the tree rules
BODY_NOT_AN_OBJECT_MSG: str = 'The request body must be a JSON object!'
METADATA_NOT_AN_OBJECT_MSG: str = 'The metadata of an upload must be an object!'
UNKNOWN_METADATA_KEYS_MSG: str = 'The metadata carries unknown key(s): {keys}!'
UPLOAD_FILENAME_MSG: str = "The uploaded file's name {problem}!"
PARENT_NOT_FOUND_MSG: str = 'The parent folder with ID: {parent} was not found!'
PARENT_NOT_A_FOLDER_MSG: str = 'The parent with ID: {parent} is a file, not a folder!'
PARENT_CYCLE_MSG: str = 'A folder can not be moved into itself or into one of its own subfolders!'
FOLDER_FLAG_IMMUTABLE_MSG: str = 'An update can not turn a file into a folder or a folder into a file!'


class MediaFileRight(BaseStrEnum):
    """
    ACL right identifiers guarding the MediaFile REST routes

    The media library has NO right family of its own: it borrows the CmdbObject rights, so whoever may
    read objects may read files and whoever may edit objects may upload and delete them. Named here so
    the borrowing is visible in one place - whether the library should get its own rights is a filed
    decision, and this enum is where that change would land
    """
    VIEW = ObjectRightName.VIEW.value
    EDIT = ObjectRightName.EDIT.value


class MediaFileRequestKey(BaseStrEnum):
    """
    Keys the MediaFile routes read out of a request

    FILE and METADATA are the two parts of the upload form; ATTACHMENT is the update route's query
    parameter, carrying REFERENCE - "this write only re-points a reference, so leave the filename alone".
    METADATA and SEARCH_TERM are also the two optional query parameters the list route filters by
    """
    FILE = 'file'
    METADATA = 'metadata'
    ATTACHMENT = 'attachment'
    REFERENCE = 'reference'
    SEARCH_TERM = 'searchTerm'
