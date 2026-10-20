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
Implementation of the API route for the ISMS configuration status

``GET /isms/config/status`` answers whether the ISMS is configured enough to be used: five readiness flags
(``IsmsConfigStatusKey``) - at least three risk classes, three likelihoods, three impacts, one impact category,
and a risk matrix that matches the scales with a risk class in every cell. The frontend checks it before every
operational ISMS screen and on the ISMS overview.

**It needs no right, by design.** Every ISMS user reaches it, whichever ISMS rights their group holds, because
every ISMS screen reads it - the gate is a login and the ISMS licence, which the whole blueprint group carries.
The answer is five booleans about the installation's setup and names no ISMS record. Because no right guards it,
**the route only reads**: a missing or stale risk matrix is reported as not ready rather than recreated or rebuilt -
``GET /isms/risk_matrix/1``, behind ``base.isms.riskMatrix.view``, does both
"""
from logging import Logger, getLogger
from typing import Any
from werkzeug import Response

from cmdb.manager import (
    RiskClassManager,
    LikelihoodManager,
    ImpactManager,
    ImpactCategoryManager,
    RiskMatrixManager,
)

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.isms_routes.isms_config_helper import (
    build_isms_config_status,
    is_risk_matrix_ready,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

isms_config_blueprint = APIBlueprint('isms_config', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@isms_config_blueprint.route('/status', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while retrieving the ISMS configuration status")
@handle_manager_errors({
    BaseManagerGetError: ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE,
    RiskMatrixManagerGetError: ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE,
})
def get_isms_config_status(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve the status of the ISMS configuration

    Needs no right (see the module docstring) and writes nothing. Four counts and one read of the stored
    IsmsRiskMatrix; the matrix is ready only when it exists, has one cell per (impact, likelihood) pair of the
    current scales and a risk class in each (``is_risk_matrix_ready``)

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when a count or the RiskMatrix read fails, 500 on an unexpected error

    Returns:
        DefaultResponse: ``{risk_classes, likelihoods, impacts, impact_categories, risk_matrix}``, one boolean
                         per configuration section
    """
    risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)
    likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    impact_category_manager: ImpactCategoryManager = ManagerProvider.get_manager(ManagerType.IMPACT_CATEGORY,
                                                                                 request_user)
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)

    risk_class_amount: int = risk_class_manager.count_documents()
    likelihood_amount: int = likelihood_manager.count_documents()
    impact_amount: int = impact_manager.count_documents()
    impact_category_amount: int = impact_category_manager.count_documents()

    stored_risk_matrix: dict[str, Any] | None = risk_matrix_manager.get_item(RISK_MATRIX_PUBLIC_ID, as_dict=True)

    config_status: dict[str, bool] = build_isms_config_status(
        risk_class_amount,
        likelihood_amount,
        impact_amount,
        impact_category_amount,
        is_risk_matrix_ready(stored_risk_matrix, impact_amount, likelihood_amount),
    )

    return DefaultResponse(config_status).make_response()
