# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of MediaFile
"""
import logging
from typing import Any
from datetime import date

from cmdb.framework.media_library.base_media_file import BaseMediaFile
from cmdb.framework.media_library.media_file_metadata import FileMetadata
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.cmdb_object import NoPublicIDError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   MediaFile - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class MediaFile(BaseMediaFile):
    """Media Libary File"""

    COLLECTION = 'media.libary'
    REQUIRED_INIT_KEYS: list[str] = ['name']

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('name', CmdbDAO.DAO_ASCENDING)],
            'name': 'name',
            'unique': True
        }
    ]

    def __init__(self, filename: str, chunkSize, uploadDate, metadata, length, **kwargs) -> None:
        """
        Args:
            filename: name of this file
            active: is job executable
            sources: consists of multiple objects of a specific object type and a specific status
            destination: is an external system, where you want to push the yourcmdb objects
            variables: has a name and gets its value out of fields of the objects
            **kwargs: optional params
        """
        self.filename: str = filename
        self.chunk_size = chunkSize
        self.upload_date = uploadDate
        self.metadata = metadata
        self.size = length

        super().__init__(**kwargs)


    def get_public_id(self) -> int:
        """
        get the public id of current element

        Note:
            Since the models object is not initializable
            the child class object will inherit this function
            SHOULD NOT BE OVERWRITTEN!

        Returns:
            int: public id

        Raises:
            NoPublicIDError: if `public_id` is zero or not set
        """
        if self.public_id == 0 or self.public_id is None:
            raise NoPublicIDError("No public_id assigned!")

        return self.public_id


    def get_filename(self) -> str:
        """
        Get the name of file
        Returns:
            str: display filename
        """
        if self.filename is None:
            return ""

        return self.filename


    def get_chunk_size(self) -> bytes:
        """
        Get the size of each chunk in bytes.
        GridFS divides the document into chunks of size chunkSize,
        except for the last, which is only as large as needed.
        The default size is 255 kilobytes (kB).
        Returns:
            bytes: display chunkSize
        """
        return self.chunk_size


    def get_upload_date(self) -> date:
        """
        Get the date the document was first stored by GridFS.
        This value has the Date type.
        Returns:
            bytes: display upload Date
        """
        return self.upload_date


    def get_metadata(self) -> FileMetadata:
        """
        Get all metadata of the file
        The metadata fields:
            permission:   the action of officially allowing someone to do a particular thing
            ref_to:       ObjectId of Object (CmdbType, CmdbObject etc.)
            ref_to_type:  Strint: Type of Object (CmdbType, CmdbObject etc.)
            mime_type:    File type
        Returns:
            list: all sources
        """
        return self.metadata


    def get_size(self) -> bytes:
        """
        Get the size of the document in bytes.
        Returns:
            bytes: size of the document
        """
        return self.size


    @classmethod
    def to_json(cls, instance: "MediaFile") -> dict[str, Any]:
        """
        Convert a type instance to json conform data
        """
        return {
            'public_id': instance.get_public_id(),
            'filename': instance.get_filename(),
            'size': instance.get_size(),
            'upload_date': instance.get_upload_date(),
            'metadata': instance.get_metadata()
        }
