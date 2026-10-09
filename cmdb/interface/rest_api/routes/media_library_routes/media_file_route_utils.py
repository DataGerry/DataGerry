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
from collections.abc import Iterator
from typing import Any
from logging import Logger, getLogger

from cerberus import Validator  # type: ignore
from flask import abort, request
from werkzeug.wrappers import Request
from werkzeug.datastructures import FileStorage
from gridfs.grid_file import GridOut

from cmdb.manager import MediaFilesManager
from cmdb.utils import Builder
from cmdb.framework.media_library import (
    MEDIA_FILE_METADATA_SCHEMA,
    MEDIA_FILE_UPDATE_SCHEMA,
    build_media_file_metadata,
    filename_problem,
)

from cmdb.interface.blueprints.schema_error_format import describe_schema_errors
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    BODY_NOT_AN_OBJECT_MSG,
    FOLDER_FLAG_IMMUTABLE_MSG,
    METADATA_NOT_AN_OBJECT_MSG,
    PARENT_CYCLE_MSG,
    PARENT_NOT_A_FOLDER_MSG,
    PARENT_NOT_FOUND_MSG,
    UNKNOWN_METADATA_KEYS_MSG,
    UPLOAD_FILENAME_MSG,
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

def metadata_field(key: MediaFileMetadataKey | str) -> str:
    """
    Builds the dotted path of a key inside a MediaFile's metadata sub-document

    Args:
        key (MediaFileMetadataKey | str): The metadata key, either declared or - when it comes from a
            request filter - a raw one

    Returns:
        str: The path to query, e.g. 'metadata.parent'
    """
    return f'{MediaFileKey.METADATA.value}.{key.value if isinstance(key, MediaFileMetadataKey) else key}'


def abort_if_unknown_metadata_keys(metadata: dict[str, Any]) -> None:
    """
    Refuses a metadata sub-document carrying a key the media library does not declare, naming every one

    Args:
        metadata (dict[str, Any]): The metadata as it arrived with the request

    Raises:
        HTTPException: 400 naming the undeclared keys
    """
    unknown_keys: list[str] = [str(key) for key in metadata if not MediaFileMetadataKey.is_valid(str(key))]

    if unknown_keys:
        abort(400, UNKNOWN_METADATA_KEYS_MSG.format(keys=', '.join(sorted(unknown_keys))))


def validate_upload_metadata(metadata: dict[str, Any]) -> None:
    """
    Refuses upload metadata that is not a usable metadata sub-document

    The metadata of an upload is client-supplied and is stored as the file's metadata sub-document, so
    only the keys MediaFileMetadataKey names may appear in it, each holding a value of its declared type
    (`MEDIA_FILE_METADATA_SCHEMA`). Anything else is refused here, before any content is streamed into
    GridFS, naming the key

    Args:
        metadata (dict[str, Any]): The metadata as it arrived with the request

    Raises:
        HTTPException: 400 when the metadata is not an object, carries an undeclared key, or a value of the
            wrong type
    """
    if not isinstance(metadata, dict):
        abort(400, METADATA_NOT_AN_OBJECT_MSG)

    abort_if_unknown_metadata_keys(metadata)

    validator = Validator(MEDIA_FILE_METADATA_SCHEMA)

    if not validator.validate(metadata):
        abort(400, describe_schema_errors(validator.errors))


def validate_update_body(body: Any) -> dict[str, Any]:
    """
    Refuses an update body that is not a usable MediaFile

    The body is the whole MediaFile: an integer `public_id`, a usable `filename` (`filename_problem`) and
    a metadata sub-document held to the same rules as an upload's. Further keys the file explorer sends
    along (`size`, `children`, ...) are tolerated and never stored

    Args:
        body (Any): The parsed request body

    Raises:
        HTTPException: 400 when the body is not an object, or does not satisfy `MEDIA_FILE_UPDATE_SCHEMA`

    Returns:
        dict[str, Any]: The body, now known to be usable
    """
    if not isinstance(body, dict):
        abort(400, BODY_NOT_AN_OBJECT_MSG)

    if isinstance(body.get(MediaFileKey.METADATA.value), dict):
        abort_if_unknown_metadata_keys(body[MediaFileKey.METADATA.value])

    validator = Validator(MEDIA_FILE_UPDATE_SCHEMA, allow_unknown=True)

    if not validator.validate(body):
        abort(400, describe_schema_errors(validator.errors))

    return body


def abort_if_filename_unusable(name: Any) -> None:
    """
    Refuses an uploaded file whose name breaks the naming rule (`filename_problem`)

    Args:
        name (Any): The name of the uploaded file part

    Raises:
        HTTPException: 400 naming the reason
    """
    problem: str | None = filename_problem(name)

    if problem:
        abort(400, UPLOAD_FILENAME_MSG.format(problem=problem))


