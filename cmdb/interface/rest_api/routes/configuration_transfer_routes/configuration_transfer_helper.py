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
Helpers of the configuration transfer routes

``configuration_lock`` is what keeps the configuration's writers apart: the import (an uploaded file or a best-practice
model) and the reset each run inside it, so only one of them changes a database's configuration at a time. It is one
settings-section lock (``cmdb.manager.system_manager.settings_section_lock``); the rack placements hold another
"""
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from flask import abort, Request, Response
from werkzeug.datastructures import FileStorage

from cmdb.database.json_codec import default, object_hook
from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.configuration_transfer import TRANSFER_COMPONENTS, TransferComponent
from cmdb.framework.exporter.export_filename_helper import (
    build_configuration_export_filename,
    clean_export_filename,
)
from cmdb.utils import CONTENT_DISPOSITION_HEADER, MAX_JSON_UPLOAD_DEPTH, attachment_disposition, load_json_upload
from cmdb.interface.blueprints.api_blueprint_constants import ERRORS_SEPARATOR
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
from cmdb.manager.system_manager.settings_section_lock import (
    SectionLockSpec,
    acquire_section_lock,
    release_section_lock,
)
from cmdb.errors.utils import JsonUploadDecodeError, JsonUploadTooDeepError
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_LOCK_SECTION,
    CONFIGURATION_LOCK_TTL_SECONDS,
    CONFIGURATION_LOCKED_MESSAGE,
    IMPORT_FILE_NOT_JSON_MESSAGE,
    IMPORT_FILE_TOO_DEEP_MESSAGE,
    IMPORT_PROBLEMS_MESSAGE,
    IMPORT_UPLOAD_FIELD,
    NO_IMPORT_FILE_MESSAGE,
    CONFIGURATION_EXPORT_FILE_EXTENSION,
    CONFIGURATION_EXPORT_JSON_INDENT,
    CONFIGURATION_EXPORT_MIMETYPE,
)
# -------------------------------------------------------------------------------------------------------------------- #

#: The configuration lock: one import, apply or reset per database at a time, refused at once while held
CONFIGURATION_LOCK_SPEC: SectionLockSpec = SectionLockSpec(
    section=CONFIGURATION_LOCK_SECTION, label='configuration lock', ttl_seconds=CONFIGURATION_LOCK_TTL_SECONDS,
)


@contextmanager
def configuration_lock(request_user: CmdbUser) -> Iterator[None]:
    """
    Holds the configuration lock of the requesting tenant's database for the duration of the block

    A settings-section lock (``settings_section_lock``): taken with one atomic insert of the lock's settings section;
    a lock older than ``CONFIGURATION_LOCK_TTL_SECONDS`` is taken over (its holder can no longer be running) and the
    takeover is logged. While another request holds it, the request is refused with 400 at once.

    The release runs in a ``finally`` - after a success, a refusal or a failed write alike - and deletes the lock only
    while it is still this request's (its holder token). A release that fails is logged, not raised: the outcome of
    the block stands, and the lock expires on its own

    Args:
        request_user (CmdbUser): The requesting user, whose tenant database is locked

    Raises:
        HTTPException: 400 when another request holds the lock
        DocumentInsertError / DocumentUpdateError: When the lock could not be taken (the block does not run)

    Yields:
        None: Runs the block while the lock is held
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    try:
        token: str = acquire_section_lock(settings_manager, CONFIGURATION_LOCK_SPEC, request_user.public_id)
    except SettingsSectionLockHeldError:
        abort(400, CONFIGURATION_LOCKED_MESSAGE)

    try:
        yield
    finally:
        release_section_lock(settings_manager, CONFIGURATION_LOCK_SPEC, token)


def build_transfer_components(request_user: CmdbUser) -> list[TransferComponent]:
    """
    Builds every registered component on the requesting tenant's manager of its collection, in import order

    Args:
        request_user (CmdbUser): The requesting user, whose tenant the managers are bound to

    Returns:
        list[TransferComponent]: The components
    """
    return [component(ManagerProvider.get_manager(component.MANAGER_TYPE, request_user))
            for component in TRANSFER_COMPONENTS]


def build_configuration_export_response(transfer_file: dict[str, Any], db_version: int,
                                        requested_filename: str | None) -> Response:
    """
    Serialises a transfer file into a downloadable JSON attachment

    BSON values plain json cannot encode (a datetime, an ObjectId) go through the shared `default` hook - a datetime
    becomes `{'$date': <epoch millis>}`, the shape every other export and response uses

    Args:
        transfer_file (dict[str, Any]): The transfer file
        db_version (int): The database version the file is stamped with, which names the download when the user
                          chose no usable name
        requested_filename (str | None): The download name the user chose, cleaned by ``clean_export_filename``;
                                         None for the generated one

    Returns:
        Response: The file as a `.json` attachment
    """
    body: str = json.dumps(transfer_file, default=default, indent=CONFIGURATION_EXPORT_JSON_INDENT)
    filename: str = clean_export_filename(
        requested_filename, CONFIGURATION_EXPORT_FILE_EXTENSION,
        build_configuration_export_filename(db_version, CONFIGURATION_EXPORT_FILE_EXTENSION),
    )

    return Response(body, mimetype=CONFIGURATION_EXPORT_MIMETYPE,
                    headers={CONTENT_DISPOSITION_HEADER: attachment_disposition(filename)})


def read_uploaded_transfer_file(source_request: Request) -> Any:
    """
    Reads and decodes the uploaded transfer file

    Decoded with the codec's object hook, so the `{'$date': millis}` values the export wrote come back as datetimes,
    through `load_json_upload`: a value the hook cannot read (a malformed `$oid`, `$uuid`, `$regex`) is refused like
    text that is not JSON, and a file nested deeper than `MAX_JSON_UPLOAD_DEPTH` is refused before any later step
    walks it recursively (the checks deep-copy every type entry). Only the decoding is judged here - what the JSON
    holds is the import checks' business

    Args:
        source_request (Request): The incoming multipart request

    Raises:
        HTTPException: 400 without a file, when it is not UTF-8 JSON or holds an unreadable extended-JSON value, or
                       when it is nested deeper than `MAX_JSON_UPLOAD_DEPTH`

    Returns:
        Any: The decoded file
    """
    upload: FileStorage | None = source_request.files.get(IMPORT_UPLOAD_FIELD)

    if upload is None:
        abort(400, NO_IMPORT_FILE_MESSAGE)

    try:
        return load_json_upload(upload.read(), object_hook=object_hook)
    except JsonUploadDecodeError as err:
        abort(400, IMPORT_FILE_NOT_JSON_MESSAGE.format(detail=err))
    except JsonUploadTooDeepError:
        abort(400, IMPORT_FILE_TOO_DEEP_MESSAGE.format(limit=MAX_JSON_UPLOAD_DEPTH))


def abort_with_problems(problems: list[str]) -> None:
    """
    Refuses an import whose file has problems, naming every one of them

    Args:
        problems (list[str]): The problems - nothing happens when there are none

    Raises:
        HTTPException: 400 listing the problems
    """
    if problems:
        abort(400, IMPORT_PROBLEMS_MESSAGE.format(problems=ERRORS_SEPARATOR.join(problems)))
