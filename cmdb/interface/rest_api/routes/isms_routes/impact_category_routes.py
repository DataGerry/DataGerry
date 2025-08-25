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
Implementation of all API routes for IsmsImpactCategories
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ImpactCategoryManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsImpactCategory

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
    DefaultResponse,
)

from cmdb.errors.manager.impact_category_manager import (
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerGetError,
    ImpactCategoryManagerUpdateError,
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

impact_category_blueprint = APIBlueprint('impact_categories', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@impact_category_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.add')
@impact_category_blueprint.validate(IsmsImpactCategory.SCHEMA)
def insert_isms_impact_category(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsImpactCategory into the database

    Args:
        data (IsmsImpactCategory.SCHEMA): Data of the IsmsImpactCategory which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsImpactCategory and its public_id
    """
    try:
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        result_id: int = impact_category_manager.create_with_follow_up(data)

        created_impact: dict[str, Any] = impact_category_manager.get_item(result_id, as_dict=True)

        if created_impact:
            return InsertSingleResponse(created_impact, result_id).make_response()

        abort(404, "Could not retrieve the created ImpactCategory from the database!")
    except HTTPException as http_err:
        raise http_err
    except ImpactCategoryManagerInsertError as err:
        LOGGER.error("[insert_isms_impact_category] ImpactCategoryManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new ImpactCategory in the database!")
    except ImpactCategoryManagerGetError as err:
        LOGGER.error("[insert_isms_impact_category] ImpactCategoryManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ImpactCategory from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_impact_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ImpactCategory!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@impact_category_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.view')
@impact_category_blueprint.parse_collection_parameters()
def get_isms_impact_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsImpactCategories

    Args:
        params (CollectionParameters): Filter for requested IsmsImpactCategories
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsImpactCategories matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsImpactCategory] = impact_category_manager.iterate_items(builder_params)
        impact_categories_list = [IsmsImpactCategory.to_json(impact_category) for impact_category
                                  in iteration_result.results]

        api_response = GetMultiResponse(impact_categories_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ImpactCategoryManagerIterationError as err:
        LOGGER.error("[get_isms_impact_categories] ImpactCategoryManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ImpactCategories from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_impact_categories] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ImpactCategories!")


@impact_category_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.view')
def get_isms_impact_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsImpactCategory

    Args:
        public_id (int): public_id of the IsmsImpactCategory
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsImpactCategory
    """
    try:
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        requested_impact = impact_category_manager.get_item(public_id, as_dict=True)

        if requested_impact:
            return GetSingleResponse(requested_impact, body = request.method == 'HEAD').make_response()

        abort(404, f"The ImpactCategory with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ImpactCategoryManagerGetError as err:
        LOGGER.error("[get_isms_impact_category] ImpactCategoryManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ImpactCategory with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_impact_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ImpactCategory with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@impact_category_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.edit')
@impact_category_blueprint.validate(IsmsImpactCategory.SCHEMA)
def update_isms_impact_category(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsImpactCategory

    Args:
        public_id (int): public_id of the IsmsImpactCategory which should be updated
        data (IsmsImpactCategory.SCHEMA): New IsmsImpactCategory data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsImpactCategory
    """
    try:
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        to_update_impact = impact_category_manager.get_item(public_id)

        if not to_update_impact:
            abort(404, f"The ImpactCategory with ID:{public_id} was not found!")

        impact_category_manager.update_item(public_id, IsmsImpactCategory.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactCategoryManagerGetError as err:
        LOGGER.error("[update_isms_impact_category] ImpactCategoryManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ImpactCategory with ID: {public_id} from the database!")
    except ImpactCategoryManagerUpdateError as err:
        LOGGER.error("[update_isms_impact_category] ImpactCategoryManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ImpactCategory with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_impact_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ImpactCategory with ID: {public_id}!")


@impact_category_blueprint.route('/multiple', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.edit')
def update_multiple_isms_impact_categories(request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update multiple IsmsImpactCategory records.

    Args:
        data (list of IsmsImpactCategory.SCHEMA): List of new IsmsImpactCategory data
        request_user (CmdbUser): User requesting this data

    Returns:
        dict: Summary of success and failures
    """
    try:
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        data = request.get_json()
        results = []

        for item in data:
            public_id = item.get("public_id")
            if not public_id:
                results.append({"public_id": None, "status": "failed", "message": "Missing public_id"})
                continue

            try:
                to_update_impact = impact_category_manager.get_item(public_id)

                if not to_update_impact:
                    results.append({
                        "public_id": public_id,
                        "status": "failed",
                        "message": f"ImpactCategory ID:{public_id} not found"
                    })
                    continue

                impact_category_manager.update_item(public_id, IsmsImpactCategory.from_data(item))

                results.append({"public_id": public_id, "status": "success"})
            except ImpactCategoryManagerGetError as err:
                LOGGER.error(
                    "[update_multiple_isms_impact_categories] ImpactCategoryManagerGetError: %s", err, exc_info=True
                )
                results.append({
                    "public_id": public_id,
                    "status": "failed",
                    "message": f"Failed to retrieve ImpactCategory ID: {public_id}"
                })
            except ImpactCategoryManagerUpdateError as err:
                LOGGER.error(
                    "[update_multiple_isms_impact_categories] ImpactCategoryManagerUpdateError: %s", err, exc_info=True
                )
                results.append({
                    "public_id": public_id,
                    "status": "failed",
                    "message": f"Failed to update ImpactCategory ID: {public_id}"
                })
            except Exception as err:
                LOGGER.error(
                    "[update_multiple_isms_impact_categories] Exception: %s. Type: %s", err, type(err), exc_info=True
                )
                results.append({
                    "public_id": public_id,
                    "status": "failed",
                    "message": "Internal server error"
                })

        return DefaultResponse(results).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_multiple_isms_impact_categories] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating multiple ImpactCategories!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@impact_category_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.delete')
def delete_isms_impact_category(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single IsmsImpactCategory

    Args:
        public_id (int): public_id of the IsmsImpactCategory which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsImpactCategory data
    """
    try:
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        to_delete_impact = impact_category_manager.get_item(public_id, as_dict=True)

        if not to_delete_impact:
            abort(404, f"The ImpactCategory with ID:{public_id} was not found!")

        impact_category_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_impact).make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactCategoryManagerDeleteError as err:
        LOGGER.error("[delete_isms_impact_category] ImpactCategoryManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ImpactCategory with ID:{public_id}!")
    except ImpactCategoryManagerGetError as err:
        LOGGER.error("[delete_isms_impact_category] ImpactCategoryManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ImpactCategory with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_impact_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ImpactCategory with ID: {public_id}!")
