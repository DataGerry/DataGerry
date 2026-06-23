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
Implementation of all API routes for ISMS Configuration
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import (
    RiskClassManager,
    LikelihoodManager,
    ImpactManager,
    ImpactCategoryManager,
    RiskMatrixManager,
)

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model.isms_helper import check_risk_classes_set_in_matrix, ensure_default_risk_matrix


from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

isms_config_blueprint = APIBlueprint('isms_config', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@isms_config_blueprint.route('/status', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_isms_config_status(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve the status of the ISMS configuration

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The status of the ISMS configuration as dict
    """
    try:
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

        # The RiskMatrix is a singleton (public_id 1) seeded at setup; recreate the default if missing
        current_risk_matrix: dict[str, Any] = ensure_default_risk_matrix(risk_matrix_manager)

        risk_matrix_risk_class_status: bool = check_risk_classes_set_in_matrix(current_risk_matrix)

        config_status: dict[str, bool] = {
            'risk_classes': risk_class_amount >= 3,
            'likelihoods': likelihood_amount >= 3,
            'impacts': impact_amount >= 3,
            'impact_categories': impact_category_amount >= 1,
            'risk_matrix': risk_matrix_risk_class_status\
                           and risk_class_amount >= 3\
                           and likelihood_amount >= 3\
                           and impact_amount >= 3,
        }

        return DefaultResponse(config_status).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_isms_config_status] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the ISMS configuration status!")
