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
Implementation of all API routes for CmdbReportCategories

A CmdbReportCategory groups CmdbReports.

Every route requires ApiLevel.ADMIN access and a ``ReportRight``: the reads VIEW, create ADD, update
EDIT, delete DELETE. Report categories have no right family of their own, so they reuse the report
rights - the same pairing the frontend already gates its category screens on (see
report-category-routing.module.ts and category-overview.component.html).

The write payload is the JSON body, validated against ``CmdbReportCategory.SCHEMA`` before the handler
runs: 'name' must be a non-empty string, and the Cerberus validator is built with purge_unknown, so an
unknown key is dropped rather than refused. The validated document still passes through
report_category_helper, which trims 'name' and re-applies the two server-owned keys - 'public_id'
comes from the URL and 'predefined' is set by the system, which is what makes the seeded 'General'
category read-only. Deletion is additionally refused while CmdbReports still reference the category
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import ReportCategoriesManager

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse, UpdateSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.models.user_model import CmdbUser
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.report_categories_manager import (
    ReportCategoriesManagerInsertError,
    ReportCategoriesManagerGetError,
    ReportCategoriesManagerDeleteError,
    ReportCategoriesManagerIterationError,
    ReportCategoriesManagerUpdateError,
)

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    CATEGORY_RETRIEVE_FAILED_MSG,
    ReportCategoryAction,
    ReportCategoryKey,
    ReportRight,
)
from cmdb.interface.rest_api.routes.report_routes.report_category_helper import (
    abort_if_category_in_use,
    abort_if_predefined,
    build_category_update_payload,
    load_category_or_404,
    normalize_category_params,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

report_categories_blueprint = APIBlueprint('report_categories', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@report_categories_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@report_categories_blueprint.protect(auth=True, right=ReportRight.ADD.value)
@report_categories_blueprint.validate(CmdbReportCategory.SCHEMA)
def create_cmdb_report_category(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbReportCategory into the database

    Args:
        data (dict[str, Any]): Schema-validated body of the CmdbReportCategory which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a body failing the schema, without a usable 'name', or a failed insert;
                       403 without the report ADD right; 500 on an unexpected failure

    Returns:
        DefaultResponse: The public_id of the created CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                                ManagerType.REPORT_CATEGORIES,
                                                                                request_user)

        # Only 'name' survives the whitelist, so a client-sent public_id can never reach the insert
        # (which assigns the next one) and 'predefined' stays system-controlled: a client can never
        # create a predefined CmdbReportCategory
        payload: dict[str, Any] = normalize_category_params(data)
        payload[ReportCategoryKey.PREDEFINED] = False

        new_report_category_id: int = report_categories_manager.insert_item(payload)

        return DefaultResponse(new_report_category_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerInsertError as err:
        LOGGER.error("[create_cmdb_report_category] ReportCategoriesManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new ReportCategory into the database!")
    except Exception as err:
        LOGGER.error("[create_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ReportCategory!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@report_categories_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@report_categories_blueprint.protect(auth=True, right=ReportRight.VIEW.value)
def get_cmdb_report_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbReportCategory

    Args:
        public_id (int): public_id of the CmdbReportCategory
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 when the CmdbReportCategory does not exist, 400 on a failed retrieval,
                       403 without the report VIEW right, 500 on an unexpected failure

    Returns:
        DefaultResponse: The requested CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)

        report_category: dict[str, Any] = load_category_or_404(report_categories_manager, public_id, as_dict=True)

        return DefaultResponse(report_category).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[get_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, CATEGORY_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except Exception as err:
        LOGGER.error("[get_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ReportCategory with ID: {public_id}!")


@report_categories_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@report_categories_blueprint.protect(auth=True, right=ReportRight.VIEW.value)
@report_categories_blueprint.parse_collection_parameters()
def get_cmdb_report_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbReportCategories

    Args:
        params (CollectionParameters): Filter for requested CmdbReportCategories
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a failed iteration, 403 without the report VIEW right, 500 on an
                       unexpected failure

    Returns:
        GetMultiResponse: All the CmdbReportCategories matching the CollectionParameters
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                                ManagerType.REPORT_CATEGORIES,
                                                                                request_user)

        builder_params: BuilderParameters = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbReportCategory] = report_categories_manager.iterate_items(builder_params)
        report_category_list: list[dict] = [CmdbReportCategory.to_json(report_category) for report_category
                                            in iteration_result.results]

        api_response = GetMultiResponse(report_category_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerIterationError as err:
        LOGGER.error("[get_cmdb_report_categories] ReportCategoriesManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ReportCategories from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_report_categories] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ReportCategories!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@report_categories_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@report_categories_blueprint.protect(auth=True, right=ReportRight.EDIT.value)
@report_categories_blueprint.validate(CmdbReportCategory.SCHEMA)
def update_cmdb_report_category(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbReportCategory

    Args:
        public_id (int): public_id of the CmdbReportCategory which should be updated
        data (dict[str, Any]): Schema-validated body carrying the new CmdbReportCategory data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a body failing the schema, without a usable 'name', or a failed
                       retrieval / update; 403 when the CmdbReportCategory is predefined or the
                       report EDIT right is missing; 404 when it does not exist; 500 on an
                       unexpected failure

    Returns:
        UpdateSingleResponse: The new data of the CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)

        current_category: CmdbReportCategory = load_category_or_404(report_categories_manager, public_id)

        # A predefined CmdbReportCategory is system-owned and read-only - renaming it would detach it
        # from the name the first-boot seeder identifies it by
        abort_if_predefined(current_category, ReportCategoryAction.UPDATED)

        payload: dict[str, Any] = build_category_update_payload(data, public_id, current_category)

        report_categories_manager.update_item(public_id, payload)

        return UpdateSingleResponse(payload).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[update_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, CATEGORY_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except ReportCategoriesManagerUpdateError as err:
        LOGGER.error("[update_cmdb_report_category] ReportCategoriesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ReportCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[update_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ReportCategory with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@report_categories_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@report_categories_blueprint.protect(auth=True, right=ReportRight.DELETE.value)
def delete_cmdb_report_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes the CmdbReportCategory with the given public_id

    Args:
        public_id (int): public_id of the CmdbReportCategory which should be deleted
        request_user (CmdbUser): User which is requesting the deletion

    Raises:
        HTTPException: 403 when the CmdbReportCategory is predefined, still used by CmdbReports, or
                       the report DELETE right is missing; 404 when it does not exist; 400 on a
                       failed retrieval / deletion; 500 on an unexpected failure

    Returns:
        DefaultResponse: True if the CmdbReportCategory was deleted
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)

        to_delete_report_category: CmdbReportCategory = load_category_or_404(report_categories_manager, public_id)

        abort_if_predefined(to_delete_report_category, ReportCategoryAction.DELETED)

        # It is not possible to delete a category if a report is using it
        abort_if_category_in_use(report_categories_manager, public_id)

        ack: bool = report_categories_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[delete_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, CATEGORY_RETRIEVE_FAILED_MSG.format(public_id=public_id))
    except ReportCategoriesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_report_category] ReportCategoriesManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ReportCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ReportCategory with ID: {public_id}!")
