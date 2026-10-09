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
Implementation of all API routes for CmdbLocations

A CmdbLocation is a node in the location tree: it mirrors ONE CmdbObject's placement, holding the
object_id it belongs to, the parent node it hangs under, and the object's type metadata for rendering.
Every route is guarded by a ``base.framework.location.*`` right (see ``LocationRight``) on top of
``ApiLevel.ADMIN``

Five things govern a change here:

* **The placement writes are the two moves.** ``PATCH /<object_id>/parent`` places, moves or - with a null or
  non-positive parent - removes one object's placement (its node's children are promoted onto the node's parent);
  ``PATCH /parents`` moves several at once. There is no separate create, update or delete route: the object write
  path mirrors the location itself, and an object delete removes its node in the delete cascade.
* **The mirror must not desync.** A placement lives in two places - the CmdbLocation node's ``parent``
  and the owning object's location field - and every write updates both (``move_object_location``).
  `LocationsManager` owns the node, `ObjectsManager.set_location_field_for_objects` the field; a write that
  touches one without the other leaves the tree and the objects disagreeing.
* **A placement write is a READ and an UPDATE of its object.** Both moves ask the caller's ACL for READ and
  UPDATE on the object's type, and an active type, before any other check (``read_placeable_object`` /
  ``authorize_object_placement``, 403); the batch move decides once per type and refuses the whole batch. On the
  object write path the object's own write has already authorized it.
* **Racks own their placed members.** Both moves call ``guard_rack_location_change`` before writing and
  ``reconcile_object_rack_membership`` after, so a drop onto a Rack's node becomes a membership and a drag off it
  ends one. A new write route needs both, not one.
