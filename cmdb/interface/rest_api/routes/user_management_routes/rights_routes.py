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
Implementation of all API routes for DataGerry Rights
"""
from logging import Logger, getLogger

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import RightsManager

from cmdb.framework.results import IterationResult
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.constants import NAME_TO_LEVEL
from cmdb.models.right_model.all_rights import ALL_RIGHTS
from cmdb.interface.route_utils import verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import GetMultiResponse, GetSingleResponse

from cmdb.errors.manager.rights_manager import RightsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

rights_blueprint = APIBlueprint('rights', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@rights_blueprint.route('/', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.parse_collection_parameters(sort='name', view='list')
def get_rights(params: CollectionParameters) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting a iterable collection of resources.

    Args:
        params (CollectionParameters): Passed parameters over the http query string

    Returns:
        GetMultiResponse: Which includes a IterationResult of the BaseRight.
    """
    try:
        rights_manager = RightsManager()
        body = request.method == 'HEAD'

        if params.optional['view'] == 'tree':
            api_response = GetMultiResponse(rights_manager.tree_to_json(ALL_RIGHTS),
                                            total=len(ALL_RIGHTS),
                                            params=params,
                                            url=request.url,
                                            body=body)

            return api_response.make_response(pagination=False)

        iteration_result: IterationResult[BaseRight] = rights_manager.iterate_rights(
                                                                        limit = params.limit,
                                                                        skip = params.skip,
                                                                        sort = params.sort,
                                                                        order = params.order
                                                                      )

        rights = [BaseRight.to_dict(type) for type in iteration_result.results]

        api_response = GetMultiResponse(rights,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except Exception as err:
        LOGGER.error("[get_rights] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving DataGerry Rights!")


@rights_blueprint.route('/<string:name>', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_right(name: str) -> Response:
    """
    HTTP `GET`/`HEAD` route for a single right resource

    Args:
        name (str): Name of the right

    Returns:
        GetSingleResponse: Which includes the json data of a BaseRight
    """
    try:
        rights_manager = RightsManager()

        right = rights_manager.get_right(name)

        if not right:
            abort(404, f"Right with name: {name} was not found in the database!")

        return GetSingleResponse(BaseRight.to_dict(right), body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except RightsManagerGetError as err:
        LOGGER.error("[get_right] RightsManagerGetError: %s", err, exc_info=True)
        abort(500, f"Failed to retrieve the Right with name: {name}!")
    except Exception as err:
        LOGGER.error("[get_right] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Right with name: {name}!")


@rights_blueprint.route('/levels', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_levels() -> Response:
    """
    HTTP `GET`/`HEAD` route for a static collection of levels

    Returns:
        GetSingleResponse: Which includes a levels as enum

    Notes:
        Calling the route over HTTP HEAD method will result in an empty body
    """
    try:
        return GetSingleResponse(NAME_TO_LEVEL, body=request.method == 'HEAD').make_response()
    except Exception as err:
        LOGGER.error("[get_levels] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while processing Right levels!")
