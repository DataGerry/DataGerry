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
Implementation of MediaFile API Route utility methods

Holds the query-filter builders the routes share, the unique-name recursion, the delete recursion, and
the three steps the upload / update routes are otherwise made of - reading the request, resolving what
is already stored, and building the metadata to persist
"""
import json
from typing import Any
from logging import Logger, getLogger

from flask import abort, request
from werkzeug.wrappers import Request
from werkzeug.datastructures import FileStorage

from cmdb.manager import MediaFilesManager
from cmdb.manager.query_builder import Builder

from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    MediaFileKey,
    MediaFileMetadataKey,
    MediaFileRequestKey,
)
from cmdb.interface.rest_api.routes.routes_helper import (
    get_element_from_data_request,
    get_file_in_request,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters

from cmdb.errors.manager.media_files_manager import MediaFileManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def generate_metadata_filter(element: str, _request: Request | None = None, params: dict | None = None) -> dict:
    """
    Generates a MongoDB filter query based on provided metadata either from request or parameters

    Args:
        element (str): The metadata key in the request or parameters
        _request (Request | None): Flask request containing the metadata in query/form
        params (dict | None): Direct dictionary containing metadata

    Raises:
        HTTPException: 400 if metadata cannot be generated

    Returns:
        dict: A MongoDB filter dictionary ready for querying
    """
    filter_metadata = {}

    try:
        data = params

        if _request:
            if _request.args.get(element):
                data = json.loads(_request.args.get(element))
            if not data:
                data = get_element_from_data_request(element, _request)

        for key, value in data.items():
            if 'reference' == key and value:
                if isinstance(value, list):
                    filter_metadata.update({f"metadata.{key}": {'$in': value}})
                else:
                    filter_metadata.update({f"metadata.{key}": {'$in': [int(value)]}})
            else:
                filter_metadata.update({f"metadata.{key}": value})

        return filter_metadata
    except Exception as err:
        LOGGER.error("Metadata was not provided - Exception: %s", err)
        abort(400, "Metadata was not provided!")


def generate_collection_parameters(params: CollectionParameters) -> dict:
    """
    Builds a MongoDB aggregation filter for file collections based on search and metadata parameters

    Args:
        params (CollectionParameters): The collection parameters including optional filters

    Returns:
        dict: A MongoDB query filter based on search term or metadata
    """
    search = params.optional.get('searchTerm')
    param = json.loads(params.optional['metadata'])

    if search:
        # Builder's constructors are stateless, so they are called on the class - Builder itself is
        # abstract and cannot be instantiated
        _ = [
            Builder.regex_('filename', search)
            , Builder.regex_('metadata.reference_type', search)
            , Builder.regex_('metadata.mime_type', search)
        ]

        if search.isdigit():
            _.append({'public_id': int(search)})
            _.append({'metadata.reference': int(search)})
            _.append(Builder.in_('metadata.reference', [int(search)]))
            _.append({'metadata.parent': int(search)})

        return Builder.and_([{'metadata.folder': False}, Builder.or_(_)])

    return generate_metadata_filter('metadata', params=param)


def create_attachment_name(name: str, index: int, metadata: dict, media_files_manager: MediaFilesManager) -> str:
    """
    Recursively generates a unique attachment file name if a file with the same name already exists.
    Adds a prefix like 'copy_(index)_' to the filename.

    Args:
        name (str): Original file name
        index (int): Copy index counter
        metadata (dict): Metadata for querying existing files
        media_files_manager (MediaFilesManager): Media file manager to check for existing files

    Returns:
        str: A unique file name string
    """
    try:
        if media_files_manager.file_exists(metadata):
            index += 1
            name = name.replace(f'copy_({index-1})_', '')
            name = f'copy_({index})_{name}'
            metadata['filename'] = name

            return create_attachment_name(name, index, metadata, media_files_manager)

        return name
    except Exception as err:
        raise MediaFileManagerGetError(str(err)) from err


def recursive_delete_filter(
    public_id: int,
    media_files_manager: MediaFilesManager,
    _ids: list[int] | None = None,
) -> list[int]:
    """
    Recursively collects and returns the list of public IDs for files to be deleted,
    including their child files in a parent-child file structure

    Args:
        public_id (int): The public ID of the root file
        media_files_manager (MediaFilesManager): Media file manager to fetch and manage files
        _ids (list[int] | None): List of already collected IDs, used for recursion

    Returns:
        list[int]: A list of public IDs of the files to delete
    """
    if _ids is None:
        _ids = []

    # public_id is already known - only the children need to be queried (one query per node, not two)
    _ids.append(public_id)

    children = media_files_manager.get_many_media_files(metadata={'metadata.parent': public_id}).result

    for item in children:
        recursive_delete_filter(item['public_id'], media_files_manager, _ids)

    return _ids


def get_stored_file_or_abort(media_files_manager: MediaFilesManager, public_id: int) -> dict[str, Any]:
    """
    Loads a stored MediaFile by public_id, or answers 404

    The manager reports a missing file as None (GridFS raises NoFile, which it swallows), so every route
    that goes on to read the document needs this in front of it - without it the None reaches the next
    subscript and the request ends as a 500 about a file that simply is not there

    Args:
        media_files_manager (MediaFilesManager): db interface for MediaFiles
        public_id (int): public_id of the MediaFile

    Raises:
        HTTPException: 404 when no MediaFile carries the public_id

    Returns:
        dict[str, Any]: The stored file document
    """
    stored_file: dict[str, Any] | None = media_files_manager.get_file(
        metadata={MediaFileKey.PUBLIC_ID.value: public_id},
    )

    if not stored_file:
        abort(404, f"The File with ID: {public_id} was not found!")

    return stored_file


def get_reference_attachment_or_abort() -> dict[str, Any]:
    """
    Reads the update route's ``attachment`` query parameter

    The parameter says whether the write only re-points a reference, in which case the filename is left
    alone. It is required - the frontend always sends it - so a missing or malformed value is a client
    error rather than the TypeError / JSONDecodeError it used to raise on the way to a 500

    Raises:
        HTTPException: 400 when the parameter is absent or is not a JSON object

    Returns:
        dict[str, Any]: The parsed parameter, e.g. {"reference": false}
    """
    raw_value: str | None = request.args.get(MediaFileRequestKey.ATTACHMENT.value)

    if raw_value is None:
        abort(400, f"The '{MediaFileRequestKey.ATTACHMENT.value}' query parameter is required!")

    try:
        attachment: Any = json.loads(raw_value)
    except ValueError:
        abort(400, f"The '{MediaFileRequestKey.ATTACHMENT.value}' query parameter is not valid JSON!")

    if not isinstance(attachment, dict):
        abort(400, f"The '{MediaFileRequestKey.ATTACHMENT.value}' query parameter must be an object!")

    return attachment


def get_upload_from_request(_request: Request) -> tuple[FileStorage, dict[str, Any], dict[str, Any]]:
    """
    Reads the three parts of an upload request

    Args:
        _request (Request): The upload request, carrying the file and its metadata as form parts

    Raises:
        HTTPException: 400 when the file part or the metadata is missing / unusable

    Returns:
        tuple[FileStorage, dict[str, Any], dict[str, Any]]: The uploaded file, the filter identifying
            an already stored file of that name in that folder, and the metadata to persist
    """
    upload: FileStorage = get_file_in_request(MediaFileRequestKey.FILE.value)

    existing_filter: dict[str, Any] = generate_metadata_filter(MediaFileRequestKey.METADATA.value, _request)
    existing_filter.update({MediaFileKey.FILENAME.value: upload.filename})

    metadata: dict[str, Any] = get_element_from_data_request(MediaFileRequestKey.METADATA.value, _request)

    return upload, existing_filter, metadata


def build_upload_metadata(
        metadata: dict[str, Any],
        upload: FileStorage,
        author_id: int,
        replaced_file: dict[str, Any] | None) -> dict[str, Any]:
    """
    Completes the metadata an upload is stored with

    The author and the mime type are server-owned. When the upload replaces a file of the same name in
    the same folder, that file's reference and reference_type are carried over, because the replacement
    is the same library entry with new content and the references pointing at it must survive it. They
    are read defensively: a stored file written before the keys existed carries neither

    Args:
        metadata (dict[str, Any]): The metadata as it arrived with the request
        upload (FileStorage): The uploaded file, for its mime type
        author_id (int): public_id of the uploading CmdbUser
        replaced_file (dict[str, Any] | None): The stored file this upload replaces, if any

    Returns:
        dict[str, Any]: The metadata to persist
    """
    if replaced_file:
        previous_metadata: dict[str, Any] = replaced_file.get(MediaFileKey.METADATA.value) or {}

        metadata[MediaFileMetadataKey.REFERENCE.value] = previous_metadata.get(
            MediaFileMetadataKey.REFERENCE.value)
        metadata[MediaFileMetadataKey.REFERENCE_TYPE.value] = previous_metadata.get(
            MediaFileMetadataKey.REFERENCE_TYPE.value)

    metadata[MediaFileMetadataKey.AUTHOR_ID.value] = author_id
    metadata[MediaFileMetadataKey.MIME_TYPE.value] = upload.mimetype

    return metadata


def build_updated_file_data(
        stored_file: dict[str, Any],
        new_file_data: dict[str, Any],
        author_id: int) -> dict[str, Any]:
    """
    Merges an update payload onto the stored MediaFile document

    The public_id is taken from the stored document, so the payload can not rewrite the identity, and the
    author is stamped as the last modifier

    Args:
        stored_file (dict[str, Any]): The MediaFile as stored
        new_file_data (dict[str, Any]): The parsed request body
        author_id (int): public_id of the CmdbUser performing the update

    Raises:
        HTTPException: 400 when the payload does not carry a filename or metadata

    Returns:
        dict[str, Any]: The document to persist
    """
    for required_key in (MediaFileKey.FILENAME, MediaFileKey.METADATA):
        if required_key.value not in new_file_data:
            abort(400, f"The request body is missing '{required_key.value}'!")

    stored_file[MediaFileKey.FILENAME.value] = new_file_data[MediaFileKey.FILENAME.value]
    stored_file[MediaFileKey.METADATA.value] = new_file_data[MediaFileKey.METADATA.value]
    stored_file[MediaFileKey.METADATA.value][MediaFileMetadataKey.AUTHOR_ID.value] = author_id

    return stored_file
