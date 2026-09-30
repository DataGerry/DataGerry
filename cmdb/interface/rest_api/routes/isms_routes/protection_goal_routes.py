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
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import ProtectionGoalManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsProtectionGoal
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey

from cmdb.framework.results import IterationResult
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import (
    get_item_or_404,
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    PROTECTION_GOAL_LABEL,
    IsmsManagerErrorMessage,
)
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
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id, update_item_from_payload
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

protection_goal_blueprint = APIBlueprint('protection_goal', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@protection_goal_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.add')
@protection_goal_blueprint.validate(build_write_schema(IsmsProtectionGoal.SCHEMA))
@handle_route_errors("while creating the ProtectionGoal")
@handle_manager_errors(manager_error_messages(PROTECTION_GOAL_LABEL, {
    ProtectionGoalManagerInsertError: IsmsManagerErrorMessage.INSERT,
    ProtectionGoalManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
}))
def insert_isms_protection_goal(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsProtectionGoal into the database

    Args:
        data (IsmsProtectionGoal.SCHEMA): Data of the IsmsProtectionGoal which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert or the read-back of the created ProtectionGoal fails, 500 when
            the created ProtectionGoal cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsProtectionGoal and its public_id
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    if data.get(ProtectionGoalKey.PREDEFINED.value):
        abort(400, "Predefined ProtectionGoals cannot be created via API!")

    #Check if a ProtectionGoal with the name already exists
    goal_with_name = protection_goal_manager.get_one_by(
        {ProtectionGoalKey.NAME.value: data.get(ProtectionGoalKey.NAME.value)}
    )

    if goal_with_name:
        abort(400, f"A ProtectionGoal with the name {data.get(ProtectionGoalKey.NAME.value)} already exists!")

    result_id = protection_goal_manager.insert_item(data)

    created_protection_goal: dict[str, Any] = require_created_item(
        protection_goal_manager.get_item(result_id, as_dict=True), PROTECTION_GOAL_LABEL,
    )

    return InsertSingleResponse(created_protection_goal, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@protection_goal_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.view')
@protection_goal_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving ProtectionGoals")
@handle_manager_errors(manager_error_messages(PROTECTION_GOAL_LABEL, {
    ProtectionGoalManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_protection_goals(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsProtectionGoals

    Args:
        params (CollectionParameters): Filter for requested IsmsProtectionGoals
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsProtectionGoals matching the CollectionParameters
    """
    body = request_wants_body()

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


@protection_goal_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.view')
@handle_route_errors("while retrieving the ProtectionGoal with ID: {public_id}")
@handle_manager_errors(manager_error_messages(PROTECTION_GOAL_LABEL, {
    ProtectionGoalManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_protection_goal(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsProtectionGoal
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    requested_protection_goal = get_item_or_404(protection_goal_manager, public_id,
                                                 f"The ProtectionGoal with ID:{public_id} was not found!")

    return GetSingleResponse(requested_protection_goal, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@protection_goal_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.edit')
@protection_goal_blueprint.validate(build_write_schema(IsmsProtectionGoal.SCHEMA))
@handle_route_errors("while updating the ProtectionGoal with ID: {public_id}")
@handle_manager_errors(manager_error_messages(PROTECTION_GOAL_LABEL, {
    ProtectionGoalManagerGetError: IsmsManagerErrorMessage.GET,
    ProtectionGoalManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
}))
def update_isms_protection_goal(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal which should be updated
        data (IsmsProtectionGoal.SCHEMA): New IsmsProtectionGoal data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsProtectionGoal
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    to_update_protection_goal: IsmsProtectionGoal = get_item_or_404(
                                                        protection_goal_manager, public_id,
                                                        f"The ProtectionGoal with ID:{public_id} was not found!",
                                                        as_dict=False)

    if data.get(ProtectionGoalKey.PREDEFINED.value) != to_update_protection_goal.predefined:
        abort(400, "The predefined property of ProtectionGoals cannot be edited!")

    if to_update_protection_goal.predefined is True:
        abort(400, "The predefined ProtectionGoals can not be edited!")

    # Reject only if a DIFFERENT ProtectionGoal already uses the new name (exclude this one)
    goal_with_name = protection_goal_manager.get_one_by(
        {ProtectionGoalKey.NAME.value: data.get(ProtectionGoalKey.NAME.value)}
    )

    if goal_with_name and goal_with_name.get(ProtectionGoalKey.PUBLIC_ID.value) != public_id:
        abort(400, f"A ProtectionGoal with the name {data.get(ProtectionGoalKey.NAME.value)} already exists!")

    # The URL owns the identity: a body public_id would otherwise be $set onto the document

    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_item_from_payload(protection_goal_manager, public_id, IsmsProtectionGoal, data)

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@protection_goal_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@protection_goal_blueprint.protect(auth=True, right='base.isms.protectionGoal.delete')
@handle_route_errors("while deleting the ProtectionGoal with ID: {public_id}")
@handle_manager_errors(
    manager_error_messages(PROTECTION_GOAL_LABEL, {
        ProtectionGoalManagerDeleteError: IsmsManagerErrorMessage.DELETE,
        ProtectionGoalManagerGetError: IsmsManagerErrorMessage.GET,
    }),
    refusals=manager_error_messages(PROTECTION_GOAL_LABEL, {
        ProtectionGoalManagerRiskUsageError: IsmsManagerErrorMessage.USED_BY_RISKS,
    }),
)
def delete_isms_protection_goal(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsProtectionGoal

    Args:
        public_id (int): public_id of the IsmsProtectionGoal which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsProtectionGoal data
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    to_delete_protection_goal: IsmsProtectionGoal = get_item_or_404(
                                                        protection_goal_manager, public_id,
                                                        f"The ProtectionGoal with ID:{public_id} was not found!",
                                                        as_dict=False)

    if to_delete_protection_goal.predefined:
        abort(400, "The predefined ProtectionGoals cannot be deleted!")

    protection_goal_manager.delete_with_follow_up(public_id)

    return DeleteSingleResponse(to_delete_protection_goal).make_response()
