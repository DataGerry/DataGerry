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
Implementation of all API routes for IsmsImpacts
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ImpactManager, ImpactCategoryManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsImpact
from cmdb.models.isms_model.isms_helper import calculate_risk_matrix
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import MAX_ISMS_SCALE_ENTRIES

from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import get_item_or_404
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)

from cmdb.errors.manager.impact_manager import (
    ImpactManagerInsertError,
    ImpactManagerGetError,
    ImpactManagerUpdateError,
    ImpactManagerDeleteError,
    ImpactManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

impact_blueprint = APIBlueprint('impacts', __name__)


def _coerce_calculation_basis(data: dict[str, Any]) -> None:
    """
    Coerces ``data['calculation_basis']`` to a 2-decimal float in place, aborting 400 if it is
    missing or not convertible.

    Args:
        data (dict[str, Any]): The request body holding the calculation_basis to normalise
    """
    try:
        data['calculation_basis'] = float(f"{float(data['calculation_basis']):.2f}")
    except Exception:
        abort(400, "The calculation basis is either not provided or could not be converted to a float!")

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@impact_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.add')
@impact_blueprint.validate(IsmsImpact.SCHEMA)
def insert_isms_impact(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsImpact into the database

    Args:
        data (IsmsImpact.SCHEMA): Data of the IsmsImpact which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsImpact and its public_id
    """
    try:
        impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)
        # There is a Limit of MAX_ISMS_SCALE_ENTRIES Impact classes
        if impact_manager.count_documents() >= MAX_ISMS_SCALE_ENTRIES:
            abort(403, f"Only a maximum of {MAX_ISMS_SCALE_ENTRIES} Impacts can be created!")

        _coerce_calculation_basis(data)

        if impact_manager.impact_calculation_basis_exists(data['calculation_basis']):
            abort(400, "The calculation basis is already used by another Impact!")

        result_id: int = impact_manager.insert_item(data)

        created_impact: dict = impact_manager.get_item(result_id, as_dict=True)

        if not created_impact:
            abort(404, "Could not retrieve the created Impact from the database!")

        # Update all IsmsImpactCategories with new IsmsImpact
        impact_category_manager.add_new_impact_to_categories(result_id)

        # Calculate the RiskMatrix
        calculate_risk_matrix(request_user)

        return InsertSingleResponse(created_impact, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactManagerInsertError as err:
        LOGGER.error("[insert_isms_impact] ImpactManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new Impact in the database!")
    except ImpactManagerGetError as err:
        LOGGER.error("[insert_isms_impact] ImpactManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Impact from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_impact] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Impact!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@impact_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.view')
@impact_blueprint.parse_collection_parameters()
def get_isms_impacts(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsImpacts

    Args:
        params (CollectionParameters): Filter for requested IsmsImpacts
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsImpacts matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsImpact] = impact_manager.iterate_items(builder_params)
        impact_list = [IsmsImpact.to_json(impact) for impact in iteration_result.results]

        api_response = GetMultiResponse(impact_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ImpactManagerIterationError as err:
        LOGGER.error("[get_isms_impacts] ImpactManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Impacts from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_impacts] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Impacts!")


@impact_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.view')
def get_isms_impact(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsImpact

    Args:
        public_id (int): public_id of the IsmsImpact
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsImpact
    """
    try:
        impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)

        requested_impact = get_item_or_404(impact_manager, public_id,
                                           f"The Impact with ID:{public_id} was not found!")

        return GetSingleResponse(requested_impact, body = request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactManagerGetError as err:
        LOGGER.error("[get_isms_impact] ImpactManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Impact with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_impact] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Impact with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@impact_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.edit')
@impact_blueprint.validate(IsmsImpact.SCHEMA)
def update_isms_impact(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsImpact

    Args:
        public_id (int): public_id of the IsmsImpact which should be updated
        data (IsmsImpact.SCHEMA): New IsmsImpact data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsImpact
    """
    try:
        impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)

        to_update_impact = get_item_or_404(impact_manager, public_id,
                                           f"The Impact with ID:{public_id} was not found!",
                                           as_dict=False)

        _coerce_calculation_basis(data)

        basis_changed = round(data['calculation_basis'], 2) != round(to_update_impact.calculation_basis, 2)

        # A changed basis must not collide with another Impact's basis (insert enforces the same rule)
        if basis_changed and impact_manager.impact_calculation_basis_exists(data['calculation_basis']):
            abort(400, "The calculation basis is already used by another Impact!")

        # If the calculation_basis changed, also update IsmsRiskAssessments
        if basis_changed:
            impact_manager.update_with_follow_up(public_id, data)
        else:
            impact_manager.update_item(public_id, IsmsImpact.from_data(data))

        # Calculate the RiskMatrix
        calculate_risk_matrix(request_user)

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactManagerGetError as err:
        LOGGER.error("[update_isms_impact] ImpactManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Impact with ID: {public_id} from the database!")
    except ImpactManagerUpdateError as err:
        LOGGER.error("[update_isms_impact] ImpactManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Impact with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_impact] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Impact with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@impact_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.delete')
def delete_isms_impact(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsImpact

    Args:
        public_id (int): public_id of the IsmsImpact which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsImpact data
    """
    try:
        impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
        impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                     request_user)

        to_delete_impact = get_item_or_404(impact_manager, public_id,
                                           f"The Impact with ID:{public_id} was not found!")

        if impact_manager.is_impact_used(public_id):
            abort(400, f"Impact with ID: {public_id} is referenced in RiskAssessments and cannot be deleted!")

        impact_manager.delete_item(public_id)

        # Delete the IsmsImpact from all the IsmsImpactCategories
        impact_category_manager.remove_deleted_impact_from_categories(public_id)

        # Calculate the RiskMatrix
        calculate_risk_matrix(request_user)

        return DeleteSingleResponse(to_delete_impact).make_response()
    except HTTPException as http_err:
        raise http_err
    except ImpactManagerDeleteError as err:
        LOGGER.error("[delete_isms_impact] ImpactManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Impact with ID:{public_id}!")
    except ImpactManagerGetError as err:
        LOGGER.error("[delete_isms_impact] ImpactManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Impact with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_impact] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Impact with ID: {public_id}!")
