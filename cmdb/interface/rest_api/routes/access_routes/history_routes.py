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
The ``/access/history`` routes: the access change history - read, export, and how long it is kept

The list and one entry ask ``base.access.view`` (ADMIN); the export and the retention ``base.access.history.export``
(ADMIN, the retention's change SUPER_ADMIN). Nothing changes an entry: no route writes one but the retention change's
own
"""
from datetime import datetime, timezone
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.utils import CONTENT_DISPOSITION_HEADER, attachment_disposition
from cmdb.manager import AccessHistoryManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessHistoryKey, CmdbAccessHistory, HistorySettingsKey
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse, UpdateSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    HISTORY_SEARCHABLE_FIELDS,
    HISTORY_SETTINGS_SCHEMA,
    AccessRightName,
)
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import list_response, load_or_404
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import take_comment
from cmdb.interface.rest_api.routes.access_routes.access_history_reads import (
    HistoryExportFormat,
    NEWEST_FIRST,
    HistoryQuery,
    export_body,
    export_entries,
    history_condition,
    retention_days,
    set_retention,
)
# -------------------------------------------------------------------------------------------------------------------- #

access_history_blueprint = APIBlueprint('access_history', __name__)

# What the 404 calls an entry, and what an export file is called
LABEL: str = 'Access history entry'
EXPORT_FILE_NAME: str = 'access-history-{stamp}.{extension}'
EXPORT_STAMP_FORMAT: str = '%Y%m%d%H%M%S'
UNKNOWN_FORMAT_MESSAGE: str = "An export is 'json' or 'csv'!"
# The query parameter naming the client's sort - without it the newest entries come first
SORT_PARAMETER: str = 'sort'


def _manager(request_user: CmdbUser) -> AccessHistoryManager:
    """
    The history of the caller's database

    Args:
        request_user (CmdbUser): The caller

    Returns:
        AccessHistoryManager: The manager
    """
    return ManagerProvider.get_manager(ManagerType.ACCESS_HISTORY, request_user)


@access_history_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@access_history_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@access_history_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the access history")
def get_access_history(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one page of the access history - newest first unless ``?sort=`` says otherwise;
    ``?group_id=``, ``?kind=``, ``?document_id=``, ``?filter=``, ``?search=`` and paging

    Args:
        params (CollectionParameters): The collection parameters
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a group id that is no id or an unknown kind

    Returns:
        GetMultiResponse: The page and its total
    """
    if SORT_PARAMETER not in request.args:
        params.sort, params.order = AccessHistoryKey.TIME.value, NEWEST_FIRST

    return list_response(_manager(request_user), CmdbAccessHistory, params, HISTORY_SEARCHABLE_FIELDS,
                         history_condition() or None)


@access_history_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@access_history_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the access history entry with ID: {public_id}")
def get_access_history_entry(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one entry of the access history

    Args:
        public_id (int): The entry's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: The entry as stored
    """
    return GetSingleResponse(load_or_404(_manager(request_user), public_id, LABEL),
                             body=request_wants_body()).make_response()


@access_history_blueprint.route('/export', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@access_history_blueprint.protect(auth=True, right=AccessRightName.HISTORY_EXPORT.value)
@handle_route_errors("while exporting the access history")
def export_access_history(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route exporting the access history as a file - ``?format=json`` (default) or ``csv``, the list's
    ``?group_id=``, ``?kind=``, ``?document_id=``; newest first, at most ``EXPORT_LIMIT`` entries

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for an unknown format, a group id that is no id or an unknown kind; 503 past the time budget

    Returns:
        Response: The file
    """
    export_format: str = request.args.get(HistoryQuery.FORMAT.value, HistoryExportFormat.JSON.value)

    if export_format not in {member.value for member in HistoryExportFormat}:
        abort(400, UNKNOWN_FORMAT_MESSAGE)

    body, mimetype = export_body(export_entries(request_user, history_condition()), export_format)
    file_name: str = EXPORT_FILE_NAME.format(stamp=datetime.now(timezone.utc).strftime(EXPORT_STAMP_FORMAT),
                                             extension=export_format)

    return Response(body, mimetype=mimetype, headers={CONTENT_DISPOSITION_HEADER: attachment_disposition(file_name)})


@access_history_blueprint.route('/settings', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@access_history_blueprint.protect(auth=True, right=AccessRightName.HISTORY_EXPORT.value)
@handle_route_errors("while retrieving the access history settings")
def get_access_history_settings(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for how long the access history keeps an entry

    Args:
        request_user (CmdbUser): The caller

    Returns:
        GetSingleResponse: ``{retention_days}`` - 0 keeps every entry
    """
    return GetSingleResponse({HistorySettingsKey.RETENTION_DAYS.value: retention_days(request_user)},
                             body=request_wants_body()).make_response()


@access_history_blueprint.route('/settings', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@access_history_blueprint.protect(auth=True, right=AccessRightName.HISTORY_EXPORT.value)
@access_history_blueprint.validate(HISTORY_SETTINGS_SCHEMA)
@handle_route_errors("while changing the access history settings")
def update_access_history_settings(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route changing how long the access history keeps an entry - the change recorded in it

    Args:
        data (dict[str, Any]): ``{retention_days, comment?}``
        request_user (CmdbUser): The caller

    Returns:
        UpdateSingleResponse: 202 with ``{retention_days}``
    """
    comment: str | None = take_comment(data)
    days: int = set_retention(request_user, data[HistorySettingsKey.RETENTION_DAYS.value], comment)

    return UpdateSingleResponse({HistorySettingsKey.RETENTION_DAYS.value: days}).make_response()
