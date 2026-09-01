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

Three read-only routes over the static rights tree - the flat paginated list, one right by its
qualified name, and the level enum. There is no write side: rights are declared in
`cmdb.models.right_model.all_rights` at import time, not stored, so nothing here can create or edit
one; what a *group* holds is the CmdbUserGroup routes' business.

Because the tree is in-memory, a single `RightsManager` is built once at import and shared across
requests instead of re-flattening ~200 rights per call, and none of the routes carries an ACL right -
the catalogue is product metadata, identical for every installation.
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

# The rights are a static, in-memory tree (not database-backed), so a single shared manager
# instance is reused across requests instead of rebuilding the flattened tree on every call
rights_manager: RightsManager = RightsManager()

# -------------------------------------------------------------------------------------------------------------------- #

@rights_blueprint.route('/', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.parse_collection_parameters(sort='name', view='list')
def get_rights(params: CollectionParameters) -> Response:
    """
    HTTP `GET`/`HEAD` route for an iterable collection of DataGerry rights

    Supports two views via the `view` query parameter: `tree` returns the nested rights tree
    (unpaginated), any other value returns the flat, paginated and sorted list.

    Both views report the same `total`: the number of rights. `len(ALL_RIGHTS)` would be the number
    of top-level groups (10) rather than the ~200 rights the payload carries, which is why the count
    comes from the flattened tree the manager already holds.

    Args:
        params (CollectionParameters): Passed parameters over the http query string

    Returns:
        GetMultiResponse: Which includes an IterationResult of the BaseRight

    Raises:
        HTTPException: 500 when the rights could not be assembled (e.g. an unknown `?sort=` value,
                       which reaches `BaseRight.__getitem__` as an unknown attribute)

    Notes:
        No ACL right is required - the rights catalogue is static product metadata.
        Calling the route over HTTP HEAD will result in an empty body
    """
    try:
        body: bool = request.method == 'HEAD'

        if params.optional['view'] == 'tree':
            api_response = GetMultiResponse(RightsManager.tree_to_json(ALL_RIGHTS),
                                            total=len(rights_manager.rights),
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

        rights: list[dict] = [BaseRight.to_dict(right) for right in iteration_result.results]

        api_response = GetMultiResponse(rights,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=body)

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
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

    Raises:
        HTTPException: 404 when no right matches the given name, 500 when the lookup itself failed

    Notes:
        No ACL right is required - the rights catalogue is static product metadata.
        Calling the route over HTTP HEAD will result in an empty body
    """
    try:
        right: BaseRight | None = rights_manager.get_right(name)

        if not right:
            abort(404, f"Right with name: {name} was not found!")

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
        GetSingleResponse: The name -> level mapping (`NAME_TO_LEVEL`), keyed by name because the
            frontend renders a selector from the names and sends back the numeric value

    Raises:
        HTTPException: 500 when the mapping could not be serialised

    Notes:
        No ACL right is required - the levels are a static enum.
        Calling the route over HTTP HEAD method will result in an empty body
    """
    try:
        return GetSingleResponse(NAME_TO_LEVEL, body=request.method == 'HEAD').make_response()
    except Exception as err:
        LOGGER.error("[get_levels] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while processing Right levels!")
