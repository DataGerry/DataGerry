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
Implementation of all CmdbReport API routes
"""
import re
from logging import Logger, getLogger
import json
from typing import Any
from datetime import datetime
from ast import literal_eval
from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDBQueryBuilder
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ReportsManager,
    ObjectsManager,
)

from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse, UpdateSingleResponse
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.reports_manager import (
    ReportsManagerInsertError,
    ReportsManagerGetError,
    ReportsManagerIterationError,
    ReportsManagerUpdateError,
    ReportsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

reports_blueprint = APIBlueprint('reports', __name__)

DATETIME_PATTERN = r"datetime\.datetime\((.*?)\)"

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@reports_blueprint.route('/', methods=['POST'])
@reports_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_cmdb_report(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates a CmdbReport in the database

    Args:
        params (dict): CmdbReport parameters

    Returns:
        DefaultResponse: public_id of the created CmdbReport
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        params['report_category_id'] = int(params['report_category_id'])
        params['type_id'] = int(params['type_id'])
        params['predefined'] = params['predefined'] in ["True", "true"]
        params['mds_mode'] = params['mds_mode'] if params['mds_mode'] in [MdsMode.ROWS,
                                                                          MdsMode.COLUMNS] else MdsMode.ROWS
        params['conditions'] = json.loads(params['conditions'])
        params['selected_fields'] = literal_eval(params['selected_fields'])

        report_type = reports_manager.get_one_from_other_collection(CmdbType.COLLECTION, params['type_id'])
        params['report_query'] = {'data': str(MongoDBQueryBuilder(params['conditions'],
                                                                  CmdbType.from_data(report_type)).build())}

        new_report_id = reports_manager.insert_item(params)

        return DefaultResponse(new_report_id).make_response()
    except ReportsManagerInsertError as err:
        LOGGER.error("[create_cmdb_report] ReportsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Report in the database!")
    except Exception as err:
        LOGGER.error("[create_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Report!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@reports_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_cmdb_report(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the CmdbReport with the given public_id
    
    Args:
        public_id (int): public_id of CmdbReport which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbReport
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        requested_report = reports_manager.get_item(public_id, as_dict=True)

        if not requested_report:
            abort(404, f"The Report with ID:{public_id} was not found!")

        return DefaultResponse(requested_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[get_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Report with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Report with ID: {public_id}!")


@reports_blueprint.route('/', methods=['GET', 'HEAD'])
@reports_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_cmdb_reports(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns all CmdbReports based on the params

    Args:
        params (CollectionParameters): Parameters to identify documents in database
        request_user (CmdbUser): User which is requesting the CmdbReports

    Returns:
        GetMultiResponse: All CmdbReports considering the params
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        builder_params: BuilderParameters = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbReport] = reports_manager.iterate_items(builder_params)
        report_list: list[dict] = [report_.__dict__ for report_ in iteration_result.results]

        api_response = GetMultiResponse(report_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except ReportsManagerIterationError as err:
        LOGGER.error("[get_cmdb_reports] ImpactManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Reports from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_reports] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Reports!")


#TODO: DOCUMENT-API-FIX
@reports_blueprint.route('/<int:public_id>/count_reports_of_type', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def count_cmdb_reports_of_type(public_id: int, request_user: CmdbUser):
    """
    Return the number of reports in der database with the given public_id of a CmdbType

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): CmdbUser which is requesting this data

    Returns:
        DefaultResponse: Number of CmdbReports for CmdbType
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        reports_count = reports_manager.count_items({'type_id':public_id})

        return DefaultResponse(reports_count).make_response()
    except ReportsManagerGetError as err:
        LOGGER.error("[count_cmdb_reports_of_type] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the number of Reports for Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[count_cmdb_reports_of_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
              f"An internal server error occured while retrieving the number of Reports for Type with ID: {public_id}!"
             )