* **The tree is read lazily.** ``/tree/roots`` + ``/tree/<id>/children`` walk one level at a time,
  ``/tree/path/<id>`` opens straight to a node and ``/tree/search`` returns a pruned forest; each node
  carries ``has_children`` so the frontend can offer an expand without fetching the subtree. No route
  returns the whole forest in one response. Every level is name-ordered by the manager
  (case-insensitive, public_id as tie-break), so no route sorts.
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    LocationsManager,
    TypesManager,
    ObjectsManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import (
    abort_if_query_too_slow,
    abort_if_too_large,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    GetMultiResponse,
    DefaultResponse,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    build_location_forest,
    build_location_level,
    normalize_parent_id,
    validate_object_location_move,
    validate_object_location_moves,
    move_object_location,
    PlacementTarget,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    guard_rack_location_change,
    reconcile_object_rack_membership,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    BULK_MOVE_OBJECT_IDS_KEY,
    LocationRight,
)
from cmdb.models.location_model.location_constants import RootLocationDefault, LocationKey

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.locations_manager import (
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerIterationError,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

location_blueprint = APIBlueprint('locations', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@location_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@location_blueprint.parse_collection_parameters()
@handle_route_errors("while iterating Locations")
def get_cmdb_locations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbLocations

    Requires the ``base.framework.location.view`` right

    Args:
        params (CollectionParameters): Filter for requested CmdbLocations
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the iteration fails; 500 on an
            unexpected error

    Returns:
        Response: All the CmdbLocations matching the CollectionParameters (GetMultiResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        # Canonical documents straight from the read: the route only passes the result on as JSON,
        # so hydrating a CmdbLocation per row and converting it back would be two objects per node
        location_list, total = locations_manager.iterate_location_documents(builder_params)

        api_response = GetMultiResponse(location_list,
                                        total=total,
                                        params=params,
                                        url=request.url,
                                        body=request_wants_body())

        return api_response.make_response()
    except LocationsManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_locations] LocationsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Locations from the database!")


@location_blueprint.route('/tree/roots', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while requesting the root Locations")
def get_cmdb_location_tree_roots(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route returning the first level of the location tree

    Returns the direct children of the root location, each flagged with ``has_children`` so the
    frontend can lazily expand deeper levels via ``/tree/<public_id>/children`` instead of loading
    the whole forest at once

    Requires the ``base.framework.location.view`` right

    Args:
        request_user (CmdbUser): User requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the read fails; 500 on an
            unexpected error

    Returns:
        Response: The root location's direct children, name-ascending and each with has_children
                  (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        children: list[dict[str, Any]] = locations_manager.get_child_location_documents(
            RootLocationDefault.PUBLIC_ID
        )

        return DefaultResponse(build_location_level(children, locations_manager)).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_tree_roots] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the root Locations from the database!")


@location_blueprint.route('/tree/search', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while searching the Location tree")
def search_cmdb_location_tree(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route returning a pruned location tree matching a search query

    Reproduces the sidebar tree's search on the backend so it works without loading the whole
    forest: every location whose name matches the ``query`` (case-insensitive, literal substring)
    is returned together with its ancestor chain, assembled into a nested forest. Non-matching
    descendants of a match are excluded, so the response is the filtered tree view ready to render.
    Each node carries a ``has_children`` flag reflecting whether it has direct children in the FULL
    tree (even ones the prune left out) so the frontend can still offer to expand them. An empty
    ``query`` yields an empty forest

    Requires the ``base.framework.location.view`` right. The query is matched as a literal substring
    (``re.escape``d in the manager), and the result is NOT capped - see the filed decision on bounding
    it

    Args:
        request_user (CmdbUser): User requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the search fails; 500 on an
            unexpected error

    Returns:
        Response: The pruned location forest of matches and their ancestors (DefaultResponse)
    """
    try:
        query: str = request.args.get('query', '', type=str)

        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        matches_and_ancestors: list[dict[str, Any]] = locations_manager.search_locations_with_ancestors(query)

        # has_children reflects real direct children (some may be pruned out of the search result)
        node_ids: list[int] = [location[LocationKey.PUBLIC_ID.value] for location in matches_and_ancestors]
        parents_with_children: set[int] = locations_manager.get_parents_with_children(node_ids)

        forest: list[dict[str, Any]] = build_location_forest(matches_and_ancestors, parents_with_children)

        return DefaultResponse(forest).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[search_cmdb_location_tree] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to search the Location tree!")


@location_blueprint.route('/tree/path/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while requesting the path to Location with ID:{public_id}")
def get_cmdb_location_tree_path(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route returning the location tree pre-expanded to one location

    Powers the location picker when editing an object that already has a location: given the
    selected location's ``public_id`` (the value stored in the object's location field) it returns
    the forest opened all the way down to that node in ONE call - every root plus the full set of
    siblings at each level along the ancestor path to the target - instead of forcing the frontend
    to walk the lazy ``/tree/roots`` + ``/tree/<id>/children`` levels itself. Each node carries a
    ``has_children`` flag (real children in the FULL tree, so untouched branches stay expandable).
    The target's own children are not expanded; they load on demand like the rest of the lazy tree.
    The caller already knows which node is selected (it is ``public_id``), so no node is flagged

    Requires the ``base.framework.location.view`` right

    Args:
        public_id (int): public_id of the selected CmdbLocation to open the tree to
        request_user (CmdbUser): User requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbLocation carries the
            public_id; 400 when the read fails; 500 on an unexpected error

    Returns:
        Response: The forest expanded to the selected location, each node with has_children
                  (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        path_locations: list[dict[str, Any]] = locations_manager.get_locations_on_path_to(public_id)

        if not path_locations:
            abort(404, f"The Location with ID:{public_id} was not found!")

        # has_children reflects real direct children in the FULL tree (deeper levels are not fetched)
        node_ids: list[int] = [location[LocationKey.PUBLIC_ID.value] for location in path_locations]
        parents_with_children: set[int] = locations_manager.get_parents_with_children(node_ids)

        forest: list[dict[str, Any]] = build_location_forest(path_locations, parents_with_children)

        return DefaultResponse(forest).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_tree_path] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Location tree path to Location with ID:{public_id}!")


@location_blueprint.route('/tree/<int:public_id>/children', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while requesting children of Location with ID:{public_id}")
def get_cmdb_location_tree_children(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route returning the direct children of one location in the tree

    Powers the lazy expand of the sidebar location tree, one level at a time. Each returned node
    carries a ``has_children`` flag so a further expand control can be shown without fetching its
    subtree

    Requires the ``base.framework.location.view`` right

    Args:
        public_id (int): public_id of the CmdbLocation whose direct children should be returned
        request_user (CmdbUser): User requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the read fails; 500 on an
            unexpected error

    Returns:
        Response: The location's direct children, name-ascending and each with has_children
                  (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        children: list[dict[str, Any]] = locations_manager.get_child_location_documents(public_id)

        return DefaultResponse(build_location_level(children, locations_manager)).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_tree_children] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the child Locations of Location with ID:{public_id}!")


@location_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while retrieving the Location with ID:{public_id}")
def get_cmdb_location(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbLocation

    Requires the ``base.framework.location.view`` right

    Args:
        public_id (int): public_id of the CmdbLocation
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbLocation carries the
            public_id; 400 when the read fails; 500 on an unexpected error

    Returns:
        Response: The requested CmdbLocation (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        requested_location = locations_manager.get_location(public_id)

        if not requested_location:
            abort(404, f"The Location with ID:{public_id} was not found!")

        return DefaultResponse(requested_location).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Location with ID: {public_id} from the database!")


@location_blueprint.route('/<int:object_id>/object', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while retrieving the Location for Object with ID:{object_id}")
def get_cmdb_location_for_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to return the selected CmdbLocation for a given object_id (public_id of CmdbObject)

    Requires the ``base.framework.location.view`` right

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when the CmdbObject has no CmdbLocation;
            400 when the read fails; 500 on an unexpected error

    Returns:
        Response: The CmdbLocation linked to the given object_id (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        requested_location = locations_manager.get_location_for_object(object_id)

        if not requested_location:
            abort(404, f"The Location for Object with ID:{object_id} was not found!")

        return DefaultResponse(requested_location).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_for_object] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Location for Object with ID: {object_id} from the database!")


@location_blueprint.route('/<int:object_id>/parent', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while retrieving the parent location for Object with ID:{object_id}")
def get_cmdb_location_parent(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to return the parent CmdbLocation for a given object_id (public_id of CmdbObject)

    Requires the ``base.framework.location.view`` right

    "There is no parent" is a successful answer, not a 404: the route returns 200 with ``null`` both
    when the object has no location at all and when its location's parent node is missing. It must not
    404 for the second case only, so the same outcome had two encodings - and a dangling ``parent``
    reference (a data-integrity problem) was reported to the caller as if the object did not exist

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the read fails; 500 on an
            unexpected error

    Returns:
        Response: The parent CmdbLocation, or None when there is none (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        parent = None

        current_location = locations_manager.get_location_for_object(object_id)

        if current_location:
            parent = locations_manager.get_location(current_location[LocationKey.PARENT.value])

            if not parent:
                # A node whose parent id resolves to nothing - log it, but answer the question asked
                LOGGER.warning(
                    "[get_cmdb_location_parent] Location of Object ID: %s points at missing parent ID: %s!",
                    object_id, current_location[LocationKey.PARENT.value],
                )

        return DefaultResponse(parent).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_parent] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the parent Location for Object with ID: {object_id} from the database!")


@location_blueprint.route('/<int:object_id>/children', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.VIEW.value)
@handle_route_errors("while retrieving childen for Location of Object with ID: {object_id}")
def get_cmdb_children(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to get all direct child CmdbLocations for a given object_id

    Requires the ``base.framework.location.view`` right

    An object with no location has no children, so that is an empty list rather than a 404 - the same
    "nothing to give you is still an answer" rule the parent route follows. The ``except
    HTTPException`` arm below is therefore not reachable from this route's own body; it is the
    pass-through for an HTTPException raised by a collaborator, which is what every route in this file
    carries

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the read fails; 500 on an
            unexpected error

    Returns:
        Response: The direct child CmdbLocations for the given object_id, name-ascending
                  (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        children: list[dict[str, Any]] = []

        current_location = locations_manager.get_location_for_object(object_id)

        if current_location:
            children = locations_manager.get_child_location_documents(
                current_location[LocationKey.PUBLIC_ID.value]
            )

        return DefaultResponse(children).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_children] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Location for Object with ID: {object_id} from the database!")

# ---------------------------------------------- CRUD - MOVE (drag & drop) ------------------------------------------- #

@location_blueprint.route('/<int:object_id>/parent', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.EDIT.value)
@handle_route_errors("while moving the Location of Object with ID:{object_id}")
def move_cmdb_location_for_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route to move a single object's location placement to a new parent

    Powers a drag-and-drop of one node in the location tree. The body carries ``{parent}`` - the new
    parent CmdbLocation id (the root id to place at the top level, or null / a non-positive id to
    remove the placement). The caller's ACL has to grant READ and UPDATE on the object's type, and the type
    has to be active - checked first. The move is validated (parent exists, is selectable-as-parent, no cycle)
    and mirrored to both the object's location field and its CmdbLocation node; an invalid drop is
    rejected 400 so the frontend can revert it

    Requires the ``base.framework.location.edit`` right

    Args:
        object_id (int): public_id of the CmdbObject whose placement moves
        request_user (CmdbUser): The user making the request

    Raises:
        HTTPException: 403 when the user lacks the right, may not read or change the CmdbObject, or its Type
            is deactivated; 404 when the CmdbObject does not exist; 400 when the drop target is invalid, a
            Rack rule refuses the move or the write fails;
            500 on an unexpected error

    Returns:
        Response: Echo of the applied move ({object_id, parent}) (DefaultResponse)
    """
    try:
        body: dict[str, Any] = request.get_json(silent=True) or {}
        parent: int | None = normalize_parent_id(body.get(LocationKey.PARENT.value))

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        # First: the caller has to be allowed to read and change the object, and the drop has to be legal
        target: PlacementTarget = validate_object_location_move(
            object_id, parent, objects_manager, locations_manager, request_user,
        )

        # A Rack owns where its PLACED members sit, so one may not be dragged out of its rack from here,
        # and a Rack may not be dropped into another Rack
        guard_rack_location_change(request_user, object_id, parent, locations_manager)

        move_object_location(object_id, parent, request_user, objects_manager, locations_manager, target)

        # Dropping an object onto a Rack's node makes it a member of that Rack, and dragging it off ends
        # the membership - the tree and the rack say the same thing either way
        reconcile_object_rack_membership(
            request_user, object_id, parent, objects_manager, types_manager, locations_manager,
        )

        return DefaultResponse(
            {LocationKey.OBJECT_ID.value: object_id, LocationKey.PARENT.value: parent}
        ).make_response()
    except (ObjectsManagerGetError, ObjectsManagerUpdateError) as err:
        abort_if_too_large(err)
        LOGGER.error("[move_cmdb_location_for_object] ObjectsManager error: %s", err, exc_info=True)
        abort(400, f"Failed to move the Location of Object with ID:{object_id}!")
    except (LocationsManagerGetError, LocationsManagerUpdateError) as err:
        abort_if_too_large(err)
        LOGGER.error("[move_cmdb_location_for_object] LocationsManager error: %s", err, exc_info=True)
        abort(400, f"Failed to move the Location of Object with ID:{object_id}!")


@location_blueprint.route('/parents', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right=LocationRight.EDIT.value)
@handle_route_errors("while moving the Locations of the requested Objects")
def move_cmdb_locations(request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route to move several objects' location placements under one common parent

    Powers a multi-select drag-and-drop. The body carries ``{object_ids: [...], parent}``. Every
    listed object is authorized FIRST (it exists, the caller's ACL grants READ and UPDATE on its type, the
    type is active), then validated (it has a location field, the parent exists, is selectable-as-parent, no
    cycle); if any target is denied (403) or invalid (400) the whole batch is rejected and nothing is
    written. Otherwise every placement is moved and mirrored. ``parent`` null / non-positive removes the
    placement from each listed object

    Requires the ``base.framework.location.edit`` right

    The pre-flight reads are batched: the listed objects are fetched in one ``$in`` query, each distinct
    type is resolved once, and the parent - which the whole batch shares - is validated once instead of
    per object (see ``validate_object_location_moves``). The per-object cycle check still runs
    individually, because it depends on where each object currently sits

    Args:
        request_user (CmdbUser): The user making the request

    Raises:
        HTTPException: 403 when the user lacks the right, may not read or change a listed CmdbObject, or its
            Type is deactivated; 404 when a listed CmdbObject does not exist; 400 when ``object_ids`` is not a
            non-empty list of integers, a target is invalid, a Rack
            rule refuses a move or a write fails; 500 on an unexpected error

    Returns:
        Response: Echo of the applied moves ({object_ids, parent}) (DefaultResponse)
    """
    try:
        body: dict[str, Any] = request.get_json(silent=True) or {}
        raw_object_ids: Any = body.get(BULK_MOVE_OBJECT_IDS_KEY)

        if not isinstance(raw_object_ids, list) or not raw_object_ids:
            abort(400, f"The '{BULK_MOVE_OBJECT_IDS_KEY}' body field must be a non-empty list!")

        try:
            object_ids: list[int] = [int(object_id) for object_id in raw_object_ids]
        except (TypeError, ValueError):
            abort(400, f"The '{BULK_MOVE_OBJECT_IDS_KEY}' list must contain only integers!")

        parent: int | None = normalize_parent_id(body.get(LocationKey.PARENT.value))

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        # Atomic pre-flight: every target is authorized and validated before anything is written, so a denied
        # or invalid one rejects the whole batch rather than leaving it half-applied. Batched: one $in read for
        # the objects, one read and one ACL decision per distinct type, one parent check for all. Also hands each
        # object and its type to the apply pass, so it re-reads neither
        validated_targets: dict[int, PlacementTarget] = validate_object_location_moves(
            object_ids, parent, objects_manager, locations_manager, request_user,
        )

        # A Rack member is refused here too
        for object_id in object_ids:
            guard_rack_location_change(request_user, object_id, parent, locations_manager)

        for object_id in object_ids:
            move_object_location(
                object_id, parent, request_user, objects_manager, locations_manager, validated_targets[object_id]
            )
            reconcile_object_rack_membership(
                request_user, object_id, parent, objects_manager, types_manager, locations_manager,
            )

        return DefaultResponse(
            {BULK_MOVE_OBJECT_IDS_KEY: object_ids, LocationKey.PARENT.value: parent}
        ).make_response()
    except (ObjectsManagerGetError, ObjectsManagerUpdateError) as err:
        abort_if_too_large(err)
        LOGGER.error("[move_cmdb_locations] ObjectsManager error: %s", err, exc_info=True)
        abort(400, "Failed to move the Locations of the requested Objects!")
    except (LocationsManagerGetError, LocationsManagerUpdateError) as err:
        abort_if_too_large(err)
        LOGGER.error("[move_cmdb_locations] LocationsManager error: %s", err, exc_info=True)
        abort(400, "Failed to move the Locations of the requested Objects!")
