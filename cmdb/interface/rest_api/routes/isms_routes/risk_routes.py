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
Implementation of all API routes for the IsmsRisks
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import RiskManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsRisk, RiskType
from cmdb.models.isms_model.isms_risk_constants import RiskKey

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
    ISMS_BULK_DELETE_DELETED_KEY,
    RISK_BULK_DELETED_RA_KEY,
    RISK_BULK_DELETED_CMA_KEY,
    RISK_LABEL,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.routes_helper import (
    extract_public_ids,
    request_wants_body,
    pin_public_id,
    update_item_from_payload,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
    DefaultResponse,
)

from cmdb.errors.manager.risk_manager import (
    RiskManagerInsertError,
    RiskManagerGetError,
    RiskManagerUpdateError,
    RiskManagerDeleteError,
    RiskManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

risk_blueprint = APIBlueprint('risk', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@risk_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.add')
@risk_blueprint.validate(build_write_schema(IsmsRisk.SCHEMA))
@handle_route_errors("while creating the Risk")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerInsertError: IsmsManagerErrorMessage.INSERT,
    RiskManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
}))
def insert_isms_risk(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsRisk into the database

    Args:
        data (IsmsRisk.SCHEMA): Data of the IsmsRisk which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert or the read-back of the created Risk fails, 500 when
            the created Risk cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsRisk and its public_id
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    # risk_type is refused by IsmsRisk.SCHEMA itself (an 'allowed' list built from RiskType), so
    # only the cross-field rule a per-field schema cannot express is left to check here
    if not is_risk_data_valid(data):
        abort(400, "Incomplete Risk data, no creation possible!")

    result_id: int = risk_manager.insert_item(data)

    created_risk: dict[str, Any] = require_created_item(risk_manager.get_item(result_id, as_dict=True), RISK_LABEL)

    return InsertSingleResponse(created_risk, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@risk_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.view')
@risk_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving Risks")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_risks(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsRisks

    Args:
        params (CollectionParameters): Filter for requested IsmsRisks
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsRisks matching the CollectionParameters
    """
    body = request_wants_body()

    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

    iteration_result: IterationResult[IsmsRisk] = risk_manager.iterate_items(builder_params)
    risks_list = [IsmsRisk.to_json(risk) for risk in iteration_result.results]

    api_response = GetMultiResponse(risks_list,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    body)

    return api_response.make_response()


@risk_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.view')
@handle_route_errors("while retrieving the Risk with ID: {public_id}")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_risk(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsRisk

    Args:
        public_id (int): public_id of the IsmsRisk
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsRisk
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    requested_risk = get_item_or_404(risk_manager, public_id,
                                     f"The Risk with ID:{public_id} was not found!")

    return GetSingleResponse(requested_risk, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@risk_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.edit')
@risk_blueprint.validate(build_write_schema(IsmsRisk.SCHEMA))
@handle_route_errors("while updating the Risk with ID: {public_id}")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerGetError: IsmsManagerErrorMessage.GET,
    RiskManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
}))
def update_isms_risk(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsRisk

    Args:
        public_id (int): public_id of the IsmsRisk which should be updated
        data (IsmsRisk.SCHEMA): New IsmsRisk data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsRisk
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    get_item_or_404(risk_manager, public_id,
                    f"The Risk with ID:{public_id} was not found!", as_dict=False)

    # See the insert route: the schema owns risk_type, this owns the cross-field rule
    if not is_risk_data_valid(data):
        abort(400, "Incomplete Risk data, no update possible!")

    # The URL owns the identity: a body public_id would otherwise be $set onto the document

    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_item_from_payload(risk_manager, public_id, IsmsRisk, data)

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@risk_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.delete')
@handle_route_errors("while deleting the Risk with ID: {public_id}")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerDeleteError: IsmsManagerErrorMessage.DELETE,
    RiskManagerGetError: IsmsManagerErrorMessage.GET,
}))
def delete_isms_risk(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsRisk

    Args:
        public_id (int): public_id of the IsmsRisk which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsRisk data
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    to_delete_risk = get_item_or_404(risk_manager, public_id,
                                     f"The Risk with ID:{public_id} was not found!")

    risk_manager.delete_with_follow_up(public_id)

    return DeleteSingleResponse(to_delete_risk).make_response()


@risk_blueprint.route('/delete/<string:public_ids>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_blueprint.protect(auth=True, right='base.isms.risk.delete')
@handle_route_errors("while bulk-deleting Risks")
@handle_manager_errors(manager_error_messages(RISK_LABEL, {
    RiskManagerDeleteError: IsmsManagerErrorMessage.BULK_DELETE,
}))
def delete_many_isms_risks(public_ids: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to bulk-delete IsmsRisks by a comma-separated id list

    Unlike the other ISMS bulk deletes (which refuse a still-referenced item), deleting a Risk is an
    unconditional CASCADE: every deleted Risk takes its RiskAssessments (referencing it via risk_id)
    and, beneath them, their ControlMeasureAssignments with it - the same cascade the single-delete
    performs, batched over the whole list. Non-existent ids are silently ignored. The response reports
    the deleted Risk ids plus how many RiskAssessments and ControlMeasureAssignments the cascade
    removed alongside them

    Args:
        public_ids (str): Comma-separated IsmsRisk public_ids to delete
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: {'successfully': [deleted Risk ids], 'deleted_risk_assessments': int,
                          'deleted_control_measure_assignments': int}
    """
    risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

    requested_ids: list[int] = extract_public_ids(public_ids)

    deleted_ids, deleted_ras, deleted_cmas = risk_manager.delete_many_with_follow_up(requested_ids)

    return DefaultResponse({
        ISMS_BULK_DELETE_DELETED_KEY: sorted(deleted_ids),
        RISK_BULK_DELETED_RA_KEY: deleted_ras,
        RISK_BULK_DELETED_CMA_KEY: deleted_cmas,
    }).make_response()

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def is_risk_data_valid(data: dict[str, Any]) -> bool:
    """
    Validates the risk data dictionary based on the specified risk type

    Depending on the risk_type, additional fields are required:
      - For THREAT_X_VULNERABILITY: 'threats' and 'vulnerabilities' must be provided
      - For THREAT: 'threats' must be provided
      - For EVENT: 'consequences' and 'description' must be provided

    Args:
        data (dict[str, Any]): The risk data to validate

    Returns:
        bool: True if the risk data is valid, False otherwise
    """
    data_risk_type = data.get(RiskKey.RISK_TYPE.value)

    if not RiskType.is_valid(data_risk_type):
        return False

    if data_risk_type == RiskType.THREAT_X_VULNERABILITY:
        if not data.get(RiskKey.THREATS.value):
            return False

        if not data.get(RiskKey.VULNERABILITIES.value):
            return False

    if data_risk_type == RiskType.THREAT:
        if not data.get(RiskKey.THREATS.value):
            return False

    if data_risk_type == RiskType.EVENT:
        if not data.get(RiskKey.CONSEQUENCES.value):
            return False

        if not data.get(RiskKey.DESCRIPTION.value):
            return False

    return True