def abort_unless_usable_parent(
        media_files_manager: MediaFilesManager,
        parent: Any,
        moved_id: int | None = None) -> None:
    """
    Refuses a parent that is no folder of the library, or - for a moved entry - lies inside that entry

    `None` is the library root. Any other parent has to be an existing folder. When an existing entry is
    moved, the walk up from the new parent may not meet the entry itself: a folder inside its own subtree
    drops out of the tree and its delete would never end. The walk stops at the root, or at an entry it
    has seen before (a loop already stored above the target, which it can not make worse)

    Args:
        media_files_manager (MediaFilesManager): db interface for MediaFiles
        parent (Any): The requested parent, already known to be an integer or None
        moved_id (int | None): public_id of the entry being moved; None for an upload

    Raises:
        HTTPException: 400 when the parent does not exist, is a file, or lies inside the moved entry
    """
    if parent is None:
        return

    folder: dict[str, Any] | None = media_files_manager.get_file(
        metadata={MediaFileKey.PUBLIC_ID.value: parent},
    )

    if not folder:
        abort(400, PARENT_NOT_FOUND_MSG.format(parent=parent))

    if not (folder.get(MediaFileKey.METADATA.value) or {}).get(MediaFileMetadataKey.FOLDER.value):
        abort(400, PARENT_NOT_A_FOLDER_MSG.format(parent=parent))

    if moved_id is None:
        return

    seen: set[int] = set()
    current: dict[str, Any] | None = folder

    while current is not None and current[MediaFileKey.PUBLIC_ID.value] not in seen:
        if current[MediaFileKey.PUBLIC_ID.value] == moved_id:
            abort(400, PARENT_CYCLE_MSG)

        seen.add(current[MediaFileKey.PUBLIC_ID.value])
        above: Any = (current.get(MediaFileKey.METADATA.value) or {}).get(MediaFileMetadataKey.PARENT.value)
        current = None if above is None else media_files_manager.get_file(
            metadata={MediaFileKey.PUBLIC_ID.value: above},
        )


