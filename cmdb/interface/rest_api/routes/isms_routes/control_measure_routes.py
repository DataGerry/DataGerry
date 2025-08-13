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
Implementation of all API routes for the IsmsControlMeasures
"""
import logging
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ControlMeasureManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasure

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

from cmdb.errors.manager.control_measure_manager import (
    ControlMeasureManagerInsertError,
    ControlMeasureManagerGetError,
    ControlMeasureManagerUpdateError,
    ControlMeasureManagerDeleteError,
    ControlMeasureManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

control_measure_blueprint = APIBlueprint('control_measure', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@control_measure_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.add')
@control_measure_blueprint.validate(IsmsControlMeasure.SCHEMA)
def insert_isms_control_measure(data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsControlMeasure into the database

    Args:
        data (IsmsControlMeasure.SCHEMA): Data of the IsmsControlMeasure which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsControlMeasure and its public_id
    """
    try:
        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                       request_user)

        result_id: int = control_measure_manager.insert_item(data)

        created_control_measure: dict = control_measure_manager.get_item(result_id, as_dict=True)

        if created_control_measure:
            return InsertSingleResponse(created_control_measure, result_id).make_response()

        abort(404, "Could not retrieve the created ControlMeasure from the database!")
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureManagerInsertError as err:
        LOGGER.error("[insert_isms_control_measure] ControlMeasureManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new ControlMeasure in the database!")
    except ControlMeasureManagerGetError as err:
        LOGGER.error("[insert_isms_control_measure] ControlMeasureManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ControlMeasure from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_control_measure] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ControlMeasure!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@control_measure_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.view')
@control_measure_blueprint.parse_collection_parameters()
def get_isms_control_measures(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsControlMeasures

    Args:
        params (CollectionParameters): Filter for requested IsmsControlMeasures
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsControlMeasures matching the CollectionParameters
    """
    try:
        body: bool = request.method == 'HEAD'

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
    except ControlMeasureManagerIterationError as err:
        LOGGER.error("[get_isms_control_measures] ControlMeasureManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ControlMeasures from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_control_measures] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ControlMeasures!")


@control_measure_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.view')
def get_isms_control_measure(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsControlMeasure
    """
    try:
        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                       request_user)

        requested_control_measure = control_measure_manager.get_item(public_id, as_dict=True)

        if requested_control_measure:
            return GetSingleResponse(requested_control_measure, body = request.method == 'HEAD').make_response()

        abort(404, f"The ControlMeasure with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureManagerGetError as err:
        LOGGER.error("[get_isms_control_measure] ControlMeasureManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ControlMeasure with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_control_measure] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ControlMeasure with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@control_measure_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.edit')
@control_measure_blueprint.validate(IsmsControlMeasure.SCHEMA)
def update_isms_control_measure(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure which should be updated
        data (IsmsControlMeasure.SCHEMA): New IsmsControlMeasure data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsControlMeasure
    """
    try:
        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                       request_user)

        to_update_control_measure = control_measure_manager.get_item(public_id)

        if not to_update_control_measure:
            abort(404, f"The ControlMeasure with ID:{public_id} was not found!")

        control_measure_manager.update_item(public_id, IsmsControlMeasure.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureManagerGetError as err:
        LOGGER.error("[update_isms_control_measure] ControlMeasureManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ControlMeasure with ID: {public_id} from the database!")
    except ControlMeasureManagerUpdateError as err:
        LOGGER.error("[update_isms_control_measure] ControlMeasureManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ControlMeasure with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_control_measure] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ControlMeasure with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@control_measure_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_blueprint.protect(auth=True, right='base.isms.controlMeasure.delete')
def delete_isms_control_measure(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single IsmsControlMeasure

    Args:
        public_id (int): public_id of the IsmsControlMeasure which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsControlMeasure data
    """
    try:
        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE,
                                                                                       request_user)

        to_delete_control_measure = control_measure_manager.get_item(public_id, as_dict=True)

        if not to_delete_control_measure:
            abort(404, f"The ControlMeasure with ID:{public_id} was not found!")

        if control_measure_manager.is_control_measure_used(public_id):
            abort(400, f"ControlMeasure with ID:{public_id} is not deletable while used by ControlMeasureAssignments!")

        control_measure_manager.delete_item(public_id)

        return DeleteSingleResponse(to_delete_control_measure).make_response()
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureManagerDeleteError as err:
        LOGGER.error("[delete_isms_control_measure] ControlMeasureManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ControlMeasure with ID:{public_id}!")
    except ControlMeasureManagerGetError as err:
        LOGGER.error("[delete_isms_control_measure] ControlMeasureManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ControlMeasure with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_control_measure] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ControlMeasure with ID: {public_id}!")
