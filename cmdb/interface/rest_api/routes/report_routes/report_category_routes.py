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
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.report_categories_manager import (
    ReportCategoriesManagerInsertError,
    ReportCategoriesManagerGetError,
    ReportCategoriesManagerDeleteError,
    ReportCategoriesManagerIterationError,
    ReportCategoriesManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

report_categories_blueprint = APIBlueprint('report_categories', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@report_categories_blueprint.route('/', methods=['POST'])
@report_categories_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_cmdb_report_category(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbReportCategory into the database

    Args:
        data (CmdbReportCategory.SCHEMA): Data of the CmdbReportCategory which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The public_id of the created CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                                ManagerType.REPORT_CATEGORIES,
                                                                                request_user)

        # It is not possible to create a predefined CmdbReportCategory
        #TODO: FIX in Frontend (do not send the public_id)
        params['public_id'] = report_categories_manager.get_next_public_id(inc_id=True)
        params['predefined'] = False

        new_report_category_id = report_categories_manager.insert_item(params)

        return DefaultResponse(new_report_category_id).make_response()
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
def get_cmdb_report_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbReportCategory

    Args:
        public_id (int): public_id of the CmdbReportCategory
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The requested CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)

        report_category = report_categories_manager.get_item(public_id, as_dict=True)

        if report_category:
            return DefaultResponse(report_category).make_response()

        abort(404, f"The ReportCategory with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[get_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ReportCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ReportCategory with ID: {public_id}!")


@report_categories_blueprint.route('/', methods=['GET', 'HEAD'])
@report_categories_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_cmdb_report_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbReportCategories

    Args:
        params (CollectionParameters): Filter for requested CmdbReportCategories
        request_user (CmdbUser): User requesting this data

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
    except ReportCategoriesManagerIterationError as err:
        LOGGER.error("[get_cmdb_report_categories] ReportCategoriesManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ReportCategories from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_report_categories] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ReportCategories!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@report_categories_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@report_categories_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_cmdb_report_category(public_id: int, params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbReportCategory

    Args:
        public_id (int): public_id of the CmdbReportCategory which should be updated
        data (CmdbReportCategory.SCHEMA): New CmdbReportCategory data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)
        params['public_id'] = int(params['public_id'])
        params['predefined'] = params['predefined'] in ["True", "true"]

        current_category = report_categories_manager.get_item(public_id)

        if current_category:
            report_categories_manager.update_item(public_id, params)

            return UpdateSingleResponse(params).make_response()

        abort(404, f"The ReportCategory with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[update_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ReportCategory with ID: {public_id} from the database!")
    except ReportCategoriesManagerUpdateError as err:
        LOGGER.error("[update_cmdb_report_category] ReportCategoriesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ReportCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[update_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ReportCategory with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@report_categories_blueprint.route('/<int:public_id>/', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def delete_cmdb_report_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes the CmdbReportCategory with the given public_id
    
    Args:
        public_id (int): public_id of CmdbReportCategory which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbReportCategory
    """
    try:
        report_categories_manager: ReportCategoriesManager = ManagerProvider.get_manager(
                                                                            ManagerType.REPORT_CATEGORIES,
                                                                            request_user)


        to_delete_report_category: CmdbReportCategory = report_categories_manager.get_item(public_id)

        if not to_delete_report_category:
            abort(404, f"The ReportCategory with ID:{public_id} was not found!")

        if to_delete_report_category.predefined:
            abort(405, "Deletion of a predefined ReportCategory is not allowed!")

        # It is not possbile to delete a category if a report is using it
        reports_wtih_category = report_categories_manager.get_many_from_other_collection(CmdbReport.COLLECTION,
                                                                                        report_category_id=public_id)

        if len(reports_wtih_category) > 0:
            abort(403, f"ReportCategory with ID: {public_id} can not be deleted because it is used by Reports!")

        ack = report_categories_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except ReportCategoriesManagerGetError as err:
        LOGGER.error("[delete_cmdb_report_category] ReportCategoriesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ReportCategory with ID: {public_id} from the database!")
    except ReportCategoriesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_report_category] ReportCategoriesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ReportCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_report_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ReportCategory with ID: {public_id}!")
