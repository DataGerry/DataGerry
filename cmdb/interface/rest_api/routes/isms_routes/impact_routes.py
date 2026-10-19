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

**Every write is all-or-nothing.** Creating, updating or deleting an Impact also writes every ImpactCategory's
description of it (create / delete), the RiskAssessments using a changed calculation_basis (update) and the
RiskMatrix rebuilt from the scales. Each route runs all of them in one ledger (``scale_write_ledger``): a failure
anywhere takes back what was already written and answers the error it hit; an undo that cannot finish answers 500
naming what is left
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import ImpactManager, ImpactCategoryManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsImpact
from cmdb.models.isms_model.isms_helper import calculate_risk_matrix
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    MAX_ISMS_SCALE_ENTRIES,
    ISMS_IMPACTS_LABEL,
    IMPACT_LABEL,
    CALCULATION_BASIS_TAKEN_MSG,
    IsmsManagerErrorMessage,
    IsmsWriteAction,
)

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
    abort_if_isms_cap_reached,
    get_item_or_404,
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_scale_helper import (
    coerce_calculation_basis,
    insert_scale_entry,
    scale_write_ledger,
    update_scale_entry,
)
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
    ImpactManagerCalculationBasisError,
    ImpactManagerAssessmentUsageError,
)
from cmdb.errors.manager.impact_category_manager import ImpactCategoryManagerUpdateError
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

impact_blueprint = APIBlueprint('impacts', __name__)


# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@impact_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.add')
@impact_blueprint.validate(build_write_schema(IsmsImpact.SCHEMA))
@handle_route_errors("while creating the Impact")
@handle_manager_errors(manager_error_messages(IMPACT_LABEL, {
    ImpactManagerInsertError: IsmsManagerErrorMessage.INSERT,
    ImpactManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
    ImpactManagerCalculationBasisError: IsmsManagerErrorMessage.CALCULATION_BASIS_CHECK,
    ImpactCategoryManagerUpdateError: IsmsManagerErrorMessage.CATEGORY_DESCRIPTIONS,
}))
def insert_isms_impact(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsImpact into the database

    Args:
        data (IsmsImpact.SCHEMA): Data of the IsmsImpact which should be inserted
        request_user (CmdbUser): User requesting this data

    The Impact, its description in every ImpactCategory and the rebuilt RiskMatrix are written in one ledger:
    any failure leaves none of them behind

    Raises:
        HTTPException: 400 when the insert, the read-back of the created Impact or the ImpactCategories' update
            fails, 500 when the created Impact cannot be found afterwards, an undo cannot finish or on an
            unexpected error

    Returns:
        InsertSingleResponse: The new IsmsImpact and its public_id
    """
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    abort_if_isms_cap_reached(impact_manager, MAX_ISMS_SCALE_ENTRIES, ISMS_IMPACTS_LABEL)

    coerce_calculation_basis(data)

    if impact_manager.impact_calculation_basis_exists(data[ImpactKey.CALCULATION_BASIS.value]):
        abort(400, CALCULATION_BASIS_TAKEN_MSG.format(entity=IMPACT_LABEL.singular))

    with scale_write_ledger(IsmsWriteAction.CREATE, IMPACT_LABEL) as ledger:
        result_id: int = insert_scale_entry(impact_manager, data, IMPACT_LABEL, ledger)

        created_impact: dict[str, Any] = require_created_item(
            impact_manager.get_item(result_id, as_dict=True), IMPACT_LABEL,
        )

        impact_category_manager.add_new_impact_to_categories(result_id, ledger)

        calculate_risk_matrix(request_user, ledger)

    return InsertSingleResponse(created_impact, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@impact_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.view')
@impact_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving Impacts")
@handle_manager_errors(manager_error_messages(IMPACT_LABEL, {
    ImpactManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_impacts(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsImpacts

    Args:
        params (CollectionParameters): Filter for requested IsmsImpacts
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsImpacts matching the CollectionParameters
    """
    body = request_wants_body()

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


@impact_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.view')
@handle_route_errors("while retrieving the Impact with ID: {public_id}")
@handle_manager_errors(manager_error_messages(IMPACT_LABEL, {
    ImpactManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_impact(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsImpact

    Args:
        public_id (int): public_id of the IsmsImpact
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsImpact
    """
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)

    requested_impact = get_item_or_404(impact_manager, public_id,
                                       f"The Impact with ID:{public_id} was not found!")

    return GetSingleResponse(requested_impact, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@impact_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.edit')
@impact_blueprint.validate(build_write_schema(IsmsImpact.SCHEMA))
@handle_route_errors("while updating the Impact with ID: {public_id}")
@handle_manager_errors(manager_error_messages(IMPACT_LABEL, {
    ImpactManagerGetError: IsmsManagerErrorMessage.GET,
    ImpactManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
    ImpactManagerCalculationBasisError: IsmsManagerErrorMessage.CALCULATION_BASIS_CHECK,
}))
def update_isms_impact(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsImpact

    All of the route's writes run in one ledger: a failure anywhere takes back what was already written, and an
    undo that cannot finish answers 500 naming the writes still in effect

    Args:
        public_id (int): public_id of the IsmsImpact which should be updated
        data (IsmsImpact.SCHEMA): New IsmsImpact data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsImpact
    """
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)

    to_update_impact = get_item_or_404(impact_manager, public_id,
                                       f"The Impact with ID:{public_id} was not found!",
                                       as_dict=False)

    coerce_calculation_basis(data)

    new_basis = data[ImpactKey.CALCULATION_BASIS.value]
    basis_changed = round(new_basis, 2) != round(to_update_impact.calculation_basis, 2)

    # A changed basis must not collide with another Impact's basis (insert enforces the same rule)
    if basis_changed and impact_manager.impact_calculation_basis_exists(new_basis):
        abort(400, CALCULATION_BASIS_TAKEN_MSG.format(entity=IMPACT_LABEL.singular))

    # The URL owns the identity: a body public_id would otherwise be $set onto the document, and
    # both branches below build the model from this payload
    pin_public_id(data, public_id)

    # A changed calculation_basis also rewrites the IsmsRiskAssessments using it; with the RiskMatrix, all or none
    with scale_write_ledger(IsmsWriteAction.UPDATE, IMPACT_LABEL) as ledger:
        stored: dict[str, Any] = update_scale_entry(impact_manager, IsmsImpact, public_id, data, basis_changed,
                                                    IMPACT_LABEL, ledger)

        calculate_risk_matrix(request_user, ledger)

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@impact_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@impact_blueprint.protect(auth=True, right='base.isms.impact.delete')
@handle_route_errors("while deleting the Impact with ID: {public_id}")
@handle_manager_errors(
    manager_error_messages(IMPACT_LABEL, {
        ImpactManagerDeleteError: IsmsManagerErrorMessage.DELETE,
        ImpactManagerGetError: IsmsManagerErrorMessage.GET,
        ImpactCategoryManagerUpdateError: IsmsManagerErrorMessage.CATEGORY_DESCRIPTIONS,
    }),
    refusals=manager_error_messages(IMPACT_LABEL, {
        ImpactManagerAssessmentUsageError: IsmsManagerErrorMessage.USED_BY_ASSESSMENTS,
    }),
)
def delete_isms_impact(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsImpact

    All of the route's writes run in one ledger: a failure anywhere takes back what was already written, and an
    undo that cannot finish answers 500 naming the writes still in effect

    Args:
        public_id (int): public_id of the IsmsImpact which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsImpact data
    """
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)

    to_delete_impact = get_item_or_404(impact_manager, public_id,
                                       f"The Impact with ID:{public_id} was not found!")

    with scale_write_ledger(IsmsWriteAction.DELETE, IMPACT_LABEL) as ledger:
        # Refused while an IsmsRiskAssessment uses it - checked again right after. Recorded once it really
        # deleted: a refused delete, or one that found nothing, must not be "undone" by inserting the snapshot
        if impact_manager.delete_if_unused(public_id):
            ledger.deleted(impact_manager, public_id, to_delete_impact)

        impact_category_manager.remove_deleted_impact_from_categories(public_id, ledger)

        calculate_risk_matrix(request_user, ledger)

    return DeleteSingleResponse(to_delete_impact).make_response()
