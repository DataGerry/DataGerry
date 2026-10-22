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
Implementation of all API routes for the IsmsRiskAssessments
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import RiskAssessmentManager, ControlMeasureAssignmentManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_risk_assessment_constants import CONTROL_MEASURE_ASSIGNMENTS_KEY, RiskAssessmentKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
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
    abort_on_unknown_control_measures,
    coerce_isms_number,
    get_item_or_404,
    guard_required_risk_assessment_fields,
    manager_error_messages,
    require_created_item,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    COPY_CMA_PARAM,
    COSTS_NOT_A_NUMBER_MSG,
    RISK_ASSESSMENT_LABEL,
    RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.assignment_entries_helper import (
    abort_on_duplicate_control_measures,
    assignments_after_update,
    validated_create_payload,
    validated_update_payload,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_naming_helper import (
    RiskAssessmentNamingLookups,
    collect_naming_ids,
    expand_object_scope_filter,
    fetch_naming_lookups,
    named_risk_assessment,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
    PERSON_REFERENCE_LOOKUP_ERRORS,
    PersonReference,
    check_person_references,
    collect_person_references,
    new_person_references,
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

from cmdb.errors.manager.risk_assessment_manager import (
    RiskAssessmentManagerInsertError,
    RiskAssessmentManagerGetError,
    RiskAssessmentManagerUpdateError,
    RiskAssessmentManagerDeleteError,
    RiskAssessmentManagerIterationError,
    RiskAssessmentManagerScaleReadError,
)
from cmdb.interface.rest_api.routes.routes_helper import (
    read_boolean_query_param,
    request_wants_body,
    pin_public_id,
    update_item_from_payload,
    undone_on_failure,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

risk_assessment_blueprint = APIBlueprint('risk_assessment', __name__)


def _coerce_costs_for_implementation(data: dict[str, Any]) -> None:
    """
    Normalises ``data['costs_for_implementation']`` to a 2-decimal float in place

    A ``None`` value is left untouched (the field is nullable per the schema); any other value that
    cannot be converted to a float aborts with 400

    Args:
        data (dict[str, Any]): The request body holding the costs_for_implementation to normalise

    Raises:
        HTTPException: 400 when a value was sent that cannot be converted
    """
    coerce_isms_number(data, RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value, COSTS_NOT_A_NUMBER_MSG, optional=True)


def _assignments_person_references(assignments: list[dict[str, Any]]) -> list[PersonReference]:
    """
    Every person reference of the ControlMeasureAssignments a RiskAssessment write carries

    Args:
        assignments (list[dict[str, Any]]): The assignment payloads

    Returns:
        list[PersonReference]: Their references, in payload order
    """
    return [
        reference
        for assignment in assignments
        for reference in collect_person_references(assignment, CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS)
    ]


# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@risk_assessment_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.add')
@risk_assessment_blueprint.validate(build_write_schema(IsmsRiskAssessment.SCHEMA))
@handle_route_errors("while creating the RiskAssessment")
@handle_manager_errors({**manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerInsertError: IsmsManagerErrorMessage.INSERT,
    RiskAssessmentManagerGetError: IsmsManagerErrorMessage.GET_CREATED,
    RiskAssessmentManagerScaleReadError: IsmsManagerErrorMessage.SCALE_READ,
}), **PERSON_REFERENCE_LOOKUP_ERRORS})
def insert_isms_risk_assessment(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an IsmsRiskAssessment into the database

    The mandatory fields (see REQUIRED_RISK_ASSESSMENT_FIELDS) must all carry a value; the treatment and
    audit blocks belong to later lifecycle stages and stay optional. Every person reference - the assessment's
    and each assignment's - has to resolve in the collection its reference type names. A ``_ref_type`` may be
    null only while its id is: a missing owner is reported as the missing ``risk_owner_id``, a set id beside a
    null ``_ref_type`` as a reference naming no known type

    ``control_measure_assignments`` is a list; each entry is held to the same write schema as
    ``POST /isms/control_measure_assignments/`` (``risk_assessment_id`` is stamped by this route, a sent
    ``public_id`` is dropped and the server assigns one), and one ControlMeasure is assigned once

    Args:
        data (IsmsRiskAssessment.SCHEMA): Data of the IsmsRiskAssessment which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when a required field is missing (every missing field is named), when
            ``control_measure_assignments`` is no list or an entry fails the assignment schema (its position and
            errors are named), when a ControlMeasure is assigned more than once, when an
            unknown ControlMeasure is referenced, when a person reference is not a public_id, names no known
            reference type or names a CmdbPerson / CmdbPersonGroup that does not exist, or when the insert, the
            reference lookup or the read-back of the created RiskAssessment fails; 500 when the created
            RiskAssessment cannot be found afterwards or on an unexpected error. **All-or-nothing:** a failure
            after the RiskAssessment was stored removes it and every assignment stored with it again, and the
            request fails with the error it hit; when that undo cannot finish, the answer is a 500 naming what
            is left behind

    Returns:
        InsertSingleResponse: The new IsmsRiskAssessment and its public_id
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.RISK_ASSESSMENT,
                                                                        request_user
                                                                     )
    cm_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                   )
    # Refuse an incomplete assessment before anything is written
    guard_required_risk_assessment_fields(data)

    _coerce_costs_for_implementation(data)

    # Each assignment judged by the assignment write schema; its public_id is the server's to assign
    cm_assignments: list[dict[str, Any]] = validated_create_payload(data.pop(CONTROL_MEASURE_ASSIGNMENTS_KEY, None))
    abort_on_duplicate_control_measures(cm_assignments)

    # Reject unknown ControlMeasure references before writing anything (no orphaned RiskAssessment)
    abort_on_unknown_control_measures(cm_assignment_manager, cm_assignments)

    # Every person reference - the assessment's own and each assignment's - resolves in the collection its
    # reference type names, before anything is written
    check_person_references(
        collect_person_references(data, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)
        + _assignments_person_references(cm_assignments),
        request_user,
    )

    # Derive maximum_impact / likelihood_value server-side (client-supplied values are not trusted)
    risk_assessment_manager.recalculate_risk_values(data)

    # All-or-nothing by compensation: a failure after the RiskAssessment is stored takes it back out, with
    # every assignment the batch managed to store, and fails with the error it hit
    with undone_on_failure(RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG) as ledger:
        result_id: int = risk_assessment_manager.insert_item(data)
        ledger.inserted(risk_assessment_manager, result_id)

        if cm_assignments:
            for cma in cm_assignments:
                cma[ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value] = result_id

            # Recorded BEFORE the batch: an unordered bulk insert stores the documents that succeed, and a
            # failure does not say which - so the undo removes every assignment of the new RiskAssessment
            ledger.inserted_where(
                cm_assignment_manager, {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: result_id},
            )
            cm_assignment_manager.insert_many_items(cm_assignments)

    created_risk_assessment: dict[str, Any] = require_created_item(
        risk_assessment_manager.get_item(result_id, as_dict=True), RISK_ASSESSMENT_LABEL,
    )

    return InsertSingleResponse(created_risk_assessment, result_id).make_response()


