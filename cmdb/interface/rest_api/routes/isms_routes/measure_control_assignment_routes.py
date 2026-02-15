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
Implementation of all API routes for the IsmsControlMeasureAssignments
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import (
    ControlMeasureAssignmentManager,
    RiskManager,
    ObjectGroupsManager,
    ObjectsManager,
    RiskAssessmentManager,
    TypesManager,
)
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRisk

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

from cmdb.errors.manager.control_measure_assignment_manager import (
    ControlMeasureAssignmentManagerInsertError,
    ControlMeasureAssignmentManagerGetError,
    ControlMeasureAssignmentManagerUpdateError,
    ControlMeasureAssignmentManagerDeleteError,
    ControlMeasureAssignmentManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

control_measure_assignment_blueprint = APIBlueprint('control_measure_assignment', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@control_measure_assignment_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.add')
@control_measure_assignment_blueprint.validate(IsmsControlMeasureAssignment.SCHEMA)
def insert_isms_control_measure_assignment(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsControlMeasureAssignment into the database

    Args:
        data (IsmsControlMeasureAssignment.SCHEMA): Data of the IsmsControlMeasureAssignment which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsControlMeasureAssignment and its public_id
    """
    try:
        c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                         )

        result_id = c_m_assignment_manager.insert_item(data)

        created_control_measure_assignment = c_m_assignment_manager.get_item(result_id, as_dict=True)

        if created_control_measure_assignment:
            return InsertSingleResponse(created_control_measure_assignment, result_id).make_response()

        abort(404, "Could not retrieve the created ControlMeasure Assignment from the database!")
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureAssignmentManagerInsertError as err:
        LOGGER.error(
            "[insert_isms_control_measure_assignment] ControlMeasureAssignmentManagerInsertError: %s",
            err,
            exc_info=True
        )
        abort(400, "Failed to insert the new ControlMeasure Assignment in the database!")
    except ControlMeasureAssignmentManagerGetError as err:
        LOGGER.error(
            "[insert_isms_control_measure_assignment] ControlMeasureAssignmentManagerGetError: %s", err, exc_info=True
        )
        abort(400, "Failed to retrieve the created ControlMeasure Assignment from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_control_measure_assignment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ControlMeasure Assignment!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@control_measure_assignment_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.view')
@control_measure_assignment_blueprint.parse_collection_parameters()
def get_isms_control_measure_assignments(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsControlMeasureAssignments

    Args:
        params (CollectionParameters): Filter for requested IsmsControlMeasureAssignments
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsControlMeasureAssignments matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        cma_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
            request_user
        )
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
            ManagerType.RISK_ASSESSMENT,
            request_user
        )
        risk_manager: RiskManager = ManagerProvider.get_manager(
            ManagerType.RISK,
            request_user
        )
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )
        objects_manager: ObjectsManager = ManagerProvider.get_manager(
            ManagerType.OBJECTS,
            request_user
        )
        types_manager: TypesManager = ManagerProvider.get_manager(
            ManagerType.TYPES,
            request_user
        )

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[IsmsControlMeasureAssignment] = cma_manager.iterate_items(
                                                                            builder_params
                                                                          )

        cmas = iteration_result.results
        ra_ids = {cma.risk_assessment_id for cma in cmas if hasattr(cma, 'risk_assessment_id')}

        # Fetch Risk Assessments in bulk
        ra_map = {
            ra['public_id']: ra for ra in risk_assessment_manager.find_all(
                criteria={'public_id': {'$in': list(ra_ids)}}
            )
        }

        # Extract all risk_ids and object/object_group ids
        risk_ids = set()
        object_ids = set()
        object_group_ids = set()
        type_ids = set()

        for ra in ra_map.values():
            if ra.get('risk_id'):
                risk_ids.add(ra['risk_id'])
            if ra.get('object_id_ref_type') == 'OBJECT':
                object_ids.add(ra.get('object_id'))
            elif ra.get('object_id_ref_type') == 'OBJECT_GROUP':
                object_group_ids.add(ra.get('object_id'))

        # Fetch required details
        risks = {
            risk['public_id']: risk
            for risk in risk_manager.get_many_from_other_collection(
                IsmsRisk.COLLECTION,
                public_id={'$in': list(risk_ids)}
            )
        }
        # Fetch objects
        object_map = {
            obj_id: objects_manager.get_object(obj_id) for obj_id in object_ids
        }
        object_summaries = {
            obj_id: objects_manager.get_summary_line(obj_id) for obj_id in object_ids
        }

        # Collect type_ids from object_map
        type_ids = {obj.get('type_id') for obj in object_map.values() if obj and obj.get('type_id')}

        # Fetch types
        types_map = {
            t['public_id']: t
            for t in types_manager.find_all(criteria={'public_id': {'$in': list(type_ids)}})
        }

        # Fetch object groups
        object_groups = {
            og['public_id']: og['name']
            for og in object_groups_manager.find_all(criteria={'public_id': {'$in': list(object_group_ids)}})
        }

        # Build enriched CMA list
        cma_list = []
        for cma in cmas:
            risk_assessment = ra_map.get(cma.risk_assessment_id)
            summary = None

            if risk_assessment:
                ra_id = risk_assessment.get('public_id', '')
                risk_name = risks.get(risk_assessment.get('risk_id'), {}).get('name', '')

                obj_summary = ''
                if risk_assessment.get('object_id_ref_type') == 'OBJECT':
                    obj_id = risk_assessment.get('object_id')
                    summary_line = object_summaries.get(obj_id, '')
                    obj = object_map.get(obj_id)
                    type_label = ''

                    if obj and obj.get('type_id'):
                        type_obj = types_map.get(obj['type_id'])
                        type_label = f"{type_obj['label']}" if type_obj and 'label' in type_obj else ''

                    obj_summary = f"{summary_line} ({type_label})"

                elif risk_assessment.get('object_id_ref_type') == 'OBJECT_GROUP':
                    obj_summary = object_groups.get(risk_assessment.get('object_id'), '')

                summary = f"#{ra_id} - {risk_name} @ {obj_summary}"

            cma_dict = IsmsControlMeasureAssignment.to_json(cma)
            cma_dict['naming'] = {'cma_summary': summary or None}
            cma_list.append(cma_dict)

        api_response = GetMultiResponse(cma_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ControlMeasureAssignmentManagerIterationError as err:
        LOGGER.error(
            "[get_isms_control_measure_assignments] ControlMeasureAssignmentManagerIterationError: %s",
            err,
            exc_info=True
        )
        abort(400, "Failed to retrieve ControlMeasure Assignments from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_control_measure_assignments] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving ControlMeasure Assignments!")


@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.view')
def get_isms_control_measure_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsControlMeasureAssignment
    """
    try:
        c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                         )

        requested_control_measure_assignment = c_m_assignment_manager.get_item(public_id, as_dict=True)

        if requested_control_measure_assignment:
            return GetSingleResponse(requested_control_measure_assignment,
                                     body = request.method == 'HEAD').make_response()

        abort(404, f"The ControlMeasure Assignment with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureAssignmentManagerGetError as err:
        LOGGER.error(
            "[get_isms_control_measure_assignment] ControlMeasureAssignmentManagerGetError: %s", err, exc_info=True
        )
        abort(400, f"Failed to retrieve the ControlMeasure Assignment with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_control_measure_assignment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(
            500,
            f"An internal server error occured while retrieving the ControlMeasure Assignment with ID: {public_id}!"
        )

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.edit')
@control_measure_assignment_blueprint.validate(IsmsControlMeasureAssignment.SCHEMA)
def update_isms_control_measure_assignment(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment which should be updated
        data (IsmsControlMeasureAssignment.SCHEMA): New IsmsControlMeasureAssignment data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsControlMeasureAssignment
    """
    try:
        c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                         )

        to_update_control_measure_assignment = c_m_assignment_manager.get_item(public_id)

        if not to_update_control_measure_assignment:
            abort(404, f"The ControlMeasure Assignment with ID:{public_id} was not found!")

        c_m_assignment_manager.update_item(public_id, IsmsControlMeasureAssignment.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureAssignmentManagerGetError as err:
        LOGGER.error(
            "[update_isms_control_measure_assignment] ControlMeasureAssignmentManagerGetError: %s", err, exc_info=True
        )
        abort(400, f"Failed to retrieve the ControlMeasure Assignment with ID: {public_id} from the database!")
    except ControlMeasureAssignmentManagerUpdateError as err:
        LOGGER.error(
            "[update_isms_control_measure_assignment] ControlMeasureAssignmentManagerUpdateError: %s",
            err,
            exc_info=True
        )
        abort(400, f"Failed to update the ControlMeasure Assignment with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_control_measure_assignment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
            f"An internal server error occured while updating the ControlMeasure Assignment with ID: {public_id}!"
        )

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.delete')
def delete_isms_control_measure_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsControlMeasureAssignment data
    """
    try:
        c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                         )

        to_delete_control_measure_assignment = c_m_assignment_manager.get_item(public_id)

        if not to_delete_control_measure_assignment:
            abort(404, f"The ControlMeasure Assignment with ID:{public_id} was not found!")

        c_m_assignment_manager.delete_item(public_id)

        return DeleteSingleResponse(to_delete_control_measure_assignment).make_response()
    except HTTPException as http_err:
        raise http_err
    except ControlMeasureAssignmentManagerDeleteError as err:
        LOGGER.error(
            "[delete_isms_control_measure_assignment] ControlMeasureAssignmentManagerDeleteError: %s",
            err,
            exc_info=True
        )
        abort(400, f"Failed to delete the ControlMeasure Assignment with ID:{public_id}!")
    except ControlMeasureAssignmentManagerGetError as err:
        LOGGER.error(
            "[delete_isms_control_measure_assignment] ControlMeasureAssignmentManagerGetError: %s",
            err,
            exc_info=True
        )
        abort(400, f"Failed to retrieve the ControlMeasure Assignment with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error(
            "[delete_isms_control_measure_assignment] Exception: %s. Type: %s", err, type(err),
            exc_info=True
        )
        abort(500,
            f"An internal server error occured while deleting the ControlMeasure Assignment with ID: {public_id}!"
        )
