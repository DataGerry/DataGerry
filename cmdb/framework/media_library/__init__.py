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
Provides the MediaFile model, the builder of a file's metadata sub-document and the key enums of a
stored MediaFile document

Consumers import from this package path rather than from the modules inside it
"""
from .media_file_keys import GRIDFS_FILES_SUFFIX, MediaFileKey, MediaFileMetadataKey
from .media_file_metadata import DEFAULT_MIME_TYPE, build_media_file_metadata
from .base_media_file import BaseMediaFile
from .media_file import MediaFile
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'GRIDFS_FILES_SUFFIX',
    'MediaFileKey',
    'MediaFileMetadataKey',
    'DEFAULT_MIME_TYPE',
    'build_media_file_metadata',
    'BaseMediaFile',
    'MediaFile',
]