# The DOCUMENT schema, deliberately: on this route the body's `public_id` is not the identity of
# anything being written - it names the SOURCE assessment the duplicates are copied from, and the
# handler pops it. Every other write route here validates the derived request schema
@risk_assessment_blueprint.route('/duplicate/<string:duplicate_mode>/<string:public_ids>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.add')
@risk_assessment_blueprint.validate(IsmsRiskAssessment.SCHEMA)
@handle_route_errors("while duplicating the RiskAssessment")
@handle_manager_errors({**manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerInsertError: IsmsManagerErrorMessage.INSERT_DUPLICATE,
}), **PERSON_REFERENCE_LOOKUP_ERRORS})
def duplicate_isms_risk_assessment(
    data: dict[str, Any],
    request_user: CmdbUser,
    duplicate_mode: str,
    public_ids: str
) -> Response:
    """
    HTTP `POST` route to duplicate an IsmsRiskAssessment into the database

    Every duplicate is built from the submitted source payload, so it has to satisfy the same mandatory
    fields as a create - otherwise one incomplete source would produce a whole batch of incomplete
    assessments - and its person references have to resolve, judged in full as on a create

    Args:
        data (IsmsRiskAssessment.SCHEMA): Data of the IsmsRiskAssessment which should be inserted
        request_user (CmdbUser): User requesting this data
        duplicate_mode (str): Three possible cases: risk, object or object_group
        public_ids (str): The comma separated public_ids of the IsmsRisks, CmdbObjects or CmdbObjectGroups
                          referenced in `duplicate_mode` which should be duplicated. Example '1,3,4,5'

    Raises:
        HTTPException: 400 on an invalid duplication target, a required field missing (every missing
            field is named), a missing source public_id, no valid target public_ids, a
            duplicate_mode that contradicts 'object_id_ref_type', a person reference that does not resolve, or
            a failed insert or reference lookup. **All-or-nothing across every target:**
            a failure on any target removes every duplicate already written, with its assignments; when that
            undo cannot finish, a 500 names what is left behind

    Returns:
        DefaultResponse: All created public_ids of IsmsRiskAssessments
    """
    # Duplicating across three modes with optional CMA copying spans several branches / locals
    # pylint: disable=too-many-locals
    duplicate_modes = ('object','risk', 'object_group')

    if duplicate_mode not in duplicate_modes:
        abort(400, f"Invalid duplication target: {duplicate_mode}. Allowed: {', '.join(duplicate_modes)}!")

    copy_cma: bool = read_boolean_query_param(COPY_CMA_PARAM, default=True)

    # The source payload becomes every duplicate, so it has to satisfy the same required fields
    guard_required_risk_assessment_fields(data)

    # The assignments are copied from the SOURCE assessment's own collection below, so the copy
    # travelling in the payload is redundant - and storing it would put a key outside
    # RiskAssessmentKey into the document, where every response built through the model would hide
    # it while it still occupied the assessment
    data.pop(CONTROL_MEASURE_ASSIGNMENTS_KEY, None)

    # Extract the public_id
    initial_risk_assessment_id = data.pop(RiskAssessmentKey.PUBLIC_ID.value, None)

    if not initial_risk_assessment_id:
        abort(400, "Missing 'public_id' of the source RiskAssessment in request body!")

    target_ids = [int(pid.strip()) for pid in public_ids.split(',') if pid.strip().isdigit()]

    if not target_ids:
        abort(400, "No valid public_ids were provided for duplication.")

    # The duplicate mode depends only on the source payload, not the targets, so validate it once
    source_ref_type = data.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value)
    if duplicate_mode == "object" and source_ref_type != ObjectReferenceType.OBJECT:
        abort(400, "object_id_ref_type must be 'OBJECT' to duplicate in object mode.")
    if duplicate_mode == "object_group" and source_ref_type != ObjectReferenceType.OBJECT_GROUP:
        abort(400, "object_id_ref_type must be 'OBJECT_GROUP' to duplicate in object_group mode.")

    # Every duplicate carries the source payload's person references, so each has to resolve - judged in full,
    # since every duplicate is a new document
    check_person_references(collect_person_references(data, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS), request_user)

    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
        ManagerType.RISK_ASSESSMENT, request_user
    )

    # Fetch the source assignments and the assignment manager once, not per duplicated target
    if copy_cma:
        original_assignments = risk_assessment_manager.get_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            criteria={ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: initial_risk_assessment_id},
        )
        cma_manager: ControlMeasureAssignmentManager | None = ManagerProvider.get_manager(
            ManagerType.CONTROL_MEASURE_ASSIGNMENT, request_user
        )
    else:
        original_assignments = []
        cma_manager = None

    # 'risk' mode retargets the risk_id; 'object'/'object_group' modes retarget the object_id
    target_field = 'risk_id' if duplicate_mode == "risk" else 'object_id'

    created_risk_assessment_ids: list[int] = []

    # All-or-nothing across every target, by compensation: a failure on any target takes back every duplicate
    # already written - so the caller never gets an error while some duplicates silently exist
    with undone_on_failure(RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG) as ledger:
        for target_id in target_ids:
            new_data = data.copy()
            new_data[target_field] = target_id

            new_risk_assessment_id: int = risk_assessment_manager.insert_item(new_data)
            ledger.inserted(risk_assessment_manager, new_risk_assessment_id)
            created_risk_assessment_ids.append(new_risk_assessment_id)

            # Copy the source assignments onto the new RiskAssessment in a single batched insert
            if original_assignments:
                new_assignments = []
                for assignment in original_assignments:
                    new_assignment = assignment.copy()
                    new_assignment.pop(ControlMeasureAssignmentKey.PUBLIC_ID.value, None)
                    new_assignment[ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value] = new_risk_assessment_id
                    new_assignments.append(new_assignment)

                # Recorded BEFORE the batch, which may store part of itself and not say which part
                ledger.inserted_where(
                    cma_manager, {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: new_risk_assessment_id},
                )
                cma_manager.insert_many_items(new_assignments)

    return DefaultResponse(created_risk_assessment_ids).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@risk_assessment_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.view')
