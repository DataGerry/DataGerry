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
Helper methods shared by the CmdbLog REST routes
"""
from typing import Any, Union

from flask import Request
from werkzeug import Response

from cmdb.manager import LogsManager, UsersManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.interface.rest_api.responses import GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LogKey,
    LogResultKey,
    INCLUDE_USERS_PARAM,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_HEAD_METHOD: str = 'HEAD'


def _include_users_requested(request: Request) -> bool:
    """Returns True when the request opted into embedded users via ``?include_users=true``."""
    return request.args.get(INCLUDE_USERS_PARAM, 'false').lower() == 'true'


def resolve_log_users(users_manager: UsersManager, logs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Resolves the distinct users referenced by a page of logs into a public_id-keyed map

    Collects the distinct ``user_id`` values from the given logs and fetches their minimal user
    projection in a single query. The map is keyed by the stringified user public_id so the frontend
    can map ``users[log.user_id]`` directly. Deleted users (a ``user_id`` with no matching user) are
    simply omitted; the log's own stored ``user_name`` remains the fallback.

    Args:
        users_manager (UsersManager): Manager used to fetch the minimal user projection
        logs (list[dict[str, Any]]): The serialized logs of the current page

    Returns:
        dict[str, dict[str, Any]]: Map of stringified public_id -> minimal user dict
    """
    user_ids = {log[LogKey.USER_ID.value] for log in logs if log.get(LogKey.USER_ID.value) is not None}

    if not user_ids:
        return {}

    users = users_manager.get_minimal_users_by_ids(list(user_ids))

    return {str(user[LogKey.PUBLIC_ID.value]): user for user in users}


def build_object_logs_response(logs_manager: LogsManager,
                               query: Union[dict[str, Any], list[dict[str, Any]]],
                               params: CollectionParameters,
                               request: Request,
                               request_user: CmdbUser) -> Response:
    """
    Runs an object-log query and wraps the matching logs in a paginated GetMultiResponse

    Shared by every CmdbLog list endpoint: each only differs by the ``query`` it passes, so the
    iterate -> serialize -> GetMultiResponse assembly lives here once. When the request sets
    ``?include_users=true`` the ``results`` payload becomes ``{logs, users}`` - the same paginated
    envelope (total/count/pager) with the referenced users resolved server-side under ``users`` so the
    frontend no longer fetches each log's user separately. Without the flag the payload stays the plain
    list of logs (the default, preserved for API clients).

    Args:
        logs_manager (LogsManager): Manager used to iterate the logs collection
        query (dict[str, Any] | list[dict[str, Any]]): Match filter or aggregation pipeline
        params (CollectionParameters): Pagination/sort parameters from the request
        request (Request): Active request, used for the response URL, HEAD + include_users detection
        request_user (CmdbUser): User making the request (used to resolve the UsersManager)

    Returns:
        Response: A GetMultiResponse; ``results`` is the log list, or ``{logs, users}`` when requested
    """
    builder_params = BuilderParameters(query, params.limit, params.skip, params.sort, params.order)

    iteration_result = logs_manager.iterate(builder_params)
    logs = [CmdbObjectLog.to_json(log) for log in iteration_result.results]

    api_response = GetMultiResponse(logs,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    request.method == HTTP_HEAD_METHOD)

    if _include_users_requested(request):
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)
        api_response.results = {
            LogResultKey.LOGS.value: api_response.results,
            LogResultKey.USERS.value: resolve_log_users(users_manager, logs),
        }

    return api_response.make_response()
