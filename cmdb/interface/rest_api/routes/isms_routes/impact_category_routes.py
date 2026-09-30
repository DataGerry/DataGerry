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
Implementation of all API routes for IsmsImpactCategories
"""
from logging import Logger, getLogger
from typing import Any
from flask import request
from werkzeug import Response

from cmdb.manager import ImpactCategoryManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsImpactCategory

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
    update_multiple_items,
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    IMPACT_CATEGORY_LABEL,
    IsmsManagerErrorMessage,
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

from cmdb.errors.manager.impact_category_manager import (
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerGetError,
    ImpactCategoryManagerUpdateError,
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerIterationError,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id, update_item_from_payload
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

impact_category_blueprint = APIBlueprint('impact_categories', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@impact_category_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.add')
@impact_category_blueprint.validate(build_write_schema(IsmsImpactCategory.SCHEMA))
@handle_route_errors("while creating the ImpactCategory")
@handle_manager_errors(manager_error_messages(IMPACT_CATEGORY_LABEL, {
    ImpactCategoryManagerInsertError: IsmsManagerErrorMessage.INSERT,
    ImpactCategoryManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
}))
def insert_isms_impact_category(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsImpactCategory into the database

    Args:
        data (IsmsImpactCategory.SCHEMA): Data of the IsmsImpactCategory which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert or the read-back of the created ImpactCategory fails, 500 when
            the created ImpactCategory cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsImpactCategory and its public_id
    """
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    result_id: int = impact_category_manager.create_with_follow_up(data)

    created_impact_category: dict[str, Any] = require_created_item(
        impact_category_manager.get_item(result_id, as_dict=True), IMPACT_CATEGORY_LABEL,
    )

    return InsertSingleResponse(created_impact_category, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@impact_category_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.view')
@impact_category_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving ImpactCategories")
@handle_manager_errors(manager_error_messages(IMPACT_CATEGORY_LABEL, {
    ImpactCategoryManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_impact_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsImpactCategories

    Args:
        params (CollectionParameters): Filter for requested IsmsImpactCategories
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsImpactCategories matching the CollectionParameters
    """
    body = request_wants_body()

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


@impact_category_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.view')
@handle_route_errors("while retrieving the ImpactCategory with ID: {public_id}")
@handle_manager_errors(manager_error_messages(IMPACT_CATEGORY_LABEL, {
    ImpactCategoryManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_impact_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsImpactCategory

    Args:
        public_id (int): public_id of the IsmsImpactCategory
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsImpactCategory
    """
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    requested_impact = get_item_or_404(impact_category_manager, public_id,
                                        f"The ImpactCategory with ID:{public_id} was not found!")

    return GetSingleResponse(requested_impact, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@impact_category_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.edit')
@impact_category_blueprint.validate(build_write_schema(IsmsImpactCategory.SCHEMA))
@handle_route_errors("while updating the ImpactCategory with ID: {public_id}")
@handle_manager_errors(manager_error_messages(IMPACT_CATEGORY_LABEL, {
    ImpactCategoryManagerGetError: IsmsManagerErrorMessage.GET,
    ImpactCategoryManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
}))
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
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    get_item_or_404(impact_category_manager, public_id,
                    f"The ImpactCategory with ID:{public_id} was not found!", as_dict=False)

    # The URL owns the identity: a body public_id would otherwise be $set onto the document

    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_item_from_payload(impact_category_manager, public_id, IsmsImpactCategory, data)

    return UpdateSingleResponse(stored).make_response()


@impact_category_blueprint.route('/multiple', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.edit')
@handle_route_errors("while updating multiple ImpactCategories")
def update_multiple_isms_impact_categories(request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update multiple IsmsImpactCategory records.

    Args:
        data (list of IsmsImpactCategory.SCHEMA): List of new IsmsImpactCategory data
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: Per-item summary of successes and failures
    """
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    results = update_multiple_items(
        impact_category_manager,
        IsmsImpactCategory,
        request.get_json(silent=True),
        "ImpactCategory",
        "update_multiple_isms_impact_categories",
    )

    return DefaultResponse(results).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@impact_category_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_category_blueprint.protect(auth=True, right='base.isms.impactCategory.delete')
@handle_route_errors("while deleting the ImpactCategory with ID: {public_id}")
@handle_manager_errors(manager_error_messages(IMPACT_CATEGORY_LABEL, {
    ImpactCategoryManagerDeleteError: IsmsManagerErrorMessage.DELETE,
    ImpactCategoryManagerGetError: IsmsManagerErrorMessage.GET,
}))
def delete_isms_impact_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsImpactCategory

    Args:
        public_id (int): public_id of the IsmsImpactCategory which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsImpactCategory data
    """
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    to_delete_impact = get_item_or_404(impact_category_manager, public_id,
                                       f"The ImpactCategory with ID:{public_id} was not found!")

    impact_category_manager.delete_with_follow_up(public_id)

    return DeleteSingleResponse(to_delete_impact).make_response()
