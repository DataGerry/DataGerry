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
Implementation of all API routes for IsmsRiskClasses
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.responses.default_response import DefaultResponse
from cmdb.manager import RiskClassManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsRiskClass
from cmdb.models.isms_model.isms_helper import remove_deleted_risk_class_from_matrix
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import MAX_ISMS_RISK_CLASSES

from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import get_item_or_404
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)

from cmdb.errors.manager.risk_class_manager import (
    RiskClassManagerInsertError,
    RiskClassManagerGetError,
    RiskClassManagerUpdateError,
    RiskClassManagerDeleteError,
    RiskClassManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

risk_class_blueprint = APIBlueprint('risk_classes', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@risk_class_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.add')
@risk_class_blueprint.validate(IsmsRiskClass.SCHEMA)
def insert_isms_risk_class(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsRiskClass into the database

    Args:
        data (IsmsRiskClass.SCHEMA): Data of the IsmsRiskClass which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsRiskClass and its public_id
    """
    try:
        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        # There is a Limit of MAX_ISMS_RISK_CLASSES Risk classes
        if risk_class_manager.count_documents() >= MAX_ISMS_RISK_CLASSES:
            abort(403, f"Only a maximum of {MAX_ISMS_RISK_CLASSES} RiskClasses can be created!")

        result_id: int = risk_class_manager.insert_item(data)

        created_risk_class: dict = risk_class_manager.get_item(result_id, as_dict=True)

        if not created_risk_class:
            abort(404, "Could not retrieve the created RiskClass from the database!")

        return InsertSingleResponse(created_risk_class, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskClassManagerInsertError as err:
        LOGGER.error("[insert_isms_risk_class] RiskClassManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new RiskClass in the database!")
    except RiskClassManagerGetError as err:
        LOGGER.error("[insert_isms_risk_class] RiskClassManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created RiskClass from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_risk_class] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the RiskClass!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@risk_class_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.view')
@risk_class_blueprint.parse_collection_parameters()
def get_isms_risk_classes(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsRiskClasses

    Args:
        params (CollectionParameters): Filter for requested IsmsRiskClasses
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsRiskClasses matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsRiskClass] = risk_class_manager.iterate_items(builder_params)
        risk_class_list = [IsmsRiskClass.to_json(risk_class) for risk_class in iteration_result.results]

        api_response = GetMultiResponse(risk_class_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except RiskClassManagerIterationError as err:
        LOGGER.error("[get_isms_risk_classes] RiskClassManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve RiskClasses from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_classes] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving RiskClasses!")


@risk_class_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.view')
def get_isms_risk_class(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsRiskClass

    Args:
        public_id (int): public_id of the IsmsRiskClass
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsRiskClass
    """
    try:
        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        requested_risk_class = get_item_or_404(risk_class_manager, public_id,
                                               f"The RiskClass with ID:{public_id} was not found!")

        return GetSingleResponse(requested_risk_class, body = request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskClassManagerGetError as err:
        LOGGER.error("[get_isms_risk_class] RiskClassManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskClass with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_class] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the RiskClass with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@risk_class_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.edit')
@risk_class_blueprint.validate(IsmsRiskClass.SCHEMA)
def update_isms_risk_class(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsRiskClass

    Args:
        public_id (int): public_id of the IsmsRiskClass which should be updated
        data (dict[str, Any]): New IsmsRiskClass data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsRiskClass
    """
    try:
        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        get_item_or_404(risk_class_manager, public_id,
                        f"The RiskClass with ID:{public_id} was not found!", as_dict=False)

        risk_class_manager.update_item(public_id, IsmsRiskClass.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskClassManagerGetError as err:
        LOGGER.error("[update_isms_risk_class] RiskClassManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskClass with ID: {public_id} from the database!")
    except RiskClassManagerUpdateError as err:
        LOGGER.error("[update_isms_risk_class] RiskClassManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the RiskClass with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_risk_class] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the RiskClass with ID: {public_id}!")


@risk_class_blueprint.route('/multiple', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.edit')
def update_multiple_isms_risk_classes(request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update multiple IsmsRiskClasses

    The list of IsmsRiskClasses to update is read from the JSON request body; each entry is
    processed independently and its per-item success/failure is reported in the response.

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: A per-item result list describing which updates succeeded or failed
    """
    try:
        data = request.get_json()

        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        results = []
        for item in data:
            public_id = item.get("public_id")
            if public_id is None:
                results.append({"public_id": None, "status": "failed", "message": "Missing public_id"})
                continue

            try:
                to_update_risk_class = risk_class_manager.get_item(public_id)

                if not to_update_risk_class:
                    results.append(
                        {"public_id": public_id, "status": "failed", "message": f"RiskClass ID:{public_id} not found"}
                    )
                    continue

                risk_class_manager.update_item(public_id, IsmsRiskClass.from_data(item))

                results.append({"public_id": public_id, "status": "success"})
            except RiskClassManagerGetError as err:
                LOGGER.error("[update_multiple_isms_risk_classes] RiskClassManagerGetError: %s", err, exc_info=True)
                results.append({
                    "public_id": public_id,
                    "status": "failed",
                    "message": f"Failed to retrieve RiskClass ID: {public_id}"
                })
            except RiskClassManagerUpdateError as err:
                LOGGER.error("[update_multiple_isms_risk_classes] RiskClassManagerUpdateError: %s", err, exc_info=True)
                results.append({
                    "public_id": public_id,
                    "status": "failed",
                    "message": f"Failed to update RiskClass ID: {public_id}"
                })
            except Exception as err:
                LOGGER.error(
                    "[update_multiple_isms_risk_classes] Exception: %s. Type: %s", err, type(err), exc_info=True
                )
                results.append(
                    {"public_id": public_id, "status": "failed", "message": "Internal server error"}
                )

        return DefaultResponse(results).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_multiple_isms_risk_classes] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating multiple RiskClasses!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@risk_class_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_class_blueprint.protect(auth=True, right='base.isms.riskClass.delete')
def delete_isms_risk_class(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsRiskClass

    Args:
        public_id (int): public_id of the IsmsRiskClass which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsRiskClass data
    """
    try:
        risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)

        to_delete_risk_class: dict[str, Any] = get_item_or_404(risk_class_manager, public_id,
                                                               f"The RiskClass with ID:{public_id} was not found!")

        risk_class_manager.delete_item(public_id)

        # Remove the risk_class from the RiskMatrix
        remove_deleted_risk_class_from_matrix(public_id, request_user)

        return DeleteSingleResponse(to_delete_risk_class).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskClassManagerDeleteError as err:
        LOGGER.error("[delete_isms_risk_class] RiskClassManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the RiskClass with ID:{public_id}!")
    except RiskClassManagerGetError as err:
        LOGGER.error("[delete_isms_risk_class] RiskClassManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskClass with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_risk_class] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the RiskClass with ID: {public_id}!")
