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
Implementation of all API routes for Search requests
"""
import json
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import QuickSearchPipelineBuilder, SearchPipelineBuilder
from cmdb.manager import ObjectsManager

from cmdb.framework.search.search_param import SearchParam
from cmdb.framework.search.searcher_framework import SearcherFramework
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.routes_helper import fetch_only_active_objects
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

search_blueprint = APIBlueprint('search_rest', __name__, url_prefix='/search')

# -------------------------------------------------------------------------------------------------------------------- #

@search_blueprint.route('/quick/count/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@search_blueprint.protect(auth=True)
def quick_search_result_counter(request_user: CmdbUser) -> Response:
    """
    Aggregates and returns quick search result counts (active, inactive, total) for the given user

    Args:
        request_user (CmdbUser): The user making the request. Used for permission and access control

    Returns:
        Response: A Response containing the quick search result counts
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        search_term = request.args.get('searchValue', SearcherFramework.DEFAULT_REGEX, str)
        builder = QuickSearchPipelineBuilder()
        only_active = fetch_only_active_objects()
        pipeline: list[dict] = builder.build(search_term=search_term,
                                        user=request_user,
                                        permission=AccessControlPermission.READ,
                                        active_flag=only_active)

        try:
            result = list(objects_manager.aggregate_objects(pipeline=pipeline))
        except ObjectsManagerIterationError as err:
            LOGGER.error('[quick_search_result_counter] ObjectsManagerIterationError: %s',err, exc_info=True)
            abort(400, "Failed to aggregate Objects for quick search result")

        if len(result) > 0:
            return DefaultResponse(result[0]).make_response()

        return DefaultResponse({'active': 0, 'inactive': 0, 'total': 0}).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[quick_search_result_counter] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while processing quick search results!")


@search_blueprint.route('/', methods=['GET', 'POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def search_framework(request_user: CmdbUser) -> Response:
    """
    Processes a search request (GET or POST) using the SearcherFramework, applying filters, pagination, and 
    optional reference resolution

    Args:
        request_user (CmdbUser): The user making the request, used for permission checks and data access

    Returns:
        Response: A Response object containing the search results (list of objects) or an empty list 
                  with HTTP 204 if an error occurs during search aggregation
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        try:
            limit = request.args.get('limit', SearcherFramework.DEFAULT_LIMIT, int)
            skip = request.args.get('skip', 0, int)
            only_active = fetch_only_active_objects()
            search_params: dict = request.args.get('query') or '{}'
            resolve_object_references: bool = request.args.get('resolve', 'false') in ['True', 'true']
        except ValueError:
            abort(400, "Could not retrieve the parameters from the request!")

        try:
            search_parameters: dict | list = {}

            if request.method == 'GET':
                search_parameters = json.loads(search_params)
            elif request.method == 'POST':
                search_params = json.loads(request.data)
                # LOGGER.debug(f"POST search_params: {search_params}")
                search_parameters = SearchParam.from_request(search_params)
                # LOGGER.debug(f"POST search_parameters: {search_parameters}")
            else:
                abort(405, f"Method: {request.method} not allowed!")
        except Exception as err:
            LOGGER.error("[search_framework] Exception: %s. Type: %s", err, type(err), exc_info=True)
            abort(400, "As unexpected error occured while processing the search request!")

        try:
            searcher = SearcherFramework(objects_manager)
            builder = SearchPipelineBuilder()

            query: list[dict] = builder.build(search_parameters,
                                            user=request_user,
                                            permission=AccessControlPermission.READ,
                                            active_flag=only_active)

            result = searcher.aggregate(
                                                     pipeline=query,
                                                     request_user=request_user,
                                                     limit=limit,
                                                     skip=skip,
                                                     resolve=resolve_object_references,
                                                     active=only_active
                                                 )

            return DefaultResponse(result).make_response()
        except Exception as err:
            LOGGER.error("[search_framework]: Exception: %s, Type: %s",err, type(err), exc_info=True)
            return DefaultResponse([]).make_response(204)
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[search_framework] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while processing the search request!")
