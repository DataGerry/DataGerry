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
Implementation of all API routes for the IsmsControlMeasures
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import ControlMeasureManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasure

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
    bulk_delete_reporting_in_use,
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_LABEL,
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

from cmdb.errors.manager.control_measure_manager import (
    ControlMeasureManagerInsertError,
    ControlMeasureManagerGetError,
    ControlMeasureManagerUpdateError,
    ControlMeasureManagerDeleteError,
    ControlMeasureManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

control_measure_blueprint = APIBlueprint('control_measure', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@control_measure_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.add')
@control_measure_blueprint.validate(build_write_schema(IsmsControlMeasure.SCHEMA))
@handle_route_errors("while creating the ControlMeasure")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerInsertError: IsmsManagerErrorMessage.INSERT,
    ControlMeasureManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
}))
def insert_isms_control_measure(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsControlMeasure into the database

    Args:
        data (IsmsControlMeasure.SCHEMA): Data of the IsmsControlMeasure which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert or the read-back of the created ControlMeasure fails, 500 when
            the created ControlMeasure cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsControlMeasure and its public_id
    """
    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    # The validated payload is written straight to the collection, so the SoA answer is normalised
    # here: the schema accepts null and a null is an empty cell in the report, not a third state
    result_id: int = control_measure_manager.insert_item(IsmsControlMeasure.normalize_is_applicable(data))

    created_control_measure: dict[str, Any] = require_created_item(
        control_measure_manager.get_item(result_id, as_dict=True), CONTROL_MEASURE_LABEL,
    )

    return InsertSingleResponse(created_control_measure, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@control_measure_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.view')
@control_measure_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving ControlMeasures")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_control_measures(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsControlMeasures

    Args:
        params (CollectionParameters): Filter for requested IsmsControlMeasures
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsControlMeasures matching the CollectionParameters
    """
    body: bool = request_wants_body()

    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

    iteration_result: IterationResult[IsmsControlMeasure] = control_measure_manager.iterate_items(builder_params)
    control_measures_list = [IsmsControlMeasure.to_json(control_measure) for control_measure
                              in iteration_result.results]

    api_response = GetMultiResponse(control_measures_list,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    body)

    return api_response.make_response()


@control_measure_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.view')
@handle_route_errors("while retrieving the ControlMeasure with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_control_measure(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsControlMeasure
    """
    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    requested_control_measure = get_item_or_404(control_measure_manager, public_id,
                                                f"The ControlMeasure with ID:{public_id} was not found!")

    return GetSingleResponse(requested_control_measure, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@control_measure_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.edit')
@control_measure_blueprint.validate(build_write_schema(IsmsControlMeasure.SCHEMA))
@handle_route_errors("while updating the ControlMeasure with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerGetError: IsmsManagerErrorMessage.GET,
    ControlMeasureManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
}))
def update_isms_control_measure(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure which should be updated
        data (IsmsControlMeasure.SCHEMA): New IsmsControlMeasure data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsControlMeasure
    """
    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    get_item_or_404(control_measure_manager, public_id,
                    f"The ControlMeasure with ID:{public_id} was not found!", as_dict=False)

    # The URL owns the identity: a body public_id would otherwise be $set onto the document

    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_item_from_payload(control_measure_manager, public_id, IsmsControlMeasure, data)

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@control_measure_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.delete')
@handle_route_errors("while deleting the ControlMeasure with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerDeleteError: IsmsManagerErrorMessage.DELETE,
    ControlMeasureManagerGetError: IsmsManagerErrorMessage.GET,
}))
def delete_isms_control_measure(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsControlMeasure data
    """
    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    to_delete_control_measure = get_item_or_404(control_measure_manager, public_id,
                                                f"The ControlMeasure with ID:{public_id} was not found!")

    if control_measure_manager.is_control_measure_used(public_id):
        abort(400, f"ControlMeasure with ID:{public_id} is not deletable while used by ControlMeasureAssignments!")

    control_measure_manager.delete_item(public_id)

    return DeleteSingleResponse(to_delete_control_measure).make_response()


@control_measure_blueprint.route('/delete/<string:public_ids>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.delete')
@handle_route_errors("while bulk-deleting ControlMeasures")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_LABEL, {
    ControlMeasureManagerGetError: IsmsManagerErrorMessage.BULK_USAGE,
    ControlMeasureManagerDeleteError: IsmsManagerErrorMessage.BULK_DELETE,
}))
def delete_many_isms_control_measures(public_ids: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to bulk-delete IsmsControlMeasures by a comma-separated id list

    A ControlMeasure can only be deleted while it is not referenced by any IsmsControlMeasureAssignment
    (mirroring the single-delete guard, since deleting it would strip the control out of a
    RiskAssessment's treatment plan). This bulk variant is partial by design: every requested
    ControlMeasure that is still referenced is left untouched and reported back, while the unused ones
    are deleted. Non-existent ids are silently ignored. The used-check runs as a single grouped query
    for the whole batch

    Args:
        public_ids (str): Comma-separated IsmsControlMeasure public_ids to delete
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: {'successfully': [deleted ids], 'in_use': [skipped ids still referenced]}
    """
    control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                   request_user)

    requested_ids: list[int] = extract_public_ids(public_ids)

    # Partition the whole batch in one grouped query: ids still referenced by an assignment are
    # kept (deleting them would orphan a RiskAssessment's treatment plan)
    in_use_ids: set[int] = control_measure_manager.get_used_control_measure_ids(requested_ids)

    payload: dict[str, list[int]] = bulk_delete_reporting_in_use(
        control_measure_manager, requested_ids, in_use_ids
    )

    return DefaultResponse(payload).make_response()
