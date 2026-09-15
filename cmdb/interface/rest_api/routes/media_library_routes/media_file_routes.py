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
Implementation of all API routes for the MediaFiles

The media library is a tree of files and folders kept in GridFS: a folder is a MediaFile whose metadata
says ``folder: true``, and every entry names its ``metadata.parent``. The pair (filename, parent) is what
has to stay unique, which is why the upload route replaces a file of the same name in the same folder and
the update route renames a clashing one to ``copy_(n)_<name>``

Six routes: list, upload, update, read one, download the bytes, delete a subtree. They borrow the
CmdbObject rights (see ``MediaFileRight``) - the library has no right family of its own - and a missing
file is a 404 on every one of them
"""
import json
from logging import Logger, getLogger
from bson import json_util
from flask import abort, request, Response
from werkzeug.wrappers.response import Response as Resp
from werkzeug.exceptions import HTTPException
from werkzeug.http import quote_header_value

from cmdb.interface.rest_api.responses.gridfs_response import GridFsResponse
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import MediaFilesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    MediaFileKey,
    MediaFileMetadataKey,
    MediaFileRequestKey,
    MediaFileRight,
)
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    build_updated_file_data,
    build_upload_metadata,
    create_attachment_name,
    generate_collection_parameters,
    generate_metadata_filter,
    get_reference_attachment_or_abort,
    get_stored_file_or_abort,
    get_upload_from_request,
    recursive_delete_filter,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    DefaultResponse,
)

from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
    MediaFileManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

media_file_blueprint = APIBlueprint('media_file_blueprint', __name__, url_prefix='/media_file')

# -------------------------------------------------------------------------------------------------------------------- #

@media_file_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.VIEW.value)
@media_file_blueprint.parse_collection_parameters()
def get_file_list(params: CollectionParameters, request_user: CmdbUser) -> Resp:
    """
    HTTP `GET`/`HEAD` route to list the MediaFiles of the library

    Requires the ``base.framework.object.view`` right. The optional ``metadata`` parameter narrows the
    listing to one folder; ``searchTerm`` searches filenames, reference types and mime types instead

    Note that the paging parameters are NOT applied to the GridFS query yet, so every matching file is
    loaded and ``total`` is the length of that list - a filed decision, not an oversight

    Args:
        params (CollectionParameters): Filter, sort and paging parameters
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the files could not be retrieved;
            500 on an unexpected error

    Returns:
        GetMultiResponse: The MediaFiles matching the parameters
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES, request_user)

        metadata = generate_collection_parameters(params=params)
        response_query = {'limit': params.limit, 'skip': params.skip, 'sort': [(params.sort, params.order)]}
        output: GridFsResponse = media_files_manager.get_many_media_files(metadata, **response_query)

        api_response = GetMultiResponse(output.result, total=output.total, params=params, url=request.url)

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except MediaFileManagerGetError as err:
        LOGGER.error("[get_file_list] MediaFileManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the FilesList from the database!")
    except Exception as err:
        LOGGER.error("[get_file_list] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the FilesList!")


@media_file_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.EDIT.value)
def add_new_file(request_user: CmdbUser) -> Resp:
    """
    HTTP `POST` route to upload a MediaFile into the library

    Requires the ``base.framework.object.edit`` right. The file arrives as the ``file`` form part and its
    metadata as the ``metadata`` one; ``author_id`` and ``mime_type`` are server-owned

    Uploading over an entry of the same name in the same folder REPLACES it: the new content is written
    first and the old entry is removed only afterwards, so a refused or failing upload leaves the
    previous file intact. The replaced entry's reference and reference_type are carried over, because
    what points at the library entry must survive its content being replaced

    Args:
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the request carries no usable file or
            metadata, or the insert fails; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The stored MediaFile and its public_id
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES,
                                                                            request_user)

        upload, existing_filter, metadata = get_upload_from_request(request)

        replaced_file: dict | None = None

        if media_files_manager.file_exists(existing_filter):
            replaced_file = media_files_manager.get_file(existing_filter)

        result = media_files_manager.insert_file(
            data=upload,
            metadata=build_upload_metadata(metadata, upload, request_user.public_id, replaced_file),
        )

        # Only now: the replacement exists, so removing the previous entry can no longer lose both
        if replaced_file:
            media_files_manager.delete_file(replaced_file[MediaFileKey.PUBLIC_ID.value])

        return InsertSingleResponse(result, result[MediaFileKey.PUBLIC_ID.value]).make_response()
    except HTTPException as http_err:
        raise http_err
    except MediaFileManagerGetError as err:
        LOGGER.error("[add_new_file] MediaFileManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the File which would be replaced from the database!")
    except MediaFileManagerInsertError as err:
        LOGGER.error("[add_new_file] MediaFileManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the File in the database!")
    except Exception as err:
        LOGGER.error("[add_new_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while adding the file!")


@media_file_blueprint.route('/', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.EDIT.value)
def update_file(request_user: CmdbUser) -> Resp:
    """
    HTTP `PUT` route to update a MediaFile's name, folder or metadata

    Requires the ``base.framework.object.edit`` right. The body is the whole MediaFile document; the
    identity comes from the stored file, so a payload public_id can not rewrite it, and the author is
    stamped as the last modifier

    The ``attachment`` query parameter is required. With ``{"reference": true}`` the write only re-points
    a reference and the filename is taken as given; otherwise the name has to stay unique inside its
    folder, so a clashing one is renamed to ``copy_(n)_<name>``

    Args:
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the body or the ``attachment``
            parameter is unusable, or the update fails; 404 when no MediaFile carries the public_id;
            500 on an unexpected error

    Returns:
        DefaultResponse: The updated MediaFile
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES,
                                                                            request_user)

        new_file_data = json.loads(json.dumps(request.json), object_hook=json_util.object_hook)
        reference_attachment = get_reference_attachment_or_abort()

        if MediaFileKey.PUBLIC_ID.value not in new_file_data:
            abort(400, f"The request body is missing '{MediaFileKey.PUBLIC_ID.value}'!")

        stored_file = get_stored_file_or_abort(media_files_manager, new_file_data[MediaFileKey.PUBLIC_ID.value])
        data = build_updated_file_data(stored_file, new_file_data, request_user.get_public_id())

        # A file keeps its own name only where nothing else in the folder claims it - unless this write
        # merely re-points a reference, which leaves the name alone
        if not reference_attachment.get(MediaFileRequestKey.REFERENCE.value):
            checker = {
                MediaFileKey.FILENAME.value: data[MediaFileKey.FILENAME.value],
                f'{MediaFileKey.METADATA.value}.{MediaFileMetadataKey.PARENT.value}':
                    data[MediaFileKey.METADATA.value].get(MediaFileMetadataKey.PARENT.value),
            }
            data[MediaFileKey.FILENAME.value] = create_attachment_name(
                data[MediaFileKey.FILENAME.value], 0, checker, media_files_manager,
            )

        media_files_manager.update_file(data)

        return DefaultResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except MediaFileManagerUpdateError as err:
        LOGGER.error("[update_file] MediaFileManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the File in the database!")
    except Exception as err:
        LOGGER.error("[update_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating the file!")