@risk_assessment_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving RiskAssessments")
@handle_manager_errors(manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerIterationError: IsmsManagerErrorMessage.ITERATE,
}))
def get_isms_risk_assessments(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple IsmsRiskAssessments

    A filter scoped to one OBJECT (``$and`` of ``{object_id_ref_type: OBJECT}`` and ``{object_id: <int>}``) also
    matches the assessments of every CmdbObjectGroup the object belongs to; the filter's other clauses, the list's
    search among them, still apply (``expand_object_scope_filter``). Every assessment of the page carries a
    ``naming`` block with the display names of what it references, read in one projected query per collection; an
    object of a Type the caller may not READ stays unnamed

    Args:
        params (CollectionParameters): Filter for requested IsmsRiskAssessments
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the assessments could not be iterated; 500 when the scope's object or groups, or a
            name, could not be read, or on an unexpected error

    Returns:
        GetMultiResponse: All the IsmsRiskAssessments matching the CollectionParameters
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
        ManagerType.RISK_ASSESSMENT, request_user,
    )

    params.filter = expand_object_scope_filter(params.filter, request_user)

    builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
    iteration_result: IterationResult[IsmsRiskAssessment] = risk_assessment_manager.iterate_items(builder_params)

    lookups: RiskAssessmentNamingLookups = fetch_naming_lookups(
        collect_naming_ids(iteration_result.results), request_user,
    )

    return GetMultiResponse(
        [named_risk_assessment(risk_assessment, lookups) for risk_assessment in iteration_result.results],
        iteration_result.total,
        params,
        request.url,
        request_wants_body(),
    ).make_response()


