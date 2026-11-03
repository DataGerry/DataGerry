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

**A ProtectionGoal's name is unique**, compared exactly as sent - see ``protection_goal_helper``: a read answers the
ordinary case, the unique index on ``name`` a lost race, both with the same 400. A failed name read is its own 400
(``IsmsManagerErrorMessage.NAME_CHECK``).

**The three predefined goals are sealed**: not creatable, not editable, not deletable, the flag itself immutable.
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
    PROTECTION_GOAL_NOT_FOUND_MSG,
    PROTECTION_GOAL_PREDEFINED_CREATE_MSG,
    PROTECTION_GOAL_PREDEFINED_DELETE_MSG,
    PROTECTION_GOAL_PREDEFINED_EDIT_MSG,
    PROTECTION_GOAL_PREDEFINED_FLAG_MSG,
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
    ProtectionGoalManagerNameCheckError,
    ProtectionGoalManagerRiskUsageError,
)
from cmdb.interface.rest_api.routes.isms_routes.protection_goal_helper import (
    abort_if_protection_goal_name_taken,
    insert_protection_goal,
    update_protection_goal,
)
from cmdb.interface.rest_api.routes.routes_helper import pin_public_id, request_wants_body
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
    ProtectionGoalManagerNameCheckError: IsmsManagerErrorMessage.NAME_CHECK,
}))
def insert_isms_protection_goal(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsProtectionGoal into the database

    Args:
        data (IsmsProtectionGoal.SCHEMA): Data of the IsmsProtectionGoal which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 for a predefined goal, a name another goal holds (by the pre-check or, on a lost race,
            by the unique index), a failed name read, or a failed insert / read-back of the created ProtectionGoal;
            500 when the created ProtectionGoal cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsProtectionGoal and its public_id
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    if data.get(ProtectionGoalKey.PREDEFINED.value):
        abort(400, PROTECTION_GOAL_PREDEFINED_CREATE_MSG)

    abort_if_protection_goal_name_taken(protection_goal_manager, data[ProtectionGoalKey.NAME.value])

    result_id: int = insert_protection_goal(protection_goal_manager, data)

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
                                                 PROTECTION_GOAL_NOT_FOUND_MSG.format(public_id=public_id))

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
    ProtectionGoalManagerNameCheckError: IsmsManagerErrorMessage.NAME_CHECK,
}))
def update_isms_protection_goal(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsProtectionGoal

    A goal may keep its own name; a name another goal holds is refused by the pre-check or, on a lost race, by the
    unique index - both the same 400

    Args:
        public_id (int): public_id of the IsmsProtectionGoal which should be updated
        data (IsmsProtectionGoal.SCHEMA): New IsmsProtectionGoal data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 when the ProtectionGoal does not exist; 400 for a predefined goal or a changed
            predefined flag, a name another goal holds, a failed name read, or a failed read / update; 500 on an
            unexpected error

    Returns:
        UpdateSingleResponse: The new data of the IsmsProtectionGoal
    """
    protection_goal_manager: ProtectionGoalManager = ManagerProvider.get_manager(
                                                                        ManagerType.PROTECTION_GOAL,
                                                                        request_user
                                                                     )

    to_update_protection_goal: IsmsProtectionGoal = get_item_or_404(
                                                        protection_goal_manager, public_id,
                                                        PROTECTION_GOAL_NOT_FOUND_MSG.format(public_id=public_id),
                                                        as_dict=False)

    if data.get(ProtectionGoalKey.PREDEFINED.value) != to_update_protection_goal.predefined:
        abort(400, PROTECTION_GOAL_PREDEFINED_FLAG_MSG)

    if to_update_protection_goal.predefined is True:
        abort(400, PROTECTION_GOAL_PREDEFINED_EDIT_MSG)

    abort_if_protection_goal_name_taken(protection_goal_manager, data[ProtectionGoalKey.NAME.value], public_id)

    # The URL owns the identity: a body public_id would otherwise be $set onto the document
    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_protection_goal(protection_goal_manager, public_id, data)

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
                                                        PROTECTION_GOAL_NOT_FOUND_MSG.format(public_id=public_id),
                                                        as_dict=False)

    if to_delete_protection_goal.predefined:
        abort(400, PROTECTION_GOAL_PREDEFINED_DELETE_MSG)

    protection_goal_manager.delete_with_follow_up(public_id)

    return DeleteSingleResponse(to_delete_protection_goal).make_response()
