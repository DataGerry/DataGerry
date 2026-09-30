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
Implementation of all API routes for the IsmsControlMeasureAssignments
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

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
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey

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
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_ASSIGNMENT_LABEL,
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
)

from cmdb.errors.manager.control_measure_assignment_manager import (
    ControlMeasureAssignmentManagerInsertError,
    ControlMeasureAssignmentManagerGetError,
    ControlMeasureAssignmentManagerUpdateError,
    ControlMeasureAssignmentManagerDeleteError,
    ControlMeasureAssignmentManagerIterationError,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id, update_item_from_payload
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

control_measure_assignment_blueprint = APIBlueprint('control_measure_assignment', __name__)


def build_cma_summary(
    risk_assessment: dict[str, Any] | None,
    risks: dict[int, dict[str, Any]],
    object_map: dict[int, dict[str, Any]],
    object_summaries: dict[int, str],
    types_map: dict[int, dict[str, Any]],
    object_groups: dict[int, str],
) -> str | None:
    """
    Builds the display summary for a ControlMeasureAssignment from its RiskAssessment.

    The RiskAssessment references its risk and either a single CmdbObject or a CmdbObjectGroup
    (discriminated by object_id_ref_type); the summary combines the assessment id, the risk name and
    the referenced object's summary line (+ type label) or the object group's name. All lookups are
    served from the pre-fetched maps, so this stays a pure, database-free helper.

    Args:
        risk_assessment (dict[str, Any] | None): The RiskAssessment referenced by the assignment
        risks (dict[int, dict[str, Any]]): risk_id -> IsmsRisk document
        object_map (dict[int, dict[str, Any]]): object public_id -> CmdbObject document
        object_summaries (dict[int, str]): object public_id -> summary line
        types_map (dict[int, dict[str, Any]]): type public_id -> CmdbType document
        object_groups (dict[int, str]): object group public_id -> group name

    Returns:
        str | None: The composed summary, or None when the assignment has no RiskAssessment
    """
    if not risk_assessment:
        return None

    ra_id = risk_assessment.get(RiskAssessmentKey.PUBLIC_ID.value, '')
    risk_name = risks.get(risk_assessment.get(RiskAssessmentKey.RISK_ID.value), {}).get(RiskKey.NAME.value, '')
    obj_summary = ''

    if risk_assessment.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) == ObjectReferenceType.OBJECT:
        obj_id = risk_assessment.get(RiskAssessmentKey.OBJECT_ID.value)
        summary_line = object_summaries.get(obj_id, '')
        obj = object_map.get(obj_id)
        type_label = ''

        if obj and obj.get('type_id'):
            type_obj = types_map.get(obj['type_id'])
            type_label = f"{type_obj['label']}" if type_obj and 'label' in type_obj else ''

        obj_summary = f"{summary_line} ({type_label})"
    elif risk_assessment.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) == ObjectReferenceType.OBJECT_GROUP:
        obj_summary = object_groups.get(risk_assessment.get(RiskAssessmentKey.OBJECT_ID.value), '')

    return f"#{ra_id} - {risk_name} @ {obj_summary}"

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@control_measure_assignment_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.add')
@control_measure_assignment_blueprint.validate(build_write_schema(IsmsControlMeasureAssignment.SCHEMA))
@handle_route_errors("while creating the ControlMeasure Assignment")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_ASSIGNMENT_LABEL, {
    ControlMeasureAssignmentManagerInsertError: IsmsManagerErrorMessage.INSERT,
    ControlMeasureAssignmentManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
}))
def insert_isms_control_measure_assignment(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsControlMeasureAssignment into the database

    Args:
        data (IsmsControlMeasureAssignment.SCHEMA): Data of the IsmsControlMeasureAssignment which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the insert or the read-back of the created ControlMeasureAssignment fails, 500 when
            the created ControlMeasureAssignment cannot be found afterwards or on an unexpected error

    Returns:
        InsertSingleResponse: The new IsmsControlMeasureAssignment and its public_id
    """
    c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                     )

    missing_control_measures = c_m_assignment_manager.get_missing_control_measure_ids([data])
    if missing_control_measures:
        abort(400, f"Unknown ControlMeasure(s) referenced: {sorted(missing_control_measures)}!")

    result_id = c_m_assignment_manager.insert_item(data)

    created_control_measure_assignment: dict[str, Any] = require_created_item(
        c_m_assignment_manager.get_item(result_id, as_dict=True), CONTROL_MEASURE_ASSIGNMENT_LABEL,
    )

    return InsertSingleResponse(created_control_measure_assignment, result_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@control_measure_assignment_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.view')
@control_measure_assignment_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving ControlMeasureAssignments")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_ASSIGNMENT_LABEL, {
    ControlMeasureAssignmentManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_control_measure_assignments(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsControlMeasureAssignments

    Args:
        params (CollectionParameters): Filter for requested IsmsControlMeasureAssignments
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the IsmsControlMeasureAssignments matching the CollectionParameters
    """
    # This route joins six collections (assignment/assessment/risk/object/type/group) to enrich the
    # response, so the number of lookup maps legitimately exceeds the default local-variable limit
    # pylint: disable=too-many-locals
    body = request_wants_body()

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
        ra[RiskAssessmentKey.PUBLIC_ID.value]: ra for ra in risk_assessment_manager.find_all(
            criteria={RiskAssessmentKey.PUBLIC_ID.value: {'$in': list(ra_ids)}}
        )
    }

    # Extract all risk_ids and object/object_group ids
    risk_ids = set()
    object_ids = set()
    object_group_ids = set()

    for ra in ra_map.values():
        if ra.get(RiskAssessmentKey.RISK_ID.value):
            risk_ids.add(ra[RiskAssessmentKey.RISK_ID.value])
        if ra.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) == ObjectReferenceType.OBJECT:
            object_ids.add(ra.get(RiskAssessmentKey.OBJECT_ID.value))
        elif ra.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) == ObjectReferenceType.OBJECT_GROUP:
            object_group_ids.add(ra.get(RiskAssessmentKey.OBJECT_ID.value))

    # Fetch required details
    risks = {
        risk[RiskKey.PUBLIC_ID.value]: risk
        for risk in risk_manager.get_many_from_other_collection(
            IsmsRisk.COLLECTION,
            public_id={'$in': list(risk_ids)}
        )
    }

    # Fetch the referenced objects once (bulk) and reuse the docs for the summary lines, so the
    # enrichment issues a couple of bulk queries instead of two per-object lookups
    object_docs = objects_manager.find_objects(
        {'public_id': {'$in': list(object_ids)}}, as_dict=True
    ) if object_ids else []
    object_map = {obj['public_id']: obj for obj in object_docs}
    object_summaries = objects_manager.get_summary_lines_lookup(
        list(object_ids), object_docs=object_docs
    ) if object_ids else {}

    # Collect type_ids from object_map
    type_ids = {obj.get('type_id') for obj in object_map.values() if obj.get('type_id')}

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
        summary = build_cma_summary(
            ra_map.get(cma.risk_assessment_id), risks, object_map, object_summaries, types_map, object_groups
        )
        cma_dict = IsmsControlMeasureAssignment.to_json(cma)
        cma_dict['naming'] = {'cma_summary': summary}
        cma_list.append(cma_dict)

    api_response = GetMultiResponse(cma_list,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    body)

    return api_response.make_response()


