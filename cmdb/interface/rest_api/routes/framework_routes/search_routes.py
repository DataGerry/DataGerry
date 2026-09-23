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
The two REST routes of the object search

* `GET /rest/search/quick/count/` - the search bar's live counter. One aggregation returns how many
  objects a regex term matches, split into active / inactive / total
* `GET|POST /rest/search/` - the search itself. Both methods carry the SAME payload, a JSON array of
  search parameters (`SearchParamKey` objects): POST in its body, GET in `?query=`. Both are turned
  into `SearchParam` objects before they reach the pipeline builder - skipping that step and handing
  the raw JSON to the builder answers **500** for every GET search carrying an actual term

Both routes build their pipeline with the request user and READ permission, so the ACL filter is in
the aggregation before it reaches the database. Neither checks an ACL *right*, which is recorded in
the discussion backlog rather than changed here.

Request parameters are strict: a non-numeric `?limit=` / `?skip=` or an unrecognised `?resolve=` is a
400, not a silently substituted default. Werkzeug's `request.args.get(..., type=int)` does the
opposite - it swallows the `ValueError` and returns the default - which is why the numbers are parsed
through `_int_arg` here instead
"""
import json
from typing import Any
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import QuickSearchPipelineBuilder, SearchPipelineBuilder
from cmdb.manager import ObjectsManager

from cmdb.framework.search.search_param import SearchParam
from cmdb.framework.search.search_constants import QuickSearchCountKey, SearchQueryKey

from cmdb.errors.framework_search import SearchParamError
from cmdb.framework.search.searcher_framework import SearcherFramework
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.routes_helper import fetch_only_active_objects
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import str_to_bool

from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

search_blueprint = APIBlueprint('search_rest', __name__, url_prefix='/search')

#: `?query=` when the client sends none - an empty parameter list, i.e. "match everything the ACL allows"
EMPTY_QUERY: str = '[]'

#: `?skip=` when the client sends none - start at the first match
DEFAULT_SKIP: int = 0

#: `?resolve=` when the client sends none - answer referenced objects as ids, not as rendered objects
DEFAULT_RESOLVE: str = 'false'

#: The quick counter's answer when the aggregation matched nothing at all
EMPTY_COUNT: dict[str, int] = {
    QuickSearchCountKey.ACTIVE.value: 0,
    QuickSearchCountKey.INACTIVE.value: 0,
    QuickSearchCountKey.TOTAL.value: 0,
}

# -------------------------------------------------------------------------------------------------------------------- #

def _int_arg(name: str, default: int) -> int:
    """
    Reads one integer query parameter, refusing a value that is not a number

    `request.args.get(name, default, int)` cannot be used for this: it catches the `ValueError`
    itself and answers the default, so `?limit=abc` would be served as a normal request with a
    silently substituted page size while `?limit=-1` is refused two lines later

    Args:
        name (str): Name of the query parameter to read
        default (int): Value to use when the parameter is absent or empty

    Raises:
        ValueError: When the parameter is present but not a valid integer

    Returns:
        int: The parsed value, or 'default' when the parameter was not sent
    """
    raw: str | None = request.args.get(name)

    if not raw:
        return default

    return int(raw)


def _parse_search_parameters(raw_query: str) -> list[SearchParam]:
    """
    Turns the JSON payload of a search request into the parameter objects the builder consumes

    Shared by both methods on purpose: GET carries the payload in `?query=` and POST in its body, but
    it is the same array of `SearchParamKey` objects and it has to become the same
    `list[SearchParam]`. Handing the raw JSON to `SearchPipelineBuilder` instead makes it read
    `.search_form` off plain strings and raise `AttributeError`

    Args:
        raw_query (str): The request's JSON payload

    Raises:
        SearchParamError: When an entry is missing a required key or carries an unusable value
        ValueError: When the payload is not valid JSON (json.JSONDecodeError derives from it)

    Returns:
        list[SearchParam]: One SearchParam per entry, in the order they were sent
    """
    return SearchParam.from_request(json.loads(raw_query))

# -------------------------------------------------------------------------------------------------------------------- #

@search_blueprint.route('/quick/count/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@search_blueprint.protect(auth=True)
@handle_route_errors("while processing quick search results")
def quick_search_result_counter(request_user: CmdbUser) -> Response:
    """
    Aggregates and returns quick search result counts (active, inactive, total) for the given user

    Backs the search bar's live counter, so it runs on every keystroke: one aggregation, and the
    pipeline carries the ACL filter for the requesting user

    Args:
        request_user (CmdbUser): The user making the request. Used for permission and access control

    Raises:
        HTTPException: 400 when the aggregation fails, 500 on an unexpected error

    Returns:
        Response: A Response containing the quick search result counts
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    search_term: str = request.args.get(SearchQueryKey.SEARCH_VALUE.value,
                                        SearcherFramework.DEFAULT_REGEX,
                                        str)
    builder = QuickSearchPipelineBuilder()
    only_active: bool = fetch_only_active_objects()
    pipeline: list[dict] = builder.build(search_term=search_term,
                                         user=request_user,
                                         permission=AccessControlPermission.READ,
                                         active_flag=only_active)

    try:
        result: list[dict] = list(objects_manager.aggregate_objects(pipeline=pipeline))
    except ObjectsManagerIterationError as err:
        LOGGER.error('[quick_search_result_counter] ObjectsManagerIterationError: %s', err, exc_info=True)
        abort(400, "Failed to aggregate Objects for quick search result")

    if result:
        return DefaultResponse(result[0]).make_response()

    return DefaultResponse(dict(EMPTY_COUNT)).make_response()


