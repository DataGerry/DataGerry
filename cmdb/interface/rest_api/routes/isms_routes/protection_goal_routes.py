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
Implementation of all API routes for the IsmsProtectionGoals
"""
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ProtectionGoalManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsProtectionGoal

from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)

from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerInsertError,
    ProtectionGoalManagerGetError,
    ProtectionGoalManagerUpdateError,
    ProtectionGoalManagerDeleteError,
    ProtectionGoalManagerIterationError,
    ProtectionGoalManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

protection_goal_blueprint = APIBlueprint('protection_goal', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@protection_goal_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.add')
@protection_goal_blueprint.validate(IsmsProtectionGoal.SCHEMA)
def insert_isms_protection_goal(data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsProtectionGoal into the database

    Args:
        data (IsmsProtectionGoal.SCHEMA): Data of the IsmsProtectionGoal which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsProtectionGoal and its public_id
    """
    try:
        protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                            ManagerType.PROTECTION_GOAL,
                                                                            request_user
                                                                         )

        if data.get('predefined'):
            abort(400, "Predefined ProtectionGoals cannot be created via API!")

        #Check if a ProtectionGoal with the name already exists
        goal_with_name = protection_goal_manager.get_one_by({'name': data.get('name')})

        if goal_with_name:
            abort(400, f"A ProtectionGoal with the name {data.get('name')} already exists!")

        result_id = protection_goal_manager.insert_item(data)

        created_protection_goal = protection_goal_manager.get_item(result_id, as_dict=True)

        if created_protection_goal:
            return InsertSingleResponse(created_protection_goal, result_id).make_response()

        abort(404, "Could not retrieve the created ProtectionGoal from the database!")
    except HTTPException as http_err:
        raise http_err
    except ProtectionGoalManagerInsertError as err:
        LOGGER.error("[insert_isms_protection_goal] ProtectionGoalManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new ProtectionGoal in the database!")
    except ProtectionGoalManagerGetError as err:
        LOGGER.error("[insert_isms_protection_goal] ProtectionGoalManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ProtectionGoal from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_protection_goal] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ProtectionGoal!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@protection_goal_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.view')
@protection_goal_blueprint.parse_collection_parameters()
def get_isms_protection_goals(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsProtectionGoals

    Args:
        params (CollectionParameters): Filter for requested IsmsProtectionGoals
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsProtectionGoals matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                            ManagerType.PROTECTION_GOAL,
                                                                            request_user
                                                                         )

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsProtectionGoal] = protection_goal_manager.iterate_items(builder_params)
        protection_goals_list = [IsmsProtectionGoal.to_json(protection_goal) for protection_goal
                                 in iteration_result.results]

        api_response = GetMultiResponse(protection_goals_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ProtectionGoalManagerIterationError as err:
        LOGGER.error("[get_isms_protection_goals] ProtectionGoalManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ProtectionGoals from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_protection_goals] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ProtectionGoals!")


@protection_goal_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.view')
def get_isms_protection_goal(public_id: int, request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsProtectionGoal
    """
    try:
        protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                            ManagerType.PROTECTION_GOAL,
                                                                            request_user
                                                                         )

        requested_protection_goal = protection_goal_manager.get_item(public_id, as_dict=True)

        if requested_protection_goal:
            return GetSingleResponse(requested_protection_goal, body = request.method == 'HEAD').make_response()

        abort(404, f"The ProtectionGoal with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ProtectionGoalManagerGetError as err:
        LOGGER.error("[get_isms_protection_goal] ProtectionGoalManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ProtectionGoal with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_protection_goal] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ProtectionGoal with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@protection_goal_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.edit')
@protection_goal_blueprint.validate(IsmsProtectionGoal.SCHEMA)
def update_isms_protection_goal(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal which should be updated
        data (IsmsProtectionGoal.SCHEMA): New IsmsProtectionGoal data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsProtectionGoal
    """
    try:
        protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                            ManagerType.PROTECTION_GOAL,
                                                                            request_user
                                                                         )

        to_update_protection_goal: IsmsProtectionGoal = protection_goal_manager.get_item(public_id)

        if not to_update_protection_goal:
            abort(404, f"The ProtectionGoal with ID:{public_id} was not found!")

        if data.get('predefined') != to_update_protection_goal.predefined:
            abort(400, "The predefined property of ProtectionGoals cannot be edited!")

        if to_update_protection_goal.predefined is True:
            abort(400, "The predefined ProtectionGoals can not be edited!")

        #Check if a ProtectionGoal with the new name already exists
        goal_with_name = protection_goal_manager.get_one_by({'name': data.get('name')})

        if goal_with_name:
            abort(400, f"A ProtectionGoal with the name {data.get('name')} already exists!")

        protection_goal_manager.update_item(public_id, IsmsProtectionGoal.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ProtectionGoalManagerGetError as err:
        LOGGER.error("[update_isms_protection_goal] ProtectionGoalManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ProtectionGoal with ID: {public_id} from the database!")
    except ProtectionGoalManagerUpdateError as err:
        LOGGER.error("[update_isms_protection_goal] ProtectionGoalManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ProtectionGoal with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_protection_goal] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ProtectionGoal with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@protection_goal_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.delete')
def delete_isms_protection_goal(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsProtectionGoal data
    """
    try:
        protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                            ManagerType.PROTECTION_GOAL,
                                                                            request_user
                                                                         )

        to_delete_protection_goal: IsmsProtectionGoal = protection_goal_manager.get_item(public_id)

        if not to_delete_protection_goal:
            abort(404, f"The ProtectionGoal with ID:{public_id} was not found!")

        if to_delete_protection_goal.predefined:
            abort(400, "The predefined ProtectionGoals cannot be deleted!")

        protection_goal_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_protection_goal).make_response()
    except HTTPException as http_err:
        raise http_err
    except ProtectionGoalManagerDeleteError as err:
        LOGGER.error("[delete_isms_protection_goal] ProtectionGoalManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ProtectionGoal with ID:{public_id}!")
    except ProtectionGoalManagerRiskUsageError as err:
        LOGGER.error("[delete_isms_protection_goal] ProtectionGoalManagerRiskUsageError: %s", err)
        abort(400, f"ProtectionGoal with ID:{public_id} can not be deleted because it is used by Risks!")
    except ProtectionGoalManagerGetError as err:
        LOGGER.error("[delete_isms_protection_goal] ProtectionGoalManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ProtectionGoal with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_protection_goal] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ProtectionGoal with ID: {public_id}!")
