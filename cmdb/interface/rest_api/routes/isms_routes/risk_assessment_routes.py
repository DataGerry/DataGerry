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
Implementation of all API routes for the IsmsRiskAssessments
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import (
    RiskAssessmentManager,
    ObjectGroupsManager,
    ObjectsManager,
    ControlMeasureAssignmentManager,
    RiskManager,
    PersonsManager,
    PersonGroupsManager,
)
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.object_group_model import ObjectGroupMode

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

from cmdb.errors.manager.risk_assessment_manager import (
    RiskAssessmentManagerInsertError,
    RiskAssessmentManagerGetError,
    RiskAssessmentManagerUpdateError,
    RiskAssessmentManagerDeleteError,
    RiskAssessmentManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

risk_assessment_blueprint = APIBlueprint('risk_assessment', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@risk_assessment_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.add')
@risk_assessment_blueprint.validate(IsmsRiskAssessment.SCHEMA)
def insert_isms_risk_assessment(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsRiskAssessment into the database

    Args:
        data (IsmsRiskAssessment.SCHEMA): Data of the IsmsRiskAssessment which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new IsmsRiskAssessment and its public_id
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user
                                                                         )
        cm_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                       )
        try:
            data['costs_for_implementation'] = float(f"{float(data['costs_for_implementation']):.2f}")
        except Exception:
            abort(400, "The 'Cost for Implementation' could not be converted to a float!")

        cm_assignments = data.pop('control_measure_assignments')

        result_id: int = risk_assessment_manager.insert_item(data)

        # Create all provided ControlMeasureAssignments if there are any
        if cm_assignments:
            for cma in cm_assignments:
                cma['risk_assessment_id'] = result_id

                cm_assignment_manager.insert_item(cma)

        created_risk_assessment = risk_assessment_manager.get_item(result_id, as_dict=True)

        if not created_risk_assessment:
            abort(404, "Could not retrieve the created RiskAssessment from the database!")

        return InsertSingleResponse(created_risk_assessment, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskAssessmentManagerInsertError as err:
        LOGGER.error("[insert_isms_risk_assessment] RiskAssessmentManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new RiskAssessment in the database!")
    except RiskAssessmentManagerGetError as err:
        LOGGER.error("[insert_isms_risk_assessment] RiskAssessmentManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created RiskAssessment from the database!")
    except Exception as err:
        LOGGER.error("[insert_isms_risk_assessment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the RiskAssessment!")


@risk_assessment_blueprint.route('/duplicate/<string:duplicate_mode>/<string:public_ids>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.add')
@risk_assessment_blueprint.validate(IsmsRiskAssessment.SCHEMA)
def duplicate_isms_risk_assessment(
    data: dict[str, Any],
    request_user: CmdbUser,
    duplicate_mode: str,
    public_ids: str
) -> Response:
    """
    HTTP `POST` route to duplicate an IsmsRiskAssessment into the database

    Args:
        data (IsmsRiskAssessment.SCHEMA): Data of the IsmsRiskAssessment which should be inserted
        request_user (CmdbUser): User requesting this data
        duplicate_mode (str): Three possible cases: risk, object or object_group
        public_ids (str): The comma separated public_ids of the IsmsRisks, CmdbObjects or CmdbObjectGroups
                          referenced in `duplicate_mode` which should be duplicated. Example '1,3,4,5'

    Returns:
        DefaultResponse: All created public_ids of IsmsRiskAssessments
    """
    try:
        duplicate_modes = ('object','risk', 'object_group')

        if duplicate_mode not in duplicate_modes:
            abort(400, f"Invalid duplication target: {duplicate_mode}. Allowed: {', '.join(duplicate_modes)}!")

        copy_cma = request.args.get('copy_cma', 'true').lower() == 'true'

        # Extract the public_id
        initial_risk_assessment_id = data.pop('public_id', None)

        if not initial_risk_assessment_id:
            abort(400, "Missing 'public_id' of the source RiskAssessment in request body!")

        target_ids = [int(pid.strip()) for pid in public_ids.split(',') if pid.strip().isdigit()]

        if not target_ids:
            abort(400, "No valid public_ids were provided for duplication.")

        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
            ManagerType.RISK_ASSESSMENT, request_user
        )

        if copy_cma:
            original_assignments = risk_assessment_manager.get_many_from_other_collection(
                                                                IsmsControlMeasureAssignment.COLLECTION,
                                                                risk_assessment_id=initial_risk_assessment_id
                                                            )
        else:
            original_assignments = []

        created_risk_assessment_ids = []

        for target_id in target_ids:
            new_data = data.copy()

            if duplicate_mode == "risk":
                new_data['risk_id'] = target_id
            elif duplicate_mode == "object":
                if new_data.get('object_id_ref_type') != "OBJECT":
                    abort(400, "object_id_ref_type must be 'OBJECT' to duplicate in object mode.")
                new_data['object_id'] = target_id
            elif duplicate_mode == "object_group":
                if new_data.get('object_id_ref_type') != "OBJECT_GROUP":
                    abort(400, "object_id_ref_type must be 'OBJECT_GROUP' to duplicate in object_group mode.")
                new_data['object_id'] = target_id

            new_risk_assessment_id = risk_assessment_manager.insert_item(new_data)
            created_risk_assessment_ids.append(new_risk_assessment_id)

            if copy_cma:
                cma_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                    ManagerType.CONTROL_MEASURE_ASSIGNMENT, request_user
                )

                for assignment in original_assignments:
                    new_assignment = assignment.copy()
                    new_assignment.pop('public_id', None)
                    new_assignment['risk_assessment_id'] = new_risk_assessment_id
                    cma_manager.insert_item(new_assignment)

        return DefaultResponse(created_risk_assessment_ids).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskAssessmentManagerInsertError as err:
        LOGGER.error("[duplicate_isms_risk_assessment] RiskAssessmentManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the duplicated RiskAssessment in the database!")
    except Exception as err:
        LOGGER.error("[duplicate_isms_risk_assessment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while duplicating the RiskAssessment!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@risk_assessment_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.view')
@risk_assessment_blueprint.parse_collection_parameters()
def get_isms_risk_assessments(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsRiskAssessments

    Args:
        params (CollectionParameters): Filter for requested IsmsRiskAssessments
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsRiskAssessments matching the CollectionParameters
    """
    try:
        body: bool = request.method == 'HEAD'

        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
            ManagerType.RISK_ASSESSMENT,
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
        risk_manager: RiskManager = ManagerProvider.get_manager(ManagerType.RISK, request_user)
        persons_manager: PersonsManager = ManagerProvider.get_manager(
            ManagerType.PERSON, request_user
        )
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(
            ManagerType.PERSON_GROUP,
            request_user
        )

        # Add RiskAssessments from ObjectGroups
        # # STEP 1: Extract object_id from the fixed filter
        original_filter = params.filter or {}
        clauses = original_filter.get('$and', [])
        object_id = None
        ref_type = None

        for clause in clauses:
            if 'object_id' in clause:
                object_id = clause['object_id']

            if 'object_id_ref_type' in clause:
                ref_type = clause['object_id_ref_type']

        # STEP 2: Enhance the filter if object_id was found
        if object_id is not None and ref_type == 'OBJECT':
            target_object = objects_manager.get_object(object_id)

            if target_object is not None:
                type_id = target_object['type_id']

                # Find all STATIC groups containing this CmdbObject
                static_groups = object_groups_manager.find(criteria={
                    'group_type': ObjectGroupMode.STATIC,
                    'assigned_ids': object_id
                })

                static_group_ids = [g['public_id'] for g in static_groups]

                # Find all DYNAMIC groups that include this CmdbType
                dynamic_groups = object_groups_manager.find(criteria={
                    'group_type': ObjectGroupMode.DYNAMIC,
                    'assigned_ids': type_id
                })
                dynamic_group_ids = [g['public_id'] for g in dynamic_groups]

                all_group_ids = static_group_ids + dynamic_group_ids

                # STEP 3: Build enhanced filter
                params.filter = {
                    '$or': [
                        {'$and': [{'object_id_ref_type': ref_type}, {'object_id': object_id}]},
                        {'$and': [{'object_id_ref_type': 'OBJECT_GROUP'}, {'object_id': {'$in': all_group_ids}}]}
                    ]
                }

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[IsmsRiskAssessment] = risk_assessment_manager.iterate_items(builder_params)
        risk_assessments = iteration_result.results

        # Prepare bulk fetch mappings
        risk_ids = set()
        object_group_ids = set()
        object_ids = set()
        person_ids = set()
        responsible_person_ids = set()
        responsible_person_group_ids = set()

        for ra in risk_assessments:
            if ra.risk_id:
                risk_ids.add(ra.risk_id)
            if ra.object_id_ref_type == 'OBJECT_GROUP':
                object_group_ids.add(ra.object_id)
            if ra.object_id_ref_type == 'OBJECT':
                object_ids.add(ra.object_id)
            if isinstance(ra.interviewed_persons, list) and len(ra.interviewed_persons) > 0:
                person_ids.update(ra.interviewed_persons)
            if ra.responsible_persons_id:
                if ra.responsible_persons_id_ref_type == 'PERSON':
                    responsible_person_ids.add(ra.responsible_persons_id)
                elif ra.responsible_persons_id_ref_type == 'PERSON_GROUP':
                    responsible_person_group_ids.add(ra.responsible_persons_id)

        # Bulk fetch metadata
        risks = {
            r['public_id']: r['name'] for r in
            risk_manager.find_all(criteria={'public_id': {'$in': list(risk_ids)}})
        }
        object_groups = {
            g['public_id']: g['name'] for g in
            object_groups_manager.find_all(criteria={'public_id': {'$in': list(object_group_ids)}})
        }
        persons = {}
        if person_ids:
            persons = {
                p['public_id']: p['display_name'] for p in
                persons_manager.find_all(criteria={'public_id': {'$in': list(person_ids)}})
            }

        responsible_persons = {}
        if responsible_person_ids:
            responsible_persons = {
                p['public_id']: p['display_name'] for p in
                persons_manager.find_all(criteria={'public_id': {'$in': list(responsible_person_ids)}})
            }
        responsible_person_groups = {}
        if responsible_person_group_ids:
            responsible_person_groups = {
                g['public_id']: g['name'] for g in
                person_groups_manager.find_all(criteria={'public_id': {'$in': list(responsible_person_group_ids)}})
            }

        # Add naming info
        risk_assessments_list = []
        for ra in risk_assessments:
            naming = {
                'risk_id_name': risks.get(ra.risk_id),
                'object_group_id_name': None,
                'object_id_name': None,
                'interviewed_persons_names': None,
                'responsible_persons_id_name': None,
            }

            if ra.object_id_ref_type == 'OBJECT_GROUP':
                naming['object_group_id_name'] = object_groups.get(ra.object_id)

            if ra.object_id_ref_type == 'OBJECT':
                naming['object_id_name'] = objects_manager.get_summary_line(ra.object_id)

            if ra.interviewed_persons:
                naming['interviewed_persons_names'] = [
                    persons[pid] for pid in ra.interviewed_persons if pid in persons
                ] or None

            if ra.responsible_persons_id:
                if ra.responsible_persons_id_ref_type == 'PERSON':
                    naming['responsible_persons_id_name'] = responsible_persons.get(ra.responsible_persons_id)
                elif ra.responsible_persons_id_ref_type == 'PERSON_GROUP':
                    naming['responsible_persons_id_name'] = responsible_person_groups.get(ra.responsible_persons_id)

            ra_json = IsmsRiskAssessment.to_json(ra)
            ra_json['naming'] = naming
            risk_assessments_list.append(ra_json)

        api_response = GetMultiResponse(risk_assessments_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except RiskAssessmentManagerIterationError as err:
        LOGGER.error("[get_isms_risk_assessments] RiskAssessmentManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve RiskAssessments from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_assessments] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving RiskAssessments!")


@risk_assessment_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.view')
def get_isms_risk_assessment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsRiskAssessment

    Args:
        public_id (int): public_id of the IsmsRiskAssessment
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsRiskAssessment
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user
                                                                         )

        requested_risk_assessment = risk_assessment_manager.get_item(public_id, as_dict=True)

        if requested_risk_assessment:
            return GetSingleResponse(requested_risk_assessment, body = request.method == 'HEAD').make_response()

        abort(404, f"The RiskAssessment with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except RiskAssessmentManagerGetError as err:
        LOGGER.error("[get_isms_risk_assessment] RiskAssessmentManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskAssessment with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_assessment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the RiskAssessment with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@risk_assessment_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.edit')
@risk_assessment_blueprint.validate(IsmsRiskAssessment.SCHEMA)
def update_isms_risk_assessment(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsRiskAssessment

    Args:
        public_id (int): public_id of the IsmsRiskAssessment which should be updated
        data (IsmsRiskAssessment.SCHEMA): New IsmsRiskAssessment data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsRiskAssessment
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user
                                                                         )
        cm_assignment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                            request_user
                                                                       )

        to_update_risk_assessment = risk_assessment_manager.get_item(public_id)

        if not to_update_risk_assessment:
            abort(404, f"The RiskAssessment with ID:{public_id} was not found!")

        try:
            data['costs_for_implementation'] = float(f"{float(data['costs_for_implementation']):.2f}")
        except Exception:
            abort(400, "The 'Cost for Implementation' could not be converted to a float!")

        # Handle ControlMeasureAssignments
        cm_assignments: dict = data.pop('control_measure_assignments', [])

        # Handle created ControlMeasureAssignments
        if cm_assignments.get('created'):
            created_cm_assignments: list[dict] = cm_assignments.get('created')

            for created_cma in created_cm_assignments:
                cm_assignment_manager.insert_item(created_cma)

        # Handle updated ControlMeasureAssignments
        if cm_assignments.get('updated'):
            update_cm_assignments: list[dict] = cm_assignments.get('updated')

            for updated_cma in update_cm_assignments:
                cm_assignment_manager.update_item(updated_cma.get('public_id'),
                                                  IsmsControlMeasureAssignment.from_data(updated_cma))

        # Handle deleted ControlMeasureAssignments
        if cm_assignments.get('deleted'):
            deleted_cma_ids = cm_assignments.get('deleted')

            for deleted_cma_id in deleted_cma_ids:
                cm_assignment_manager.delete_item(deleted_cma_id)

        # Update the actual RiskAssessment
        risk_assessment_manager.update_item(public_id, IsmsRiskAssessment.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskAssessmentManagerGetError as err:
        LOGGER.error("[update_isms_risk_assessment] RiskAssessmentManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskAssessment with ID: {public_id} from the database!")
    except RiskAssessmentManagerUpdateError as err:
        LOGGER.error("[update_isms_risk_assessment] RiskAssessmentManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the RiskAssessment with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_isms_risk_assessment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the RiskAssessment with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@risk_assessment_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.delete')
def delete_isms_risk_assessment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsRiskAssessment

    Args:
        public_id (int): public_id of the IsmsRiskAssessment which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsRiskAssessment data
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user
                                                                         )

        to_delete_risk_assessment = risk_assessment_manager.get_item(public_id)

        if not to_delete_risk_assessment:
            abort(404, f"The RiskAssessment with ID:{public_id} was not found!")

        risk_assessment_manager.delete_with_followup(public_id)

        return DeleteSingleResponse(to_delete_risk_assessment).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskAssessmentManagerDeleteError as err:
        LOGGER.error("[delete_isms_risk_assessment] RiskAssessmentManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the RiskAssessment with ID:{public_id}!")
    except RiskAssessmentManagerGetError as err:
        LOGGER.error("[delete_isms_risk_assessment] RiskAssessmentManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the RiskAssessment with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_isms_risk_assessment] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the RiskAssessment with ID: {public_id}!")