@search_blueprint.route('/', methods=['GET', 'POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while processing the search request")
def search_framework(request_user: CmdbUser) -> Response:
    """
    Processes a search request (GET or POST) using the SearcherFramework

    GET and POST are the same search: both carry a JSON array of search parameters - GET in
    `?query=`, POST in the body - and both are parsed by `_parse_search_parameters`. `?limit=` 0
    means every match (the pager convention of this API), `?skip=` pages through them and
    `?resolve=true` renders referenced CmdbObjects instead of their ids.

    The criteria are built with the request user and READ permission, so the pipeline the searcher
    runs is ACL-filtered before it reaches the database.

    Two failure modes this route has to avoid:

    * an error in the search block answering **204 with an empty body**, which a client cannot tell
      apart from "nothing matched" - and which turns an unusable `?limit=0` into a silently empty page
    * the GET branch not building `SearchParam` objects, which answers **500** for any GET search
      carrying an actual term and leaves only `?query={}` working

    Args:
        request_user (CmdbUser): The user making the request, used for permission checks and data access

    Raises:
        HTTPException: 400 when the parameters or the search itself are unusable, 500 on an
                       unexpected error

    Returns:
        Response: A Response object carrying the rendered page, the total and the per-type groups
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        try:
            limit: int = _int_arg(SearchQueryKey.LIMIT.value, SearcherFramework.DEFAULT_LIMIT)
            skip: int = _int_arg(SearchQueryKey.SKIP.value, DEFAULT_SKIP)
            only_active: bool = fetch_only_active_objects()
            raw_query: str = request.args.get(SearchQueryKey.QUERY.value) or EMPTY_QUERY
            resolve_object_references: bool = str_to_bool(
                request.args.get(SearchQueryKey.RESOLVE.value, DEFAULT_RESOLVE)
            )
        except ValueError:
            abort(400, "Could not retrieve the parameters from the request!")

        # 0 is 'every match' here as in every paginated route; a negative page size or offset is not a
        # weaker version of that but an unusable request, and MongoDB would refuse the stage anyway
        if limit < 0 or skip < 0:
            abort(400, "The 'limit' and 'skip' parameters of a search must not be negative!")

        try:
            # Only GET and POST are routed, so Werkzeug answers 405 for anything else before this
            # view runs - there is no third branch to write here
            payload: str | bytes = raw_query if request.method == 'GET' else request.data
            search_parameters: list[SearchParam] = _parse_search_parameters(payload)
        except SearchParamError as err:
            # The parameter list itself is unusable, and the message names which entry: a search that
            # dropped the bad one would answer 200 with more objects than the filter allows
            LOGGER.error("[search_framework] SearchParamError: %s", err)
            abort(400, str(err))
        except Exception as err:
            LOGGER.error("[search_framework] Exception: %s. Type: %s", err, type(err), exc_info=True)
            abort(400, "An unexpected error occured while processing the search request!")

        searcher = SearcherFramework(objects_manager)
        builder = SearchPipelineBuilder()

        query: list[dict] = builder.build(search_parameters,
                                          user=request_user,
                                          permission=AccessControlPermission.READ,
                                          active_flag=only_active)

        result: Any = searcher.aggregate(
            pipeline=query,
            request_user=request_user,
            limit=limit,
            skip=skip,
            resolve=resolve_object_references,
        )

        return DefaultResponse(result).make_response()
    except ObjectsManagerIterationError as err:
        LOGGER.error("[search_framework] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to aggregate the Objects for the search request!")