@media_file_blueprint.route('/<string:filename>/', methods=['GET'])
@media_file_blueprint.route('/<string:filename>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.VIEW.value)
def get_file(filename: str, request_user: CmdbUser) -> Resp:
    """
    HTTP `GET` route to retrieve a single MediaFile by name

    Requires the ``base.framework.object.view`` right. The optional ``metadata`` query parameter narrows
    the lookup to one folder, which is what makes the name unambiguous - the same name may exist in
    several folders

    Args:
        filename (str): Name of the MediaFile, unique within its folder
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no MediaFile of that name exists in
            the addressed folder; 500 on an unexpected error

    Returns:
        DefaultResponse: The requested MediaFile
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES,
                                                                            request_user)

        filter_metadata = generate_metadata_filter(MediaFileRequestKey.METADATA.value, request)
        filter_metadata.update({MediaFileKey.FILENAME.value: filename})

        result = media_files_manager.get_file(metadata=filter_metadata)

        if not result:
            abort(404, f"The File with the name: {filename} was not found!")

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the file: {filename}!")


@media_file_blueprint.route('/download/<path:filename>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.VIEW.value)
def download_file(filename: str, request_user: CmdbUser) -> Resp:
    """
    HTTP `GET` route to download a MediaFile's content

    Requires the ``base.framework.object.view`` right. The optional ``metadata`` query parameter narrows
    the lookup to one folder, as it does for the metadata read

    The filename is quoted in the Content-Disposition header rather than interpolated bare, so a name
    carrying a quote or a semicolon can not break the header the browser parses. Note the whole file is
    read into memory before it is sent - a filed decision, not an oversight

    Args:
        filename (str): Name of the MediaFile to download
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no MediaFile of that name exists in
            the addressed folder; 500 on an unexpected error

    Returns:
        Response: The file content as an attachment
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES,
                                                                            request_user)

        filter_metadata = generate_metadata_filter(MediaFileRequestKey.METADATA.value, request)
        filter_metadata.update({MediaFileKey.FILENAME.value: filename})
        result = media_files_manager.get_file(metadata=filter_metadata, blob=True)

        if result is None:
            # Without this the empty body went out as a 200 - the caller saved a 0-byte file
            abort(404, f"The File with the name: {filename} was not found!")

        return Response(
            result,
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename={quote_header_value(filename)}',
            },
        )
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[download_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while downloading the file: {filename}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@media_file_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@media_file_blueprint.protect(auth=True, right=MediaFileRight.EDIT.value)
def delete_file(public_id: int, request_user: CmdbUser) -> Resp:
    """
    HTTP `DELETE` route to delete a MediaFile or a whole folder

    Requires the ``base.framework.object.edit`` right. Deleting a folder deletes what it holds: the
    subtree below the addressed entry is collected first and then removed, the addressed entry included

    Args:
        public_id (int): public_id of the MediaFile to delete
        request_user (CmdbUser): The authenticated user issuing the request

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no MediaFile carries the public_id;
            400 when the deletion fails; 500 on an unexpected error

    Returns:
        DefaultResponse: The MediaFile which was deleted
    """
    try:
        media_files_manager: MediaFilesManager = ManagerProvider.get_manager(ManagerType.MEDIA_FILES,
                                                                            request_user)

        file_to_delete = get_stored_file_or_abort(media_files_manager, public_id)

        for _id in recursive_delete_filter(public_id, media_files_manager):
            media_files_manager.delete_file(_id)

        return DefaultResponse(file_to_delete).make_response()
    except HTTPException as http_err:
        raise http_err
    except MediaFileManagerDeleteError as err:
        LOGGER.error("[delete_file] MediaFileManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the File with ID: {public_id} in the database!")
    except Exception as err:
        LOGGER.error("[delete_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the file with ID: {public_id}!")
