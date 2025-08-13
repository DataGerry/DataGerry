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
Implementation of all API routes for IsmsLikelihoods
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import LikelihoodManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsLikelihood
from cmdb.models.isms_model.isms_helper import calculate_risk_matrix

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
)

from cmdb.errors.manager.likelihood_manager import (
    LikelihoodManagerInsertError,
    LikelihoodManagerGetError,
    LikelihoodManagerUpdateError,
    LikelihoodManagerDeleteError,
    LikelihoodManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

likelihood_blueprint = APIBlueprint('likelihoods', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@likelihood_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@likelihood_blueprint.protect(auth=True, right='base.isms.likelihood.add')
@likelihood_blueprint.validate(IsmsLikelihood.SCHEMA)
def insert_isms_likelihood(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsLikelihood into the database

    Args:
        data (IsmsLikelihood.SCHEMA): Data of the IsmsLikelihood which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsLikelihood and its public_id
    """
    try:
        likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

        # There is a Limit of 6 Likelihood classes
        likelihood_count = likelihood_manager.count_items()

        if likelihood_count >= 6:
            abort(403, "Only a maximum of 6 Likelihoods can be created!")

        try:
            data['calculation_basis'] = float(f"{float(data['calculation_basis']):.2f}")
        except Exception:
            abort(400, "The calculation basis is either not provided or could not be converted to a float!")

        if likelihood_manager.likelihood_calculation_basis_exists(data['calculation_basis']):
            abort(400, "The calculation basis is already used by another Likelihood!")

        result_id: int = likelihood_manager.insert_item(data)

        created_likelihood: dict = likelihood_manager.get_item(result_id, as_dict=True)

        if created_likelihood:
            calculate_risk_matrix(request_user)

            return InsertSingleResponse(created_likelihood, result_id).make_response()

        abort(404, "Could not retrieve the created Likelihood from the database!")
    except HTTPException as http_err:
        raise http_err
    except LikelihoodManagerInsertError as err:
        LOGGER.error("[insert_isms_likelihood] LikelihoodManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new Likelihood in the database!")
    except LikelihoodManagerGetError as err:
        LOGGER.error("[insert_isms_likelihood] LikelihoodManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Likelihood from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_likelihood] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Likelihood!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@likelihood_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@likelihood_blueprint.protect(auth=True, right='base.isms.likelihood.view')
@likelihood_blueprint.parse_collection_parameters()
def get_isms_likelihoods(params: CollectionParameters, request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsLikelihoods

    Args:
        params (CollectionParameters): Filter for requested IsmsLikelihoods
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsLikelihoods matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[IsmsLikelihood] = likelihood_manager.iterate_items(builder_params)
        likelihood_list = [IsmsLikelihood.to_json(likelihood) for likelihood in iteration_result.results]

        api_response = GetMultiResponse(likelihood_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except LikelihoodManagerIterationError as err:
        LOGGER.error("[get_isms_likelihoods] LikelihoodManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Likelihood from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_likelihoods] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Likelihoods!")


@likelihood_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@likelihood_blueprint.protect(auth=True, right='base.isms.likelihood.view')
def get_isms_likelihood(public_id: int, request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsLikelihood

    Args:
        public_id (int): public_id of the IsmsLikelihood
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsLikelihood
    """
    try:
        likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

        requested_likelihood = likelihood_manager.get_item(public_id, as_dict=True)

        if requested_likelihood:
            return GetSingleResponse(requested_likelihood, body = request.method == 'HEAD').make_response()

        abort(404, f"The Likelihood with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except LikelihoodManagerGetError as err:
        LOGGER.error("[get_isms_likelihood] LikelihoodManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Likelihood with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_likelihood] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Likelihood with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@likelihood_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@likelihood_blueprint.protect(auth=True, right='base.isms.likelihood.edit')
@likelihood_blueprint.validate(IsmsLikelihood.SCHEMA)
def update_isms_likelihood(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsLikelihood

    Args:
        public_id (int): public_id of the IsmsLikelihood which should be updated
        data (IsmsLikelihood.SCHEMA): New IsmsLikelihood data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsLikelihood
    """
    try:
        likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

        to_update_likelihood: IsmsLikelihood = likelihood_manager.get_item(public_id)

        if not to_update_likelihood:
            abort(404, f"The Likelihood with ID:{public_id} was not found!")

        try:
            data['calculation_basis'] = float(f"{float(data['calculation_basis']):.2f}")
        except Exception:
            abort(400, "The calculation basis is either not provided or could not be converted to a float!")

        # If the calculation_basis changed, also update IsmsRiskAssessments
        if round(data['calculation_basis'], 2) != round(to_update_likelihood.calculation_basis, 2):
            likelihood_manager.update_with_follow_up(public_id, data)
        else:
            likelihood_manager.update_item(public_id, IsmsLikelihood.from_data(data))

        # Calculate the RiskMatrix
        calculate_risk_matrix(request_user)

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except LikelihoodManagerGetError as err:
        LOGGER.error("[update_isms_likelihood] LikelihoodManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Likelihood with ID: {public_id} from the database!")
    except LikelihoodManagerUpdateError as err:
        LOGGER.error("[update_isms_likelihood] LikelihoodManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Likelihood with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_likelihood] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Likelihood with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@likelihood_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@likelihood_blueprint.protect(auth=True, right='base.isms.likelihood.delete')
def delete_isms_likelihood(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single IsmsLikelihood

    Args:
        public_id (int): public_id of the IsmsLikelihood which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsLikelihood data
    """
    try:
        likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

        to_delete_likelihood = likelihood_manager.get_item(public_id, as_dict=True)

        if not to_delete_likelihood:
            abort(404, f"The Likelihood with ID:{public_id} was not found!")

        if likelihood_manager.is_likelihood_used(public_id):
            abort(400, "The Likelihood is used by a RiskAssessment and is therefore not deletable!")

        likelihood_manager.delete_item(public_id)

        # Calculate the RiskMatrix
        calculate_risk_matrix(request_user)

        return DeleteSingleResponse(to_delete_likelihood).make_response()
    except HTTPException as http_err:
        raise http_err
    except LikelihoodManagerDeleteError as err:
        LOGGER.error("[delete_isms_likelihood] LikelihoodManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Likelihood with ID:{public_id}!")
    except LikelihoodManagerGetError as err:
        LOGGER.error("[delete_isms_likelihood] LikelihoodManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Likelihood with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_likelihood] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Likelihood with ID: {public_id}!")
