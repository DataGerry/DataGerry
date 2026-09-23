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
requests instead of re-flattening ~200 rights per call.

**None of the routes carries an ACL right, and that is deliberate** - the catalogue is product
metadata, identical for every installation and already public in the source of an AGPL product, and
the group-edit screen needs it for anyone who may manage a group. **They are authenticated, though.**
`verify_api_access` alone is not enough: it returns immediately when the process is not in cloud
mode, so on-premise it would leave the whole catalogue answering with no credentials at all.
`insert_request_user` is what authenticates, and `.protect` is what authorizes.

**The right is `base.user-management.group.view`, borrowed rather than owned.** The catalogue has no
right of its own, and giving it one would gate an existing route on a right no group holds until an
administrator grants it. The group screens are what the catalogue exists for - the right-picker of
the group form reads it - so the right that opens those screens is the one that opens this. A group
holding a wildcard above it (`base.user-management.group.*`, `base.user-management.*`, `base.*`)
reaches it the same way.
"""
from logging import Logger, getLogger

from flask import request, abort
from werkzeug import Response

from cmdb.manager import GroupsManager, RightsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.framework.results import IterationResult
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
from cmdb.models.right_model.all_rights import ALL_RIGHTS
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import GetMultiResponse, GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import GROUP_VIEW_RIGHT
from cmdb.interface.rest_api.routes.user_management_routes.rights_constants import (
    RIGHTS_OVERVIEW_ROUTE,
    RightHolderKey,
)
from cmdb.interface.rest_api.routes.user_management_routes.rights_helper import (
    resolve_right_holders,
    with_right_holders,
)

from cmdb.errors.manager.rights_manager import RightsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

rights_blueprint = APIBlueprint('rights', __name__)

# The rights are a static, in-memory tree (not database-backed), so a single shared manager
# instance is reused across requests instead of rebuilding the flattened tree on every call
rights_manager: RightsManager = RightsManager()

# -------------------------------------------------------------------------------------------------------------------- #

@rights_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.protect(auth=True, right=GROUP_VIEW_RIGHT)
@rights_blueprint.parse_collection_parameters(sort='name', view='list')
@handle_route_errors("while retrieving DataGerry Rights")
def get_rights(params: CollectionParameters, request_user: CmdbUser) -> Response:
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
        Guarded by `base.user-management.group.view` - the catalogue serves the group screens.
        Calling the route over HTTP HEAD will result in an empty body
    """
    # `request_user` is never read here: the catalogue is the same for every caller who may see it.
    # It is in the signature because `insert_request_user` injects it, and that decorator is what
    # authenticates the route - `.protect` above is what authorizes it
    # pylint: disable=unused-argument
    body: bool = request_wants_body()

    if params.optional['view'] == 'tree':
        api_response = GetMultiResponse(RightsManager.tree_to_json(ALL_RIGHTS),
                                        total=len(rights_manager.rights),
                                        params=params,
                                        url=request.url,
                                        body=body)

        return api_response.make_response(pagination=False)

    iteration_result: IterationResult[BaseRight] = rights_manager.iterate_rights(
        limit=params.limit,
        skip=params.skip,
        sort=params.sort,
        order=params.order,
    )

    rights: list[dict] = [BaseRight.to_dict(right) for right in iteration_result.results]

    api_response = GetMultiResponse(rights,
                                    total=iteration_result.total,
                                    params=params,
                                    url=request.url,
                                    body=body)

    return api_response.make_response()


