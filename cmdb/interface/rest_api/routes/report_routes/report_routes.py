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

Exposes the report CRUD surface (create / read / list / update / delete), a per-type count and a
``run`` route that executes a stored report query and returns the matching CmdbObjects. Every route
requires ApiLevel.ADMIN access.

The handlers stay thin orchestrators: the domain logic - payload sanitising / normalisation, the
foreign-key and Ref-Section-Field guards, building the persisted report query and the safe evaluation
of a stored query - lives in ``report_helper``; the request / document string keys, the write whitelist
and the repeated abort messages in ``report_constants``. The two server-owned keys are never taken
from a client: 'public_id' comes from the URL and 'predefined' is set by the system (create forces it
False, update carries the stored value over), and 'report_query' is always rebuilt from 'conditions'.
Business-rule rejections (missing or malformed parameters, an unresolved category or type, a
referenced Ref-Section-Field, a malformed query flag) abort with HTTP 400; a missing report with 404;
unexpected failures with 500.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ReportsManager,
    ObjectsManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse, UpdateSingleResponse
from cmdb.framework.results import IterationResult

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    PREVIEW_LIMIT,
    PREVIEW_PARAM,
    REPORT_CONDITIONS_INVALID_MSG,
    REPORT_RETRIEVE_FAILED_MSG,
    ReportKey,
)
from cmdb.interface.rest_api.routes.report_routes.report_helper import (
    build_report_create_payload,
    build_report_update_payload,
    load_report_or_404,
    parse_boolean_param,
    resolve_report_query,
)

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.mongo_query_builder import MongoDBQueryBuilderError
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

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@reports_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@reports_blueprint.parse_request_parameters()
def create_cmdb_report(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates a CmdbReport in the database

    Sanitises and normalises the request parameters, verifies the report's CmdbReportCategory and
    CmdbType, rejects any referenced Ref-Section-Field and builds the persisted report query before
    inserting the report. 'predefined' is forced to False, so a client can never create a predefined
    CmdbReport

    Args:
        params (dict[str, Any]): CmdbReport request parameters
        request_user (CmdbUser): User which is creating the CmdbReport

    Returns:
        DefaultResponse: public_id of the created CmdbReport

    Raises:
        HTTPException: 400 on missing / malformed parameters, an unresolved category or type, a
                       referenced Ref-Section-Field, an unbuildable condition tree or a failed
                       insert; 500 on an unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        payload: dict[str, Any] = build_report_create_payload(reports_manager, params)

        new_report_id: int = reports_manager.insert_item(payload)

        return DefaultResponse(new_report_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except MongoDBQueryBuilderError as err:
        LOGGER.error("[create_cmdb_report] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, REPORT_CONDITIONS_INVALID_MSG.format(reason=err))
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

    Returns:
        DefaultResponse: The requested CmdbReport

    Raises:
        HTTPException: 404 when the CmdbReport does not exist, 400 on a failed retrieval, 500 on an
                       unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        requested_report: dict[str, Any] = load_report_or_404(reports_manager, public_id)

        return DefaultResponse(requested_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[get_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, REPORT_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except Exception as err:
        LOGGER.error("[get_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Report with ID: {public_id}!")


@reports_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@reports_blueprint.parse_collection_parameters()
def get_cmdb_reports(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns all CmdbReports based on the params

    Args:
        params (CollectionParameters): Parameters to identify documents in database
        request_user (CmdbUser): User which is requesting the CmdbReports

    Returns:
        GetMultiResponse: All CmdbReports considering the params

    Raises:
        HTTPException: 400 on a failed iteration, 500 on an unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        builder_params: BuilderParameters = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbReport] = reports_manager.iterate_items(builder_params)
        report_list: list[dict[str, Any]] = [CmdbReport.to_json(report_) for report_ in iteration_result.results]

        api_response = GetMultiResponse(report_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerIterationError as err:
        LOGGER.error("[get_cmdb_reports] ReportsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Reports from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_reports] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Reports!")


@reports_blueprint.route('/<int:type_id>/count_reports_of_type', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def count_cmdb_reports_of_type(type_id: int, request_user: CmdbUser) -> Response:
    """
    Returns the number of CmdbReports in the database for the CmdbType with the given public_id

    The path parameter is the public_id of a CmdbType, not of a CmdbReport - the frontend asks for this
    count before deleting a CmdbType, whose delete route refuses while reports still use it

    Args:
        type_id (int): public_id of the CmdbType whose CmdbReports should be counted
        request_user (CmdbUser): CmdbUser which is requesting this data

    Returns:
        DefaultResponse: Number of CmdbReports for the CmdbType

    Raises:
        HTTPException: 400 on a failed count, 500 on an unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        reports_count: int = reports_manager.count_documents({ReportKey.TYPE_ID: type_id})

        return DefaultResponse(reports_count).make_response()
    # No HTTPException re-raise arm here: nothing inside the try aborts (the route neither loads a
    # document nor validates a payload), so such an arm would be dead code
    # count_documents is a BaseManager primitive, so a failure arrives as BaseManagerGetError - the
    # manager-specific error is never raised here (the same arm delete_cmdb_type uses for this count)
    except BaseManagerGetError as err:
        LOGGER.error("[count_cmdb_reports_of_type] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the number of Reports for Type with ID: {type_id}!")
    except Exception as err:
        LOGGER.error("[count_cmdb_reports_of_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
              f"An internal server error occured while retrieving the number of Reports for Type with ID: {type_id}!"
             )


@reports_blueprint.route('/run/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def run_cmdb_report_query(public_id: int, request_user: CmdbUser) -> Response:
    """
    Runs a CmdbReport's stored query and returns the matching CmdbObjects

    Evaluates the report's persisted query back into a Mongo query and iterates the objects. With
    ``?preview=true`` the result set is capped at PREVIEW_LIMIT rows database-side; otherwise the full
    result set is returned. A report whose query carries no conditions - or which stores no query at
    all - returns an empty result

    Args:
        public_id (int): public_id of the CmdbReport to run
        request_user (CmdbUser): CmdbUser which is requesting this data

    Returns:
        DefaultResponse: The query result (capped to a small preview set when ?preview=true)

    Raises:
        HTTPException: 400 on a malformed 'preview' flag or a failed retrieval; 404 when the report
                       does not exist; 500 on an unevaluable stored query or an unexpected failure
    """
    try:
        preview_mode: bool = parse_boolean_param(request.args.get(PREVIEW_PARAM, default='false'), PREVIEW_PARAM)

        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        requested_report: dict[str, Any] = load_report_or_404(reports_manager, public_id)

        report_query: dict[str, Any] = resolve_report_query(requested_report, public_id)

        result: Any = {}

        # Only execute the report if there are conditions
        if len(report_query) > 0:
            # Preview mode caps the result set at the database level (limit=0 means no limit)
            limit: int = PREVIEW_LIMIT if preview_mode else 0
            builder_params: BuilderParameters = BuilderParameters(criteria=report_query, limit=limit)

            result = objects_manager.iterate(builder_params).results

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[run_cmdb_report_query] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, REPORT_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except Exception as err:
        LOGGER.error("[run_cmdb_report_query] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while running the Report with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@reports_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@reports_blueprint.parse_request_parameters()
def update_cmdb_report(public_id: int, params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Updates a CmdbReport

    Sanitises and normalises the request parameters, pins the identity to the URL public_id and
    'predefined' to the stored value, verifies both foreign keys, rejects any referenced
    Ref-Section-Field and rebuilds the persisted report query before updating

    The response is the stored document with the written payload merged over it. The update is a
    ``$set`` of that payload, so the merge is what a re-read would return - without paying for the
    second query

    Args:
        public_id (int): public_id of CmdbReport which should be updated
        params (dict[str, Any]): updated CmdbReport parameters
        request_user (CmdbUser): CmdbUser which is requesting this update

    Returns:
        UpdateSingleResponse: The updated CmdbReport as a dict

    Raises:
        HTTPException: 400 on missing / malformed parameters, an unresolved category or type, a
                       referenced Ref-Section-Field or a failed retrieval / update; 404 when the report
                       does not exist; 500 on an unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        current_report: dict[str, Any] = load_report_or_404(reports_manager, public_id)

        payload: dict[str, Any] = build_report_update_payload(reports_manager, params, public_id, current_report)

        reports_manager.update_item(public_id, payload)

        return UpdateSingleResponse({**current_report, **payload}).make_response()
    except HTTPException as http_err:
        raise http_err
    except MongoDBQueryBuilderError as err:
        LOGGER.error("[update_cmdb_report] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, REPORT_CONDITIONS_INVALID_MSG.format(reason=err))
    except ReportsManagerGetError as err:
        LOGGER.error("[update_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, REPORT_RETRIEVE_FAILED_MSG.format(public_id=public_id))
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
def delete_cmdb_report(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes the CmdbReport with the given public_id

    Args:
        public_id (int): public_id of CmdbReport which should be deleted
        request_user (CmdbUser): User which is requesting the deletion

    Returns:
        DefaultResponse: True if deletion was successful, else False

    Raises:
        HTTPException: 404 when the CmdbReport does not exist, 400 on a failed retrieval / deletion,
                       500 on an unexpected failure
    """
    try:
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        # Only an existence check is needed here, so the raw document is enough (no model build)
        load_report_or_404(reports_manager, public_id)

        ack: bool = reports_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportsManagerGetError as err:
        LOGGER.error("[delete_cmdb_report] ReportsManagerGetError: %s", err, exc_info=True)
        abort(400, REPORT_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except ReportsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_report] ReportsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Report with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Report with ID: {public_id}!")
