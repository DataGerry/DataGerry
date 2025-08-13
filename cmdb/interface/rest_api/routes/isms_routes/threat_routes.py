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
Implementation of all API routes for the IsmsThreats
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ThreatManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsThreat

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

from cmdb.errors.manager.threat_manager import (
    ThreatManagerInsertError,
    ThreatManagerGetError,
    ThreatManagerUpdateError,
    ThreatManagerDeleteError,
    ThreatManagerIterationError,
    ThreatManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

threat_blueprint = APIBlueprint('threat', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@threat_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@threat_blueprint.protect(auth=True, right='base.isms.threat.add')
@threat_blueprint.validate(IsmsThreat.SCHEMA)
def insert_isms_threat(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsThreat into the database

    Args:
        data (IsmsThreat.SCHEMA): Data of the IsmsThreat which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsThreat and its public_id
    """
    try:
        threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

        result_id: int = threat_manager.insert_item(data)

        created_threat: dict = threat_manager.get_item(result_id, as_dict=True)

        if created_threat:
            return InsertSingleResponse(created_threat, result_id).make_response()

        abort(404, "Could not retrieve the created Threat from the database!")
    except HTTPException as http_err:
        raise http_err
    except ThreatManagerInsertError as err:
        LOGGER.error("[insert_isms_threat] ThreatManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new Threat in the database!")
    except ThreatManagerGetError as err:
        LOGGER.error("[insert_isms_threat] ThreatManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Threat from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_threat] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Threat!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@threat_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@threat_blueprint.protect(auth=True, right='base.isms.threat.view')
@threat_blueprint.parse_collection_parameters()
def get_isms_threats(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsThreats

    Args:
        params (CollectionParameters): Filter for requested IsmsThreats
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsThreats matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsThreat] = threat_manager.iterate_items(builder_params)
        threats_list = [IsmsThreat.to_json(threat) for threat in iteration_result.results]

        api_response = GetMultiResponse(threats_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ThreatManagerIterationError as err:
        LOGGER.error("[get_isms_threats] ThreatManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Threats from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_threats] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Threats!")


@threat_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@threat_blueprint.protect(auth=True, right='base.isms.threat.view')
def get_isms_threat(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsThreat

    Args:
        public_id (int): public_id of the IsmsThreat
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsThreat
    """
    try:
        threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

        requested_threat = threat_manager.get_item(public_id, as_dict=True)

        if requested_threat:
            return GetSingleResponse(requested_threat, body = request.method == 'HEAD').make_response()

        abort(404, f"The Threat with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ThreatManagerGetError as err:
        LOGGER.error("[get_isms_threat] ThreatManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Threat with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_threat] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Threat with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@threat_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@threat_blueprint.protect(auth=True, right='base.isms.threat.edit')
@threat_blueprint.validate(IsmsThreat.SCHEMA)
def update_isms_threat(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsThreat

    Args:
        public_id (int): public_id of the IsmsThreat which should be updated
        data (IsmsThreat.SCHEMA): New IsmsThreat data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsThreat
    """
    try:
        threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

        to_update_threat = threat_manager.get_item(public_id)

        if not to_update_threat:
            abort(404, f"The Threat with ID:{public_id} was not found!")

        threat_manager.update_item(public_id, IsmsThreat.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ThreatManagerGetError as err:
        LOGGER.error("[update_isms_threat] ThreatManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Threat with ID: {public_id} from the database!")
    except ThreatManagerUpdateError as err:
        LOGGER.error("[update_isms_threat] ThreatManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Threat with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_threat] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Threat with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@threat_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@threat_blueprint.protect(auth=True, right='base.isms.threat.delete')
def delete_isms_threat(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsThreat

    Args:
        public_id (int): public_id of the IsmsThreat which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsThreat data
    """
    try:
        threat_manager: ThreatManager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)

        to_delete_threat = threat_manager.get_item(public_id, as_dict=True)

        if not to_delete_threat:
            abort(404, f"The Threat with ID:{public_id} was not found!")

        threat_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_threat).make_response()
    except HTTPException as http_err:
        raise http_err
    except ThreatManagerDeleteError as err:
        LOGGER.error("[delete_isms_threat] ThreatManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Threat with ID:{public_id}!")
    except ThreatManagerRiskUsageError as err:
        LOGGER.error("[delete_isms_threat] ThreatManagerRiskUsageError: %s", err)
        abort(400, f"Threat with ID:{public_id} can not be deleted because it is used by Risks!")
    except ThreatManagerGetError as err:
        LOGGER.error("[delete_isms_threat] ThreatManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Threat with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_threat] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Threat with ID: {public_id}!")
