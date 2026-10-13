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
"""
import json
from functools import wraps
from json import JSONDecodeError
from typing import Any, Callable

from flask import abort, Request, Response
from werkzeug.datastructures import FileStorage

from cmdb.database.json_codec import default, object_hook
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.user_model import CmdbUser
from cmdb.framework.configuration_transfer import TRANSFER_COMPONENTS, TransferComponent
from cmdb.framework.exporter.export_filename_helper import build_configuration_export_filename
from cmdb.utils import CONTENT_DISPOSITION_HEADER, attachment_disposition
from cmdb.interface.blueprints.api_blueprint_constants import ERRORS_SEPARATOR, REQUEST_USER_KWARG
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    ADMIN_ONLY_MESSAGE,
    IMPORT_FILE_NOT_JSON_MESSAGE,
    IMPORT_PROBLEMS_MESSAGE,
    IMPORT_UPLOAD_FIELD,
    NO_IMPORT_FILE_MESSAGE,
    CONFIGURATION_EXPORT_FILE_EXTENSION,
    CONFIGURATION_EXPORT_JSON_INDENT,
    CONFIGURATION_EXPORT_MIMETYPE,
)
# -------------------------------------------------------------------------------------------------------------------- #

def is_administrator(user: CmdbUser | None) -> bool:
    """
    Reports whether a user is THE administrator account - public_id 1, not any member of the admin group

    Args:
        user (CmdbUser | None): The requesting user

    Returns:
        bool: True for the administrator account
    """
    return user is not None and user.public_id == CmdbUser.ADMIN_PUBLIC_ID


def administrator_only(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator refusing every caller but the administrator account

    Sits below `insert_request_user` (it checks the injected user) and above the body validation, so a caller who
    may not use the route is refused before its input is read

    Args:
        func (Callable[..., Any]): The route

    Returns:
        Callable[..., Any]: The route behind the check

    Raises:
        HTTPException: 403 for any other user
    """
    @wraps(func)
    def _decorate(*args: Any, **kwargs: Any) -> Any:
        if not is_administrator(kwargs.get(REQUEST_USER_KWARG)):
            abort(403, ADMIN_ONLY_MESSAGE)

        return func(*args, **kwargs)

    return _decorate


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


def build_configuration_export_response(transfer_file: dict[str, Any], db_version: int) -> Response:
    """
    Serialises a transfer file into a downloadable JSON attachment

    BSON values plain json cannot encode (a datetime, an ObjectId) go through the shared `default` hook - a datetime
    becomes `{'$date': <epoch millis>}`, the shape every other export and response uses

    Args:
        transfer_file (dict[str, Any]): The transfer file
        db_version (int): The database version the file is stamped with, which names the download

    Returns:
        Response: The file as a `.json` attachment
    """
    body: str = json.dumps(transfer_file, default=default, indent=CONFIGURATION_EXPORT_JSON_INDENT)
    filename: str = build_configuration_export_filename(db_version, CONFIGURATION_EXPORT_FILE_EXTENSION)

    return Response(body, mimetype=CONFIGURATION_EXPORT_MIMETYPE,
                    headers={CONTENT_DISPOSITION_HEADER: attachment_disposition(filename)})


def read_uploaded_transfer_file(source_request: Request) -> Any:
    """
    Reads and decodes the uploaded transfer file

    Decoded with the codec's object hook, so the `{'$date': millis}` values the export wrote come back as datetimes.
    Only the decoding is judged here - what the JSON holds is the import checks' business

    Args:
        source_request (Request): The incoming multipart request

    Raises:
        HTTPException: 400 without a file, or when it is not UTF-8 JSON

    Returns:
        Any: The decoded file
    """
    upload: FileStorage | None = source_request.files.get(IMPORT_UPLOAD_FIELD)

    if upload is None:
        abort(400, NO_IMPORT_FILE_MESSAGE)

    try:
        return json.loads(upload.read().decode('utf-8'), object_hook=object_hook)
    except (UnicodeDecodeError, JSONDecodeError) as err:
        abort(400, IMPORT_FILE_NOT_JSON_MESSAGE.format(detail=err))


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
