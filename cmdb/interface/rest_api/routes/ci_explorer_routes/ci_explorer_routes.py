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
Implementation of all API routes for CI Explorer
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import (
    ObjectsManager,
    TypesManager,
    RelationsManager,
    ObjectRelationsManager,
    CiExplorerProfileManager,
    LocationsManager,
)
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.ci_explorer_model import NodeType, CmdbCiExplorerProfile

from cmdb.framework.ci_explorer.argparsing import (
    clamp_item_limit,
    parse_bool_arg,
    parse_int_list_filter,
    validate_node_type,
    validate_target_id,
)
from cmdb.framework.ci_explorer.graph import build_ci_explorer_graph

from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    DefaultResponse,
    InsertSingleResponse,
    GetMultiResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)

from cmdb.errors.manager.ci_explorer_profile_manager import (
    CiExplorerProfileManagerInsertError,
    CiExplorerProfileManagerGetError,
    CiExplorerProfileManagerUpdateError,
    CiExplorerProfileManagerDeleteError,
    CiExplorerProfileManagerIterationError,
)
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import (
    CiExplorerParam,
    CiExplorerField,
)
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_helper import apply_ci_explorer_field
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ci_explorer_blueprint = APIBlueprint('ci_explorer', __name__)
# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@ci_explorer_blueprint.route('/profile', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@ci_explorer_blueprint.validate(CmdbCiExplorerProfile.SCHEMA)
def insert_cmdb_ci_explorer_profile(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an CmdbCiExplorerProfile into the database

    Args:
        data (CmdbCiExplorerProfile.SCHEMA): Data of the CmdbCiExplorerProfile which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert / re-read fails; 404 when the created profile cannot be
                       re-read; 500 on an unexpected failure

    Returns:
        InsertSingleResponse: The new CmdbCiExplorerProfile and its public_id
    """
    try:
        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
                                                                            ManagerType.CI_EXPLORER_PROFILE,
                                                                            request_user
                                                                         )

        result_id = ci_explorer_profile_manager.insert_item(data)

        created_profile = ci_explorer_profile_manager.get_item(result_id, as_dict=True)

        if created_profile:
            return InsertSingleResponse(created_profile, result_id).make_response()

        abort(404, "Could not retrieve the created CiExplorer Profile from the database!")
    except HTTPException as http_err:
        raise http_err
    except CiExplorerProfileManagerInsertError as err:
        LOGGER.error("[insert_cmdb_ci_explorer_profile] CiExplorerProfileManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new CiExplorer Profile in the database!")
    except CiExplorerProfileManagerGetError as err:
        LOGGER.error("[insert_cmdb_ci_explorer_profile] CiExplorerProfileManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created CiExplorer Profile from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_ci_explorer_profile] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the CiExplorer Profile!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@ci_explorer_blueprint.route('/profile', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@ci_explorer_blueprint.parse_collection_parameters()
def get_cmdb_ci_explorer_profiles(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbCiExplorerProfiles

    Args:
        params (CollectionParameters): Filter for requested CmdbCiExplorerProfiles
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbCiExplorerProfiles matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
                                                                            ManagerType.CI_EXPLORER_PROFILE,
                                                                            request_user
                                                                         )

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbCiExplorerProfile] = ci_explorer_profile_manager.iterate_items(
                                                                        builder_params
                                                                   )
        explorer_profiles_list = [CmdbCiExplorerProfile.to_json(explorer_profile) for explorer_profile
                                 in iteration_result.results]

        api_response = GetMultiResponse(explorer_profiles_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except CiExplorerProfileManagerIterationError as err:
        LOGGER.error("[get_cmdb_ci_explorer_profiles] CiExplorerProfileManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve CiExplorer Profiles from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_ci_explorer_profiles] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving CiExplorer Profiles!")


@ci_explorer_blueprint.route('/items', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_ci_explorer_nodes_edges(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the CI Explorer node/edge payload

    Thin orchestrator: parses query-string arguments via cmdb.framework.ci_explorer.argparsing
    helpers, resolves the five managers required by the framework module, and delegates the
    actual payload construction to ``cmdb.framework.ci_explorer.graph.build_ci_explorer_graph``.
    See that function's docstring for the full response shape

    Query args:
        target_id (int, required): public_id of the focal CmdbObject. 400 when missing
        target_type (str, default 'BOTH'): one of NodeType values (CHILD / PARENT / BOTH)
        with_root (bool, default false): include the focal object as ``root_node``
        with_locations (bool, default false): include the dg_location hierarchy (inverted)
        with_ipam_relations (bool, default false): include IPAM-hierarchy neighbours
            (SUPERNET / SUBNET / VLAN / interface carriers) folded into the standard
            parent/child buckets with metadata.source='ipam' on each edge
        item_limit (int, default 0=unlimited): cap on neighbour nodes
        types_filter (JSON list of int, optional): allowed neighbour type_ids
        relations_filter (JSON list of int, optional): allowed CmdbRelation public_ids

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The CI Explorer node/edge payload
    """
    try:
        target_id: int = validate_target_id(request.args.get(CiExplorerParam.TARGET_ID, type=int))
        target_type: NodeType = validate_node_type(
            request.args.get(CiExplorerParam.TARGET_TYPE, default=NodeType.BOTH.value).upper(),
        )
        with_root: bool = parse_bool_arg(request.args.get(CiExplorerParam.WITH_ROOT), default=False)
        with_locations: bool = parse_bool_arg(request.args.get(CiExplorerParam.WITH_LOCATIONS), default=False)
        with_ipam_relations: bool = parse_bool_arg(
            request.args.get(CiExplorerParam.WITH_IPAM_RELATIONS), default=False,
        )
        item_limit: int = clamp_item_limit(request.args.get(CiExplorerParam.ITEM_LIMIT, type=int))
        types_filter: frozenset[int] = parse_int_list_filter(request.args.get(CiExplorerParam.TYPES_FILTER))
        relations_filter: frozenset[int] = parse_int_list_filter(request.args.get(CiExplorerParam.RELATIONS_FILTER))

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user,
        )
        locations_manager: LocationsManager = ManagerProvider.get_manager(
            ManagerType.LOCATIONS, request_user,
        )

        response: dict[str, Any] = build_ci_explorer_graph(
            target_id=target_id,
            target_type=target_type,
            with_root=with_root,
            with_locations=with_locations,
            with_ipam_relations=with_ipam_relations,
            item_limit=item_limit,
            types_filter=types_filter,
            relations_filter=relations_filter,
            objects_manager=objects_manager,
            types_manager=types_manager,
            relations_manager=relations_manager,
            object_relations_manager=object_relations_manager,
            locations_manager=locations_manager,
        )

        return DefaultResponse(response).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_ci_explorer_nodes_edges] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving CI Explorer nodes and edges!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@ci_explorer_blueprint.route('/tooltip/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def update_tooltip(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to set the ci_explorer_tooltip of a CmdbObject from the CI Explorer

    Reads ``{'ci_explorer_tooltip': <string>}`` from the request body, sets it on the CmdbObject and
    returns the persisted value

    Args:
        public_id (int): public_id of the CmdbObject which should be updated
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the tooltip is missing from the body; 404 when the Object does not
                       exist; 500 on an unexpected failure

    Returns:
        DefaultResponse: The tooltip which was set for the CmdbObject
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        tooltip = apply_ci_explorer_field(
            objects_manager.get_object,
            objects_manager.update_object,
            public_id,
            CiExplorerField.TOOLTIP,
            request.get_json(silent=True),
            "Object",
        )

        return DefaultResponse({CiExplorerField.TOOLTIP.value: tooltip}).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_tooltip] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Tooltip for Object-ID: {public_id}!")


