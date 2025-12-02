# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import logging
import ast
from typing import Any
from flask import abort, request
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
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.ci_explorer_model import NodeType, CmdbCiExplorerProfile

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
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

PARENT_LOCATION_REL_COLOR: str = "#A855F7"
CHILD_LOCATION_REL_COLOR: str = "#C084FC"

ci_explorer_blueprint = APIBlueprint('ci_explorer', __name__)
# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@ci_explorer_blueprint.route('/profile', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@ci_explorer_blueprint.validate(CmdbCiExplorerProfile.SCHEMA)
def insert_cmdb_ci_explorer_profile(data: dict, request_user: CmdbUser):
    """
    HTTP `POST` route to insert an CmdbCiExplorerProfile into the database

    Args:
        data (CmdbCiExplorerProfile.SCHEMA): Data of the CmdbCiExplorerProfile which should be inserted
        request_user (CmdbUser): User requesting this data

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
def get_cmdb_ci_explorer_profiles(params: CollectionParameters, request_user: CmdbUser):
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
    except CiExplorerProfileManagerIterationError as err:
        LOGGER.error("[get_cmdb_ci_explorer_profiles] CiExplorerProfileManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve CiExplorer Profiles from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_ci_explorer_profiles] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving CiExplorer Profiles!")





@ci_explorer_blueprint.route('/items', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_ci_explorer_nodes_edges(request_user: CmdbUser):
    """
    HTTP `GET` route to retrieve Nodes and Edges for the CI Explorer

    Expects the following data via request args:
            "target_id" (int): # public_id of target CmdbObject
            "target_type" (str): # Enum with PARENT, CHILD or BOTH
            "with_root" (bool): True # If True then the target Object will be part of the Response

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The requested nodes and edges
    """
    try:
        target_id = request.args.get("target_id", type=int)
        target_type = request.args.get("target_type", default="BOTH").upper()
        with_root: bool = request.args.get("with_root", default="false").lower() == "true"
        with_locations: bool = request.args.get("with_locations", default="false").lower() == "true"
        with_refs: bool = request.args.get("with_references", default="false").lower() == "true"
        # is_root_location: bool = request.args.get("is_root_location", default="false").lower() == "true"

        types_filter = parse_int_list_filter("types_filter")
        relations_filter = parse_int_list_filter("relations_filter")

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATIONS,
                                                                            request_user
                                                                        )
        locations_manager: LocationsManager =  ManagerProvider.get_manager(
                                                    ManagerType.LOCATIONS,
                                                    request_user
                                               )

        # If the Root-Location was clicked then just return its child objects
        # if is_root_location:
        #     child_objects = None
        #     root_child_locations = locations_manager.get_locations_by(
        #         parent=1
        #     )
        #     # Retrieve all child objects
        #     operator_in = {'$in': []}
        #     filter_public_ids = {'public_id': {}}

        #     operator_in.update({'$in': root_child_locations})
        #     filter_public_ids.update({'public_id': operator_in})

        #     child_objects = objects_manager.get_objects_by(**filter_public_ids)

        #     if child_objects and types_filter:
        #         child_objects = [obj for obj in child_objects if obj["type_id"] in types_filter]

        #     response = {
        #         'location_children': child_objects
        #     }

        #     return DefaultResponse(response).make_response()


        # Non root location handling
        if target_id is None:
            abort(400, "Missing ID of target Object!")

        if not NodeType.is_valid(target_type):
            abort(400, f"Invalid target_type '{target_type}'. Need one of: {', '.join(NodeType.__members__.keys())}")

        root_object = objects_manager.get_object(target_id) if with_root else None
        root_type_info = types_manager.get_type(root_object['type_id']) if root_object else None

        object_relations = list(object_relations_manager.find(
            criteria={"$or": [
                {"relation_parent_id": target_id},
                {"relation_child_id": target_id}
            ]}
        ))

        if relations_filter:
            object_relations = [rel for rel in object_relations if rel['relation_id'] in relations_filter]

        relation_ids = set(rel['relation_id'] for rel in object_relations)
        relations_list = relations_manager.find(criteria={"public_id": {"$in": list(relation_ids)}})
        relations_by_id = {rel['public_id']: rel for rel in relations_list}

        linked_object_ids = set()
        for rel in object_relations:
            if rel['relation_parent_id'] != target_id:
                linked_object_ids.add(rel['relation_parent_id'])
            if rel['relation_child_id'] != target_id:
                linked_object_ids.add(rel['relation_child_id'])

        linked_objects_cursor = objects_manager.find(criteria={"public_id": {"$in": list(linked_object_ids)}})
        linked_objects = {obj['public_id']: obj for obj in linked_objects_cursor}

        # Apply types_filter to both linked_objects and relations
        if types_filter:
            allowed_object_ids = {
                obj_id for obj_id, obj in linked_objects.items()
                if obj.get("type_id") in types_filter
            }

            object_relations = [
                rel for rel in object_relations
                if rel['relation_parent_id'] in allowed_object_ids or rel['relation_child_id'] in allowed_object_ids
            ]

            linked_objects = {
                obj_id: obj for obj_id, obj in linked_objects.items()
                if obj_id in allowed_object_ids
            }

        type_ids = {obj['type_id'] for obj in linked_objects.values()}
        if root_type_info:
            type_ids.add(root_type_info['public_id'])

        types_list = types_manager.find(criteria={"public_id": {"$in": list(type_ids)}})
        types_by_id = {t['public_id']: t for t in types_list}

        def get_title(obj: dict, obj_type: dict):
            label_field = obj_type.get('ci_explorer_label')
            if not label_field:
                return None
            for field in obj.get('fields', []):
                if field.get('name') == label_field:
                    return field.get('value')
            return None

        response = {}

        if with_root and root_object and root_type_info:
            root_title = get_title(root_object, root_type_info)
            response['root_node'] = {
                "linked_object": root_object,
                "title": root_title,
                "type_info": {
                    "type_id": root_type_info['public_id'],
                    "type_color": root_type_info.get('ci_explorer_color'),
                    "label": root_type_info.get('label'),
                    "icon": root_type_info['render_meta'].get('icon'),
                    "fields": root_type_info.get('fields', {}),
                },
                "relation_color": None,
            }

        child_nodes = {}
        child_edges = []
        parent_nodes = {}
        parent_edges = []

        for obj_rel in object_relations:
            relation = relations_by_id.get(obj_rel['relation_id'])
            if not relation:
                continue

            is_parent = obj_rel['relation_parent_id'] == target_id
            is_child = obj_rel['relation_child_id'] == target_id

            if is_parent:
                linked_id = obj_rel['relation_child_id']
                linked_type_id = obj_rel['relation_child_type_id']
                relation_color = relation.get('relation_color_parent')
                edge_from = target_id
                edge_to = linked_id
                edge_relation_name = relation.get('relation_name_parent')
                edge_relation_icon = relation.get('relation_icon_parent')
            elif is_child:
                linked_id = obj_rel['relation_parent_id']
                linked_type_id = obj_rel['relation_parent_type_id']
                relation_color = relation.get('relation_color_child')
                edge_from = linked_id
                edge_to = target_id
                edge_relation_name = relation.get('relation_name_child')
                edge_relation_icon = relation.get('relation_icon_child')
            else:
                continue

            linked_object = linked_objects.get(linked_id)
            linked_type = types_by_id.get(linked_type_id)

            if not linked_object or not linked_type:
                continue

            node_title = get_title(linked_object, linked_type)
            node_dict = {
                "linked_object": linked_object,
                "title": node_title,
                "type_info": {
                    "type_id": linked_type['public_id'],
                    "type_color": linked_type.get('ci_explorer_color'),
                    "label": linked_type['label'],
                    "icon": linked_type['render_meta'].get('icon'),
                    "fields": linked_type.get('fields', {}),
                },
                "relation_color": relation_color
            }

            edge_dict = {
                "from": edge_from,
                "to": edge_to,
                "metadata": {
                    "relation_id": relation['public_id'],
                    "relation_name": relation['relation_name'],
                    "relation_label": edge_relation_name,
                    "relation_icon": edge_relation_icon,
                    "relation_color": relation_color,
                }
            }

            if is_parent:
                child_nodes[linked_id] = node_dict
                child_edges.append(edge_dict)
            elif is_child:
                parent_nodes[linked_id] = node_dict
                parent_edges.append(edge_dict)

        if target_type in (NodeType.BOTH, NodeType.CHILD):
            response['children_nodes'] = list(child_nodes.values())
            response['child_edges'] = child_edges
        if target_type in (NodeType.BOTH, NodeType.PARENT):
            response['parent_nodes'] = list(parent_nodes.values())
            response['parent_edges'] = parent_edges

        response['location_parent_node'] = None
        response['location_parent_edge'] = None
        response['location_child_nodes'] = None
        response['location_child_edges'] = None

        if with_locations:
            target_location = locations_manager.get_location_for_object(target_id)

            if target_location:
                parent_node: dict[str, Any] = None
                parent_edge = None

                # If the parent is root location
                if target_location['parent'] == 1:
                    parent_node = "root"
                else:
                    parent_object = objects_manager.get_object(target_location['object_id'])

                    # If the object is filtered out remove it
                    if parent_object and types_filter and parent_object['type_id'] not in types_filter:
                        parent_node = None
                    else: # The object is not filtered out
                        if parent_object:
                            parent_type = types_manager.get_type(parent_object['type_id'])
                            parent_title = get_title(parent_object, parent_type)

                            parent_node = [
                                {
                                    "linked_object": parent_object,
                                    "title": parent_title,
                                    "type_info": {
                                        "type_id": parent_type['public_id'],
                                        "type_color": parent_type.get('ci_explorer_color'),
                                        "label": parent_type['label'],
                                        "icon": parent_type['render_meta'].get('icon'),
                                        "fields": parent_type.get('fields', {}),
                                    },
                                    "relation_color": PARENT_LOCATION_REL_COLOR
                                }
                            ]

                            parent_edge: list[dict[str, Any]] = [
                                {
                                    "from": parent_object['public_id'],
                                    "to": target_id,
                                }
                            ]

                response['location_parent_node'] = parent_node
                response['location_parent_edge'] = parent_edge

                # Get all child objects of next level
                child_objects = None

                target_child_locations = locations_manager.get_locations_by(
                                                                parent=target_location['public_id']
                                                            )

                # If there are any children, then get the corresponding objects
                if target_child_locations:
                    # get all public_ids of child objects
                    object_ids = [loc["object_id"] for loc in target_child_locations]

                    # Retrieve all child objects
                    operator_in = {'$in': []}
                    filter_public_ids = {'public_id': {}}

                    operator_in.update({'$in': object_ids})
                    filter_public_ids.update({'public_id': operator_in})

                    child_objects: list[CmdbObject] = objects_manager.get_objects_by(**filter_public_ids)

                    # If type filter is active only keep objects of the type
                    if types_filter:
                        child_objects: list[CmdbObject] = [
                            obj for obj in child_objects if obj["type_id"] in types_filter
                        ]

                    # Get all types of the remaining objects
                    type_ids = [obj.type_id for obj in child_objects]

                    types_list = types_manager.find(criteria={"public_id": {"$in": list(type_ids)}})
                    types_by_id = {t['public_id']: t for t in types_list}

                    location_child_nodes = []
                    location_child_edges = []

                    for child_object in child_objects:
                        tmp_child_object = CmdbObject.to_json(child_object)
                        tmp_child_type = types_by_id.get(child_object['type_id'])
                        tmp_child_title = get_title(tmp_child_object, tmp_child_type)

                        tmp_child_node = {
                            "linked_object": tmp_child_object,
                            "title": tmp_child_title,
                            "type_info": {
                                "type_id": tmp_child_type['public_id'],
                                "type_color": tmp_child_type.get('ci_explorer_color'),
                                "label": tmp_child_type['label'],
                                "icon": tmp_child_type['render_meta'].get('icon'),
                                "fields": tmp_child_type.get('fields', {}),
                            },
                            "relation_color": CHILD_LOCATION_REL_COLOR
                        }

                        location_child_nodes.append(tmp_child_node)

                        tmp_child_edge = {
                            "from": tmp_child_object['public_id'],
                            "to": target_id
                        }

                        location_child_edges.append(tmp_child_edge)

                    response['location_child_nodes'] = location_child_nodes
                    response['location_child_edges'] = location_child_edges

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
def update_tooltip(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update the ci_explorer_tooltip of an CmdbObject from the CI Explorer

    Args:
        public_id (int): public_id of the CmdbObject which should be updated
        data (dict): New tooltip data ({'ci_explorer_tooltip': <string>})
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The Tooltip which was set for the CmdbObject
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        to_update_object: CmdbObject = objects_manager.get_object(public_id)

        if not to_update_object:
            abort(404, f"The Object with ID:{public_id} was not found!")

        to_update_object['ci_explorer_tooltip'] = data.get('ci_explorer_tooltip')

        objects_manager.update_object(public_id, to_update_object)

        return DefaultResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_tooltip] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Tooltip for Object-ID: {public_id}!")


@ci_explorer_blueprint.route('/type_label/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def update_type_label(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update the ci_explorer_label for a CmdbType

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        data (dict): New label data ({'ci_explorer_label': <string>})
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The Label which was set for the CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        to_update_type: CmdbType = types_manager.get_type(public_id)

        if not to_update_type:
            abort(404, f"The Type with ID:{public_id} was not found!")

        to_update_type['ci_explorer_label'] = data.get('ci_explorer_label')

        types_manager.update_type(public_id, to_update_type)

        return DefaultResponse(data).make_response()
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
def update_cmdb_ci_explorer_profile(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbCiExplorerProfile

    Args:
        public_id (int): public_id of the CmdbCiExplorerProfile which should be updated
        data (CmdbCiExplorerProfile.SCHEMA): New CmdbCiExplorerProfile data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbCiExplorerProfile
    """
    try:
        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
                                                                            ManagerType.CI_EXPLORER_PROFILE,
                                                                            request_user
                                                                         )

        to_update_explorer_profile: CmdbCiExplorerProfile = ci_explorer_profile_manager.get_item(public_id)

        if not to_update_explorer_profile:
            abort(404, f"The CiExplorer Profile with ID:{public_id} was not found!")


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
def delete_cmdb_ci_explorer_profile(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single CmdbCiExplorerProfile

    Args:
        public_id (int): public_id of the CmdbCiExplorerProfile which should be deleted
        request_user (CmdbUser): User requesting this data

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

        return DeleteSingleResponse(to_delete_explorer_profile).make_response()
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

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def parse_int_list_filter(arg_name: str) -> set[int]:
    """
    Converts a list of intergers from request.args to a python list of integers

    Args:
        arg_name (str): _description_

    Raises:
        ValueError: _description_

    Returns:
        set[int]: _description_
    """
    raw_value = request.args.get(arg_name)
    if not raw_value:
        return set()

    try:
        parsed = ast.literal_eval(raw_value)
        if not isinstance(parsed, list):
            raise ValueError
        return {int(x) for x in parsed}
    except (SyntaxError, ValueError, TypeError):
        abort(400, f"Invalid format for '{arg_name}'. Must be a list of integers like [1,2,3].")
