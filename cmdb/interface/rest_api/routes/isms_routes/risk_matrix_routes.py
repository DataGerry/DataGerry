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
Implementation of all API routes for the IsmsRiskMatrix
"""
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import RiskMatrixManager

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsRiskMatrix

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    GetSingleResponse,
    UpdateSingleResponse,
)

from cmdb.errors.manager.risk_matrix_manager import (
    RiskMatrixManagerGetError,
    RiskMatrixManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

risk_matrix_blueprint = APIBlueprint('risk_matrices', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@risk_matrix_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_matrix_blueprint.protect(auth=True, right='base.isms.riskMatrix.view')
def get_isms_risk_matrix(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the IsmsRiskMatrix

    Args:
        public_id (int): public_id of the IsmsRiskMatrix
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsRiskMatrix
    """
    try:
        risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(
                                                                    ManagerType.RISK_MATRIX,
                                                                    request_user
                                                                         )

        requested_risk_matrix = risk_matrix_manager.get_item(public_id, as_dict=True)

        if requested_risk_matrix:
            return GetSingleResponse(requested_risk_matrix, body = request.method == 'HEAD').make_response()

        abort(404, f"The RiskMatrix with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except RiskMatrixManagerGetError as err:
        LOGGER.error("[get_isms_risk_matrix] RiskMatrixManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskMatrix with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_matrix] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the RiskMatrix!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@risk_matrix_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_matrix_blueprint.protect(auth=True, right='base.isms.riskMatrix.edit')
@risk_matrix_blueprint.validate(IsmsRiskMatrix.SCHEMA)
def update_isms_risk_matrix(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsRiskMatrix

    Args:
        public_id (int): public_id of the IsmsRiskMatrix which should be updated
        data (IsmsRiskMatrix.SCHEMA): New IsmsRiskMatrix data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsRiskMatrix
    """
    try:
        risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(
                                                                    ManagerType.RISK_MATRIX,
                                                                    request_user
                                                                         )

        to_update_risk_matrix = risk_matrix_manager.get_item(public_id)

        if not to_update_risk_matrix:
            abort(404, f"The RiskMatrix with ID:{public_id} was not found!")

        risk_matrix_manager.update_item(public_id, IsmsRiskMatrix.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskMatrixManagerGetError as err:
        LOGGER.error("[update_isms_risk_matrix] RiskMatrixManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskMatrix with ID: {public_id} from the database!")
    except RiskMatrixManagerUpdateError as err:
        LOGGER.error("[update_isms_risk_matrix] RiskMatrixManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the RiskMatrix with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_risk_matrix] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the RiskMatrix with ID: {public_id}!")