@reports_blueprint.route('/run/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def run_cmdb_report_query(public_id: int, request_user: CmdbUser):
    """
    Returns the result of the query of the CmdbReport

    Args:
        params (int): public_id of the CmdbReport
        request_user (CmdbUser): CmdbUser which is requesting this data

    Returns:
        DefaultResponse: Dict of the query result
    """
    try:
        preview_mode: bool = request.args.get("preview", default="false").lower() == "true"

        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        requested_report: dict = reports_manager.get_item(public_id, as_dict=True)
        # LOGGER.debug(f"requested_report: {requested_report}")

        if not requested_report:
            abort(404, f"The Report with ID:{public_id} was not found!")

        query_str: str = requested_report['report_query']['data']

        processed_query_string = re.sub(DATETIME_PATTERN,
                                        replace_datetime,
                                        query_str.replace("datetime.datetime", "datetime"))

        safe_globals = {"datetime": datetime}
        #pylint: disable=W0123
        report_query = eval(processed_query_string, safe_globals)

        result = {}

        # Only execute the report if there are conditions
        if len(report_query) > 0:
            builder_params = BuilderParameters(criteria=report_query)

            result = objects_manager.iterate(builder_params).results

            # Only show maximum 2 elements if preview_mode
            if preview_mode:
                result = result[:2]

        # LOGGER.debug(f"report result: {result}")
        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[run_cmdb_report_query] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Report with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[run_cmdb_report_query] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while running the Report with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@reports_blueprint.route('/<int:public_id>', methods=['PUT','PATCH'])
@reports_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_cmdb_report(public_id: int, params: dict, request_user: CmdbUser):
    """
    Updates a CmdbReport

    Args:
        public_id (int): public_id of CmdbReport which should be updated
        params (dict): updated CmdbReport parameters
        request_user (CmdbUser): CmdbUser which is requesting this update

    Returns:
        UpdateSingleResponse: The updated CmdbReport as a dict
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        params['public_id'] = int(public_id)
        params['report_category_id'] = int(params['report_category_id'])
        params['type_id'] = int(params['type_id'])
        params['predefined'] = params['predefined'] in ["True", "true"]
        params['conditions'] = json.loads(params['conditions'])
        params['selected_fields'] = literal_eval(params['selected_fields'])
        params['mds_mode'] = params['mds_mode'] if params['mds_mode'] in [MdsMode.ROWS,
                                                                          MdsMode.COLUMNS] else MdsMode.ROWS

        current_report = reports_manager.get_item(public_id, as_dict=True)

        if not current_report:
            abort(404, f"The Report with ID:{public_id} was not found!")

        report_type = reports_manager.get_one_from_other_collection(CmdbType.COLLECTION, params['type_id'])
        params['report_query'] = {'data': str(MongoDBQueryBuilder(params['conditions'],
                                                                    CmdbType.from_data(report_type)).build())}

        reports_manager.update_item(public_id, params)
        current_report = reports_manager.get_item(public_id, as_dict=True)

        if not current_report:
            abort(404, f"The updated Report with ID:{public_id} was not found!")

        return UpdateSingleResponse(current_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[update_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Report with ID: {public_id} from the database!")
    except ReportsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_report] ReportsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Report with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Report with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@reports_blueprint.route('/<int:public_id>/', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def delete_cmdb_report(public_id: int, request_user: CmdbUser):
    """
    Deletes the CmdbReport with the given public_id
    
    Args:
        public_id (int): public_id of CmdbReport which should be retrieved
        request_user (CmdbUser): User which is requesting the deletion

    Returns:
        DefaultResponse: True if deletion was successful, else False
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        report_instance = reports_manager.get_item(public_id)

        if not report_instance:
            abort(404, f"The Report with ID:{public_id} was not found!")

        ack = reports_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[delete_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Report with ID: {public_id} from the database!")
    except ReportsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_report] ReportsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Report with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Report with ID: {public_id}!")

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

def replace_datetime(match: re.Match) -> str:
    """
    Replaces a regex match containing datetime arguments with a Python datetime object

    Args:
        match (re.Match): A regular expression match object containing 
                          a string of datetime arguments (e.g., "2025, 11, 26, 0, 0").

    Returns:
        str: A string representation (repr) of the evaluated datetime object.

    Notes:
        - This function expects the match to contain arguments suitable for datetime().
        - The returned value is the repr of the datetime object, 
          which can be used in source code or serialization.
    """
    args = match.group(1)

    #pylint: disable=W0123
    return repr(eval(f"datetime({args})"))