@ci_explorer_blueprint.route('/type_label/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def update_type_label(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to set the ci_explorer_label of a CmdbType from the CI Explorer

    Reads ``{'ci_explorer_label': <string>}`` from the request body, sets it on the CmdbType and
    returns the persisted value

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the label is missing from the body; 404 when the Type does not
                       exist; 500 on an unexpected failure

    Returns:
        DefaultResponse: The label which was set for the CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        label = apply_ci_explorer_field(
            types_manager.get_type,
            types_manager.update_type,
            public_id,
            CiExplorerField.LABEL,
            request.get_json(silent=True),
            "Type",
        )

        return DefaultResponse({CiExplorerField.LABEL.value: label}).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_type_label] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Label for Type-ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@ci_explorer_blueprint.route('/profile/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@ci_explorer_blueprint.validate(CmdbCiExplorerProfile.SCHEMA)
def update_cmdb_ci_explorer_profile(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbCiExplorerProfile

    Args:
        public_id (int): public_id of the CmdbCiExplorerProfile which should be updated
        data (CmdbCiExplorerProfile.SCHEMA): New CmdbCiExplorerProfile data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the lookup / update fails; 404 when the profile does not exist;
                       500 on an unexpected failure

    Returns:
        UpdateSingleResponse: The new data of the CmdbCiExplorerProfile
    """
    try:
        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
                                                                            ManagerType.CI_EXPLORER_PROFILE,
                                                                            request_user
                                                                         )

        # Only an existence check is needed here, so fetch the lightweight raw dict (no model build)
        to_update_explorer_profile: dict[str, Any] | None = ci_explorer_profile_manager.get_item(
            public_id, as_dict=True
        )

        if not to_update_explorer_profile:
            abort(404, f"The CiExplorer Profile with ID:{public_id} was not found!")

        # Pin the identity to the URL: a payload public_id can never rewrite the document's id
        data[CmdbObjectKey.PUBLIC_ID] = public_id

        ci_explorer_profile_manager.update_item(public_id, CmdbCiExplorerProfile.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except CiExplorerProfileManagerGetError as err:
        LOGGER.error("[update_cmdb_ci_explorer_profile] CiExplorerProfileManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the CiExplorer Profile with ID: {public_id} from the database!")
    except CiExplorerProfileManagerUpdateError as err:
        LOGGER.error("[update_cmdb_ci_explorer_profile] CiExplorerProfileManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the CiExplorer Profile with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_ci_explorer_profile] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the CiExplorer Profile with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@ci_explorer_blueprint.route('/profile/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def delete_cmdb_ci_explorer_profile(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbCiExplorerProfile

    Args:
        public_id (int): public_id of the CmdbCiExplorerProfile which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the lookup / delete fails; 404 when the profile does not exist;
                       500 on an unexpected failure

    Returns:
        DeleteSingleResponse: The deleted CmdbCiExplorerProfile data
    """
    try:
        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
                                                                            ManagerType.CI_EXPLORER_PROFILE,
                                                                            request_user
                                                                         )

        to_delete_explorer_profile: CmdbCiExplorerProfile = ci_explorer_profile_manager.get_item(public_id)

        if not to_delete_explorer_profile:
            abort(404, f"The CiExplorer Profile with ID:{public_id} was not found!")

        ci_explorer_profile_manager.delete_item(public_id)

        return DeleteSingleResponse(CmdbCiExplorerProfile.to_json(to_delete_explorer_profile)).make_response()
    except HTTPException as http_err:
        raise http_err
    except CiExplorerProfileManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_ci_explorer_profile] CiExplorerProfileManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the CiExplorer Profile with ID:{public_id}!")
    except CiExplorerProfileManagerGetError as err:
        LOGGER.error("[delete_cmdb_ci_explorer_profile] CiExplorerProfileManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the CiExplorer Profile with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_ci_explorer_profile] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the CiExplorer Profile with ID: {public_id}!")