@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.view')
@handle_route_errors("while retrieving the ControlMeasure Assignment with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_ASSIGNMENT_LABEL, {
    ControlMeasureAssignmentManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_control_measure_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsControlMeasureAssignment
    """
    c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                     )

    requested_control_measure_assignment = get_item_or_404(
                                                c_m_assignment_manager, public_id,
                                                f"The ControlMeasure Assignment with ID:{public_id} was not found!"
                                            )

    return GetSingleResponse(requested_control_measure_assignment,
                             body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.edit')
@control_measure_assignment_blueprint.validate(build_write_schema(IsmsControlMeasureAssignment.SCHEMA))
@handle_route_errors("while updating the ControlMeasure Assignment with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_ASSIGNMENT_LABEL, {
    ControlMeasureAssignmentManagerGetError: IsmsManagerErrorMessage.GET,
    ControlMeasureAssignmentManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
}))
def update_isms_control_measure_assignment(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment which should be updated
        data (IsmsControlMeasureAssignment.SCHEMA): New IsmsControlMeasureAssignment data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the IsmsControlMeasureAssignment
    """
    c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                     )

    get_item_or_404(c_m_assignment_manager, public_id,
                    f"The ControlMeasure Assignment with ID:{public_id} was not found!", as_dict=False)

    # The URL owns the identity: a body public_id would otherwise be $set onto the document

    pin_public_id(data, public_id)

    stored: dict[str, Any] = update_item_from_payload(
        c_m_assignment_manager, public_id, IsmsControlMeasureAssignment, data,
    )

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@control_measure_assignment_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@control_measure_assignment_blueprint.protect(auth=True, right='base.isms.controlMeasureAssignment.delete')
@handle_route_errors("while deleting the ControlMeasure Assignment with ID: {public_id}")
@handle_manager_errors(manager_error_messages(CONTROL_MEASURE_ASSIGNMENT_LABEL, {
    ControlMeasureAssignmentManagerDeleteError: IsmsManagerErrorMessage.DELETE,
    ControlMeasureAssignmentManagerGetError: IsmsManagerErrorMessage.GET,
}))
def delete_isms_control_measure_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsControlMeasureAssignment

    Args:
        public_id (int): public_id of the IsmsControlMeasureAssignment which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsControlMeasureAssignment data
    """
    c_m_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                     )

    to_delete_control_measure_assignment = get_item_or_404(
                                                c_m_assignment_manager, public_id,
                                                f"The ControlMeasure Assignment with ID:{public_id} was not found!",
                                                as_dict=False
                                            )

    c_m_assignment_manager.delete_item(public_id)

    return DeleteSingleResponse(to_delete_control_measure_assignment).make_response()