def unique_name_filter(data: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the filter asking whether ANOTHER entry of the folder already carries the entry's name

    The entry itself is excluded: an update keeping its name (a move into the folder it already sits in,
    a metadata edit) must not find itself and be renamed to `copy_(1)_<name>`

    Args:
        data (dict[str, Any]): The document about to be stored

    Returns:
        dict[str, Any]: The filter `create_attachment_name` checks
    """
    return {
        MediaFileKey.FILENAME.value: data[MediaFileKey.FILENAME.value],
        metadata_field(MediaFileMetadataKey.PARENT): data[MediaFileKey.METADATA.value].get(
            MediaFileMetadataKey.PARENT.value),
        MediaFileKey.PUBLIC_ID.value: {'$ne': data[MediaFileKey.PUBLIC_ID.value]},
    }


def generate_metadata_filter(
    element: str,
    _request: Request | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generates a MongoDB filter query based on provided metadata either from request or parameters

    Each metadata key becomes a ``metadata.<key>`` condition; a ``reference`` matches any of the given
    ids. **An empty metadata object means different things on the two paths:** read from a request
    (the single read, the download, the upload), ``{}`` counts as "none given" - it falls back to the
    form part of the same name and, when that is absent too, answers 400. Passed in as ``params`` (the
    list route), ``{}`` is simply no condition and matches every file. Every frontend caller sends at
    least ``folder`` or ``parent``, so only an API client meets either case

    Args:
        element (str): The metadata key in the request or parameters
        _request (Request | None): Flask request containing the metadata in query/form
        params (dict[str, Any] | None): Direct dictionary containing metadata

    Raises:
        HTTPException: 400 if metadata cannot be generated

    Returns:
        dict[str, Any]: A MongoDB filter dictionary ready for querying
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
            if MediaFileMetadataKey.REFERENCE.value == key and value:
                if isinstance(value, list):
                    filter_metadata.update({metadata_field(key): {'$in': value}})
                else:
                    filter_metadata.update({metadata_field(key): {'$in': [int(value)]}})
            else:
                filter_metadata.update({metadata_field(key): value})

        return filter_metadata
    except Exception as err:
        LOGGER.error("Metadata was not provided - Exception: %s", err)
        abort(400, "Metadata was not provided!")


def generate_collection_parameters(params: CollectionParameters) -> dict[str, Any]:
    """
    Builds a MongoDB aggregation filter for file collections based on search and metadata parameters

    Args:
        params (CollectionParameters): The collection parameters including optional filters

    Returns:
        dict[str, Any]: A MongoDB query filter based on search term or metadata
    """
    search = params.optional.get(MediaFileRequestKey.SEARCH_TERM.value)
    param = json.loads(params.optional[MediaFileRequestKey.METADATA.value])

    if search:
        # Builder's constructors are stateless, so they are called on the class - Builder itself is
        # abstract and cannot be instantiated
        _ = [
            Builder.regex_(MediaFileKey.FILENAME.value, search)
            , Builder.regex_(metadata_field(MediaFileMetadataKey.REFERENCE_TYPE), search)
            , Builder.regex_(metadata_field(MediaFileMetadataKey.MIME_TYPE), search)
        ]

        if search.isdigit():
            _.append({MediaFileKey.PUBLIC_ID.value: int(search)})
            _.append({metadata_field(MediaFileMetadataKey.REFERENCE): int(search)})
            _.append(Builder.in_(metadata_field(MediaFileMetadataKey.REFERENCE), [int(search)]))
            _.append({metadata_field(MediaFileMetadataKey.PARENT): int(search)})

        return Builder.and_([{metadata_field(MediaFileMetadataKey.FOLDER): False}, Builder.or_(_)])

    return generate_metadata_filter(MediaFileRequestKey.METADATA.value, params=param)


def create_attachment_name(
    name: str,
    index: int,
    metadata: dict[str, Any],
    media_files_manager: MediaFilesManager,
) -> str:
    """
    Recursively generates a unique attachment file name if a file with the same name already exists.
    Adds a prefix like 'copy_(index)_' to the filename.

    Args:
        name (str): Original file name
        index (int): Copy index counter
        metadata (dict[str, Any]): Metadata for querying existing files
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
        raise MediaFileManagerGetError(err) from err


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

    children = media_files_manager.get_many_media_files(
        metadata={metadata_field(MediaFileMetadataKey.PARENT): public_id},
    ).results

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
    error rather than a TypeError / JSONDecodeError on the way to a 500

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
        HTTPException: 400 when the file part or the metadata is missing / unusable, when the file's name
            breaks the naming rule, or when the metadata carries an undeclared key or a value of the wrong
            type

    Returns:
        tuple[FileStorage, dict[str, Any], dict[str, Any]]: The uploaded file, the filter identifying
            an already stored file of that name in that folder, and the metadata to persist
    """
    upload: FileStorage = get_file_in_request(MediaFileRequestKey.FILE.value)
    abort_if_filename_unusable(upload.filename)

    # Checked before the filter is built from it, so a value of the wrong type is refused naming the key
    metadata: dict[str, Any] = get_element_from_data_request(MediaFileRequestKey.METADATA.value, _request)
    validate_upload_metadata(metadata)

    existing_filter: dict[str, Any] = generate_metadata_filter(MediaFileRequestKey.METADATA.value, _request)
    existing_filter.update({MediaFileKey.FILENAME.value: upload.filename})

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
    Merges a validated update payload onto the stored MediaFile document

    The public_id is taken from the stored document, so the payload can not rewrite the identity. The
    metadata is the whole sub-document the payload carries (an update sends the full object), built like an
    upload's (`build_media_file_metadata`), so both write paths store the same seven keys. Two of them are
    server-owned: the author is stamped as the last modifier, and the mime type stays the stored one - an
    update changes no content. Whether the entry is a folder can not change

    Args:
        stored_file (dict[str, Any]): The MediaFile as stored
        new_file_data (dict[str, Any]): The request body, already held to `validate_update_body`
        author_id (int): public_id of the CmdbUser performing the update

    Raises:
        HTTPException: 400 when the payload would turn a file into a folder or a folder into a file

    Returns:
        dict[str, Any]: The document to persist
    """
    stored_metadata: dict[str, Any] = stored_file.get(MediaFileKey.METADATA.value) or {}
    metadata: dict[str, Any] = build_media_file_metadata({
        **new_file_data[MediaFileKey.METADATA.value],
        MediaFileMetadataKey.AUTHOR_ID.value: author_id,
        MediaFileMetadataKey.MIME_TYPE.value: stored_metadata.get(MediaFileMetadataKey.MIME_TYPE.value),
    })

    was_folder: bool = bool(stored_metadata.get(MediaFileMetadataKey.FOLDER.value))

    if bool(metadata[MediaFileMetadataKey.FOLDER.value]) != was_folder:
        abort(400, FOLDER_FLAG_IMMUTABLE_MSG)

    stored_file[MediaFileKey.FILENAME.value] = new_file_data[MediaFileKey.FILENAME.value]
    stored_file[MediaFileKey.METADATA.value] = metadata

    return stored_file


def stream_grid_file(grid_out: GridOut) -> Iterator[bytes]:
    """
    Yields a stored media file's content one GridFS chunk at a time

    What the download route answers with, so a file of any size costs one chunk of memory rather than
    its whole size. Closes the file once the last chunk has been sent, or when the client goes away
    and the generator is closed early

    Args:
        grid_out (GridOut): The open file (`MediaFilesManager.open_file`)

    Yields:
        bytes: The next chunk of the content; nothing for an empty file
    """
    try:
        chunk: bytes = grid_out.readchunk()

        while chunk:
            yield chunk
            chunk = grid_out.readchunk()
    finally:
        grid_out.close()
