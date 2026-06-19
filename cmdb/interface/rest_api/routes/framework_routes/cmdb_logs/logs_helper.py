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

from cmdb.manager import LogsManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.interface.rest_api.responses import GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_HEAD_METHOD: str = 'HEAD'


def build_object_logs_response(logs_manager: LogsManager,
                               query: Union[dict[str, Any], list[dict[str, Any]]],
                               params: CollectionParameters,
                               request: Request) -> Response:
    """
    Runs an object-log query and wraps the matching logs in a paginated GetMultiResponse

    Shared by every CmdbLog list endpoint: each only differs by the ``query`` it passes, so the
    iterate -> serialize -> GetMultiResponse assembly lives here once.

    Args:
        logs_manager (LogsManager): Manager used to iterate the logs collection
        query (dict[str, Any] | list[dict[str, Any]]): Match filter or aggregation pipeline
        params (CollectionParameters): Pagination/sort parameters from the request
        request (Request): Active request, used for the response URL and HEAD detection

    Returns:
        Response: A GetMultiResponse holding the serialized CmdbObjectLogs and the total count
    """
    builder_params = BuilderParameters(query, params.limit, params.skip, params.sort, params.order)

    iteration_result = logs_manager.iterate(builder_params)
    logs = [CmdbObjectLog.to_json(log) for log in iteration_result.results]

    api_response = GetMultiResponse(logs,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    request.method == HTTP_HEAD_METHOD)

    return api_response.make_response()