@risk_assessment_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.view')
@handle_route_errors("while retrieving the RiskAssessment with ID: {public_id}")
@handle_manager_errors(manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerGetError: IsmsManagerErrorMessage.GET,
}))
def get_isms_risk_assessment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single IsmsRiskAssessment

    Args:
        public_id (int): public_id of the IsmsRiskAssessment
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested IsmsRiskAssessment
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.RISK_ASSESSMENT,
                                                                        request_user
                                                                     )

    requested_risk_assessment = get_item_or_404(risk_assessment_manager, public_id,
                                                 f"The RiskAssessment with ID:{public_id} was not found!")

    return GetSingleResponse(requested_risk_assessment, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@risk_assessment_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.edit')
@risk_assessment_blueprint.validate(build_write_schema(IsmsRiskAssessment.SCHEMA))
@handle_route_errors("while updating the RiskAssessment with ID: {public_id}")
@handle_manager_errors({**manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerGetError: IsmsManagerErrorMessage.GET,
    RiskAssessmentManagerUpdateError: IsmsManagerErrorMessage.UPDATE,
    RiskAssessmentManagerScaleReadError: IsmsManagerErrorMessage.SCALE_READ,
}), **PERSON_REFERENCE_LOOKUP_ERRORS})
def update_isms_risk_assessment(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single IsmsRiskAssessment

    The payload is the whole document (there are no partial-update semantics), so the mandatory fields
    are enforced exactly as on create - an assessment cannot be saved into an incomplete state. The person
    references the update INTRODUCES are resolved - on the assessment, on a created assignment, and on an
    updated assignment against its stored self; a reference the stored document already holds is not judged
    again, so an assessment carrying one that went stale can still be saved

    ``control_measure_assignments`` is the diff ``{created, updated, deleted}``: created and updated entries are
    held to the assignment write schema (an updated one also needs its integer ``public_id``, a created one's is
    dropped), deleted entries are integer ids, and the assessment may hold one ControlMeasure once after the diff

    Args:
        public_id (int): public_id of the IsmsRiskAssessment which should be updated
        data (IsmsRiskAssessment.SCHEMA): New IsmsRiskAssessment data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 when the IsmsRiskAssessment does not exist; 400 when a required field is
            missing (every missing field is named), when the assignment diff is malformed or an entry fails the
            assignment schema, when a ControlMeasure would be assigned more than once, when an unknown
            ControlMeasure is referenced, when a ControlMeasureAssignment does not belong to this
            IsmsRiskAssessment, when a new person reference does not resolve (a set id beside a null ``_ref_type``
            included), or when a read or the reference
            lookup fails - every refusal before anything is written. **All-or-nothing:** a failure in the write
            phase undoes it (created assignments deleted, updated ones restored, deleted ones re-inserted under
            their old ids), and the request fails with the error it hit; when that undo cannot finish, a 500
            names what is left

    Returns:
        UpdateSingleResponse: The new data of the IsmsRiskAssessment
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.RISK_ASSESSMENT,
                                                                        request_user
                                                                     )
    cm_assignment_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.CONTROL_MEASURE_ASSIGNMENT,
                                                                        request_user
                                                                   )

    stored_risk_assessment: dict[str, Any] = get_item_or_404(
        risk_assessment_manager, public_id, f"The RiskAssessment with ID:{public_id} was not found!",
    )

    # Refuse an incomplete assessment before anything is written (the payload is the whole document)
    guard_required_risk_assessment_fields(data)

    _coerce_costs_for_implementation(data)

    # The ControlMeasureAssignment diff (created / updated / deleted), each entry judged by the assignment write
    # schema - a created one's public_id is the server's to assign, an updated one keeps its integer id
    diff = validated_update_payload(data.pop(CONTROL_MEASURE_ASSIGNMENTS_KEY, None))

    # Reject unknown ControlMeasure references (created + updated) before applying any change
    abort_on_unknown_control_measures(cm_assignment_manager, diff.created + diff.updated)

    # The ControlMeasureAssignments actually linked to THIS RiskAssessment, as stored - the ownership rule for
    # every update and delete below, and the snapshot each of them is undone from
    owned_cmas: dict[int, dict[str, Any]] = {}

    if diff.created or diff.updated or diff.deleted:
        owned_cmas = {
            cma[ControlMeasureAssignmentKey.PUBLIC_ID.value]: cma
            for cma in risk_assessment_manager.get_many_from_other_collection(
                IsmsControlMeasureAssignment.COLLECTION,
                criteria={ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: public_id},
            )
        }

    # EVERY refusal before the first write: one RiskAssessment may not mutate another's assignments, and a
    # refusal that arrived after some of the writes had run would report "refused" for a half-applied request
    for cma_id in [updated.get(ControlMeasureAssignmentKey.PUBLIC_ID.value) for updated in diff.updated] \
            + diff.deleted:
        if cma_id not in owned_cmas:
            abort(400, f"ControlMeasureAssignment ID:{cma_id} is not linked to RiskAssessment ID:{public_id}!")

    # One ControlMeasure is assigned to an assessment once - judged on what it holds after the diff
    abort_on_duplicate_control_measures(assignments_after_update(owned_cmas, diff))

    # The person references this update introduces - on the assessment, on a created assignment, on an updated
    # one against its stored self - resolve before anything is written. One already stored is not judged again
    check_person_references(
        new_person_references(data, stored_risk_assessment, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)
        + _assignments_person_references(diff.created)
        + [
            reference
            for updated_cma in diff.updated
            for reference in new_person_references(
                updated_cma,
                owned_cmas[updated_cma.get(ControlMeasureAssignmentKey.PUBLIC_ID.value)],
                CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
            )
        ],
        request_user,
    )

    for updated_cma in diff.updated:
        updated_cma[ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value] = public_id

    updated_models: list[IsmsControlMeasureAssignment] = [
        IsmsControlMeasureAssignment.from_data(updated_cma) for updated_cma in diff.updated
    ]

    # Derive maximum_impact / likelihood_value server-side (client-supplied values are not trusted)
    risk_assessment_manager.recalculate_risk_values(data)

    # The URL owns the identity: a body public_id would otherwise be $set onto the document
    pin_public_id(data, public_id)

    # Built once up front, so a RiskAssessment the model refuses is refused before anything is written
    IsmsRiskAssessment.from_data(data)

    # All-or-nothing by compensation: each write is recorded, and a failure undoes them newest first - a
    # created assignment deleted, an updated one restored from its snapshot, a deleted one re-inserted under its
    # old id. An update or delete is recorded BEFORE it runs: undoing one that did not happen is harmless,
    # missing one that did is not
    with undone_on_failure(RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG) as ledger:
        for created_cma in diff.created:
            created_cma[ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value] = public_id
            ledger.inserted(cm_assignment_manager, cm_assignment_manager.insert_item(created_cma))

        for updated_model in updated_models:
            ledger.updated(cm_assignment_manager, updated_model.public_id, owned_cmas[updated_model.public_id])
            cm_assignment_manager.update_item(updated_model.public_id, updated_model)

        for deleted_cma_id in diff.deleted:
            ledger.deleted(cm_assignment_manager, deleted_cma_id, owned_cmas[deleted_cma_id])
            cm_assignment_manager.delete_item(deleted_cma_id)

        # The RiskAssessment last: once it is written the request has fully happened
        stored: dict[str, Any] = update_item_from_payload(
            risk_assessment_manager, public_id, IsmsRiskAssessment, data,
        )

    return UpdateSingleResponse(stored).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@risk_assessment_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@risk_assessment_blueprint.protect(auth=True, right='base.isms.riskAssessment.delete')
@handle_route_errors("while deleting the RiskAssessment with ID: {public_id}")
@handle_manager_errors(manager_error_messages(RISK_ASSESSMENT_LABEL, {
    RiskAssessmentManagerDeleteError: IsmsManagerErrorMessage.DELETE,
    RiskAssessmentManagerGetError: IsmsManagerErrorMessage.GET,
}))
def delete_isms_risk_assessment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single IsmsRiskAssessment

    The RiskAssessment is deleted first, then its assignments (``delete_with_follow_up``): a failure between
    the two leaves assignments pointing at nothing, which every reader treats as unassigned, rather than a
    surviving RiskAssessment without its assignments

    Args:
        public_id (int): public_id of the IsmsRiskAssessment which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted IsmsRiskAssessment data
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                        ManagerType.RISK_ASSESSMENT,
                                                                        request_user
                                                                     )

    to_delete_risk_assessment = get_item_or_404(risk_assessment_manager, public_id,
                                                f"The RiskAssessment with ID:{public_id} was not found!",
                                                as_dict=False)

    risk_assessment_manager.delete_with_follow_up(public_id)

    return DeleteSingleResponse(to_delete_risk_assessment).make_response()
