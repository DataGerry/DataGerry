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
"""
import json
from logging import Logger, getLogger

from flask import request, abort
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Request

from cmdb.manager import MediaFilesManager
from cmdb.manager.query_builder import Builder

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters

from cmdb.errors.manager.media_files_manager import MediaFileManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_file_in_request(file_name: str) -> FileStorage:
    """
    Retrieves a file from the Flask request based on the provided file name

    Args:
        file_name (str): The name of the file to retrieve from the request

    Raises:
        HTTPException: 400 if the file is not found in the request

    Returns:
        FileStorage: The file object retrieved from the request.
    """
    # request.files.get returns None (does not raise) for a missing file, so guard explicitly
    uploaded_file = request.files.get(file_name)

    if uploaded_file is None:
        LOGGER.error("[get_file_in_request] File with name: %s was not provided!", file_name)
        abort(400, f"File with name: {file_name} was not provided!")

    return uploaded_file


def get_element_from_data_request(element: str, _request: Request) -> dict | None:
    """
    Retrieves and parses a specific element (field) from a form-data request into a dictionary

    Args:
        element (str): The field name to extract from the request form data
        _request (Request): The Flask Request object

    Returns:
        dict | None: Parsed dictionary if successful; otherwise, None
    """
    try:
        metadata = json.loads(_request.form.to_dict()[element])
        return metadata
    except Exception as err:
        LOGGER.error("[get_element_from_data_request] Exception:'%s'. Type: %s", err, type(err), exc_info=True)
        return None


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
    builder = Builder()
    search = params.optional.get('searchTerm')
    param = json.loads(params.optional['metadata'])

    if search:
        _ = [
            builder.regex_('filename', search)
            , builder.regex_('metadata.reference_type', search)
            , builder.regex_('metadata.mime_type', search)
        ]

        if search.isdigit():
            _.append({'public_id': int(search)})
            _.append({'metadata.reference': int(search)})
            _.append(builder.in_('metadata.reference', [int(search)]))
            _.append({'metadata.parent': int(search)})

        return builder.and_([{'metadata.folder': False}, builder.or_(_)])

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