@rights_blueprint.route(RIGHTS_OVERVIEW_ROUTE, methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.protect(auth=True, right=GROUP_VIEW_RIGHT)
@rights_blueprint.parse_collection_parameters(sort='name')
@handle_route_errors("while retrieving the DataGerry Rights overview")
def get_rights_overview(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for a page of rights, each carrying the CmdbUserGroups that hold it

    The same paginated, sorted list `GET /rights/` answers, plus the two keys a rights table needs
    for its "Groups" column: `groups` (public_id / name / label of each holding group) and
    `groups_count`. Both are filled for every right on the page, so an empty list is an answer and
    not a missing one

    **Two queries per page, whatever the page size.** The holders come from ONE aggregation over
    `management.groups`, asked for the page's right names only - the alternative is a count query
    per right, which for this catalogue means ~200 of them

    `?search=` narrows the catalogue before the page is cut, so the reported total is the number of
    MATCHES and a pager built on it offers the pages that exist. The term is matched the way every
    other list route matches it - as literal text, case-insensitively, against the right's name,
    label and description (`RIGHT_SEARCHABLE_FIELDS`)

    Membership is **literal**: a group holds a right when its stored `rights` list carries that
    exact name. A wildcard above it grants the right at request time but is not counted here, which
    is what keeps this count equal to the listing a client gets from
    `GET /groups/?filter={{"rights": "<name>"}}`

    Args:
        params (CollectionParameters): Passed parameters over the http query string
        request_user (CmdbUser): The user requesting the overview

    Returns:
        GetMultiResponse: One page of rights, each with `groups` and `groups_count`

    Raises:
        HTTPException: 500 when the rights or their holders could not be assembled (e.g. an unknown
                       `?sort=` value, which reaches `BaseRight.__getitem__` as an unknown attribute)

    Notes:
        Guarded by `base.user-management.group.view` - the catalogue serves the group screens.
        Calling the route over HTTP HEAD will result in an empty body
    """
    groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

    iteration_result: IterationResult[BaseRight] = rights_manager.iterate_rights(
        limit=params.limit,
        skip=params.skip,
        sort=params.sort,
        order=params.order,
        search=params.optional.get(ParameterKey.SEARCH.value),
    )

    rights: list[dict] = [BaseRight.to_dict(right) for right in iteration_result.results]
    holders = resolve_right_holders(groups_manager, [right[RightHolderKey.NAME.value] for right in rights])

    api_response = GetMultiResponse(with_right_holders(rights, holders),
                                    total=iteration_result.total,
                                    params=params,
                                    url=request.url,
                                    body=request_wants_body())

    return api_response.make_response()


@rights_blueprint.route('/<string:name>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.protect(auth=True, right=GROUP_VIEW_RIGHT)
@handle_route_errors("while retrieving Right with name: {name}")
def get_right(name: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for a single right resource

    Args:
        name (str): Name of the right

    Returns:
        GetSingleResponse: Which includes the json data of a BaseRight

    Raises:
        HTTPException: 404 when no right matches the given name, 500 when the lookup itself failed

    Notes:
        Guarded by `base.user-management.group.view` - the catalogue serves the group screens.
        Calling the route over HTTP HEAD will result in an empty body
    """
    # `request_user` is never read here: the catalogue is the same for every caller who may see it.
    # It is in the signature because `insert_request_user` injects it, and that decorator is what
    # authenticates the route - `.protect` above is what authorizes it
    # pylint: disable=unused-argument
    try:
        right: BaseRight | None = rights_manager.get_right(name)

        if not right:
            abort(404, f"Right with name: {name} was not found!")

        return GetSingleResponse(BaseRight.to_dict(right), body=request_wants_body()).make_response()
    except RightsManagerGetError as err:
        LOGGER.error("[get_right] RightsManagerGetError: %s", err, exc_info=True)
        abort(500, f"Failed to retrieve the Right with name: {name}!")


@rights_blueprint.route('/levels', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rights_blueprint.protect(auth=True, right=GROUP_VIEW_RIGHT)
@handle_route_errors("while retrieving the Right levels")
def get_levels(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for a static collection of levels

    Returns:
        GetSingleResponse: The name -> level mapping (`Levels.as_name_map`), keyed by name because
            that is the direction a catalogue is read in - a client shows the names and works with
            the numbers - and in the enum's declaration order, CRITICAL first

    Raises:
        HTTPException: 500 when the mapping could not be serialised

    Notes:
        Guarded by `base.user-management.group.view` - the catalogue serves the group screens.
        Calling the route over HTTP HEAD method will result in an empty body
    """
    # `request_user` is never read here: the catalogue is the same for every caller who may see it.
    # It is in the signature because `insert_request_user` injects it, and that decorator is what
    # authenticates the route - `.protect` above is what authorizes it
    # pylint: disable=unused-argument
    return GetSingleResponse(Levels.as_name_map(), body=request_wants_body()).make_response()
