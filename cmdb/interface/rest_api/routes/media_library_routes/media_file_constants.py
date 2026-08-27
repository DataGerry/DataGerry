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
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MediaFileRight',
    'MediaFileRequestKey',
    'MediaFileKey',
    'MediaFileMetadataKey',
]


class MediaFileRight(BaseStrEnum):
    """
    ACL right identifiers guarding the MediaFile REST routes

    The media library has NO right family of its own: it borrows the CmdbObject rights, so whoever may
    read objects may read files and whoever may edit objects may upload and delete them. Named here so
    the borrowing is visible in one place - whether the library should get its own rights is a filed
    decision, and this enum is where that change would land
    """
    VIEW = 'base.framework.object.view'
    EDIT = 'base.framework.object.edit'


class MediaFileRequestKey(BaseStrEnum):
    """
    Keys the MediaFile routes read out of a request

    FILE and METADATA are the two parts of the upload form; ATTACHMENT is the update route's query
    parameter, carrying REFERENCE - "this write only re-points a reference, so leave the filename alone"
    """
    FILE = 'file'
    METADATA = 'metadata'
    ATTACHMENT = 'attachment'
    REFERENCE = 'reference'
