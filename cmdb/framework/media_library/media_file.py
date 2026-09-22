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
Implementation of MediaFile
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from cmdb.framework.media_library.base_media_file import BaseMediaFile
from cmdb.framework.media_library.media_file_keys import (
    MediaFileKey,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
)
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.cmdb_object import NoPublicIDError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   MediaFile - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class MediaFile(BaseMediaFile):
    """
    A file of the media library, i.e. one GridFS file document

    Instances are built from a stored document (`MediaFile(**grid._file)`), which is why the constructor
    takes GridFS' own camelCase key names; `to_json` turns one back into the document the read routes
    answer with. The metadata sub-document is passed through untouched - `build_media_file_metadata` is
    what shapes it on the way in
    """

    COLLECTION = 'media.libary'
    REQUIRED_INIT_KEYS: list[str] = ['name']

    # A file's identity is (filename, metadata.parent): the library is a tree, so the same name in two
    # different folders is legal and only a clash INSIDE one folder is not - which is exactly what the
    # upload and update routes check before renaming to 'copy_(n)_<name>'. Until 2026-09-16 this
    # declared a unique index over 'name', a key no GridFS document carries, and nothing ever built it
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [
                (MediaFileKey.FILENAME.value, CmdbDAO.DAO_ASCENDING),
                (MEDIA_FILE_PARENT_PATH, CmdbDAO.DAO_ASCENDING),
            ],
            'name': MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
            'unique': True
        }
    ]

    def __init__(self,
                 filename: str,
                 chunkSize: int,
                 uploadDate: datetime,
                 metadata: dict[str, Any],
                 length: int,
                 **kwargs: Any) -> None:
        """
        Initialises a MediaFile from a stored GridFS file document

        Args:
            filename (str): Name of the file, unique per metadata.parent folder
            chunkSize (int): Size of the chunks GridFS split the content into, in bytes
            uploadDate (datetime): When GridFS stored the content - NOT a last-modified stamp
            metadata (dict[str, Any]): The file's metadata sub-document (see MediaFileMetadataKey)
            length (int): Size of the content in bytes
            **kwargs (Any): The remaining keys of the document, public_id among them
        """
        self.filename: str = filename
        self.chunk_size = chunkSize
        self.upload_date = uploadDate
        self.metadata = metadata
        self.size = length

        super().__init__(**kwargs)


    def get_public_id(self) -> int:
        """
        Get the public_id of this MediaFile

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
        Get the name of the file

        Returns:
            str: The filename, or an empty string when the document carries none
        """
        if self.filename is None:
            return ""

        return self.filename


    def get_chunk_size(self) -> int:
        """
        Get the size of each chunk in bytes

        GridFS divides the content into chunks of this size, except for the last one, which is only as
        large as it needs to be. The default is 255 kilobytes

        Returns:
            int: Size of a chunk in bytes
        """
        return self.chunk_size


    def get_upload_date(self) -> datetime:
        """
        Get the point in time GridFS stored the file's content

        A metadata-only edit leaves this alone, so it is not a last-modified stamp

        Returns:
            datetime: When the content was stored
        """
        return self.upload_date


    def get_metadata(self) -> dict[str, Any]:
        """
        Get the metadata sub-document of the file

        This is the sub-document as GridFS stores it, not a wrapper around it - its keys are the ones
        `MediaFileMetadataKey` names (see `build_media_file_metadata`, which writes them)

        Returns:
            dict[str, Any]: The file's metadata sub-document
        """
        return self.metadata


    def get_size(self) -> int:
        """
        Get the size of the file's content in bytes

        Returns:
            int: Size of the content in bytes
        """
        return self.size


    @classmethod
    def to_json(cls, instance: "MediaFile") -> dict[str, Any]:
        """
        Converts a MediaFile into the document the read routes answer with

        Args:
            instance (MediaFile): The MediaFile to convert

        Returns:
            dict[str, Any]: The file's public representation, metadata sub-document included
        """
        return {
            'public_id': instance.get_public_id(),
            'filename': instance.get_filename(),
            'size': instance.get_size(),
            'upload_date': instance.get_upload_date(),
            'metadata': instance.get_metadata()
        }
