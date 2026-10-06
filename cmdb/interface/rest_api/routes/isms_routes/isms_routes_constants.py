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
Shared constants for the ISMS REST routes
"""
from typing import NamedTuple

from cmdb.utils import BaseStrEnum
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #

# Maximum number of entries allowed for the bounded ISMS scale entities (IsmsImpact, IsmsLikelihood);
# the scales are kept small to keep risk evaluations consistent and manageable
MAX_ISMS_SCALE_ENTRIES: int = 6

# Maximum number of IsmsRiskClasses that may be created
MAX_ISMS_RISK_CLASSES: int = 10


class IsmsEntityLabel(NamedTuple):
    """How an ISMS entity is named in the messages its routes answer"""
    singular: str
    plural: str


CONTROL_MEASURE_LABEL: IsmsEntityLabel = IsmsEntityLabel('ControlMeasure', 'ControlMeasures')
CONTROL_MEASURE_ASSIGNMENT_LABEL: IsmsEntityLabel = IsmsEntityLabel(
    'ControlMeasureAssignment', 'ControlMeasureAssignments',
)
IMPACT_LABEL: IsmsEntityLabel = IsmsEntityLabel('Impact', 'Impacts')
IMPACT_CATEGORY_LABEL: IsmsEntityLabel = IsmsEntityLabel('ImpactCategory', 'ImpactCategories')
LIKELIHOOD_LABEL: IsmsEntityLabel = IsmsEntityLabel('Likelihood', 'Likelihoods')
PROTECTION_GOAL_LABEL: IsmsEntityLabel = IsmsEntityLabel('ProtectionGoal', 'ProtectionGoals')
RISK_LABEL: IsmsEntityLabel = IsmsEntityLabel('Risk', 'Risks')
RISK_ASSESSMENT_LABEL: IsmsEntityLabel = IsmsEntityLabel('RiskAssessment', 'RiskAssessments')
RISK_CLASS_LABEL: IsmsEntityLabel = IsmsEntityLabel('RiskClass', 'RiskClasses')
RISK_MATRIX_LABEL: IsmsEntityLabel = IsmsEntityLabel('RiskMatrix', 'RiskMatrices')
THREAT_LABEL: IsmsEntityLabel = IsmsEntityLabel('Threat', 'Threats')
VULNERABILITY_LABEL: IsmsEntityLabel = IsmsEntityLabel('Vulnerability', 'Vulnerabilities')


class IsmsManagerErrorMessage(BaseStrEnum):
    """
    The 400 an ISMS route answers when its manager fails, one template per operation

    ``{entity}`` and ``{entities}`` are an IsmsEntityLabel's singular and plural, filled by
    ``isms_routes_helper.manager_error_messages``. ``{public_id}`` is left for ``handle_manager_errors``
    to fill from the route's own argument
    """
    INSERT = "Failed to insert the new {entity} in the database!"
    INSERT_DUPLICATE = "Failed to insert the duplicated {entity} in the database!"
    GET_CREATED = "Failed to retrieve the created {entity} from the database!"
    GET = "Failed to retrieve the {entity} with ID: {public_id} from the database!"
    ITERATE = "Failed to retrieve {entities} from the database!"
    UPDATE = "Failed to update the {entity} with ID: {public_id}!"
    DELETE = "Failed to delete the {entity} with ID: {public_id}!"
    USED_BY_RISKS = "The {entity} with ID: {public_id} can not be deleted because it is used by Risks!"
    BULK_USAGE = "Failed to determine which {entities} are still in use!"
    BULK_DELETE = "Failed to delete one of the requested {entities}!"


# The 400 a create answers once its entity already holds the maximum number of entries; filled with the
# cap and the entity's plural label
ISMS_CAP_REACHED_MSG: str = "Only a maximum of {cap} {entity_label} can be created!"
ISMS_LIKELIHOODS_LABEL: str = LIKELIHOOD_LABEL.plural
ISMS_IMPACTS_LABEL: str = IMPACT_LABEL.plural
ISMS_RISK_CLASSES_LABEL: str = RISK_CLASS_LABEL.plural

# Minimum number of configured entries per ISMS section before it counts as "ready" in the setup
# status reported by GET /isms/config/status
MIN_CONFIGURED_RISK_CLASSES: int = 3
MIN_CONFIGURED_LIKELIHOODS: int = 3
MIN_CONFIGURED_IMPACTS: int = 3
MIN_CONFIGURED_IMPACT_CATEGORIES: int = 1

class IsmsConfigStatusKey(BaseStrEnum):
    """
    The sections of the readiness report answered by GET /isms/config/status

    Response keys, not document keys: some share a spelling with a document key (`impacts`,
    `risk_matrix`) but name a configuration section, so they are kept apart from the model enums
    """
    RISK_CLASSES = 'risk_classes'
    LIKELIHOODS = 'likelihoods'
    IMPACTS = 'impacts'
    IMPACT_CATEGORIES = 'impact_categories'
    RISK_MATRIX = 'risk_matrix'


class BulkItemResultKey(BaseStrEnum):
    """The keys of one per-item entry in an ISMS bulk-update response"""
    PUBLIC_ID = 'public_id'
    STATUS = 'status'


class BulkItemStatus(BaseStrEnum):
    """The outcome of one item in an ISMS bulk-update response; a request that answers at all wrote every item"""
    SUCCESS = 'success'


# Most items one ISMS bulk update may carry when its entity has no cap of its own (IsmsImpactCategory); the
# RiskClasses are bounded by MAX_ISMS_RISK_CLASSES instead
MAX_ISMS_BULK_UPDATE_ITEMS: int = 5000

# The 400s of an ISMS bulk update: the body as a whole, then the items. Every refusal is decided before
# anything is written, and an item is named by its position in the list and, when it has one, its id
BULK_UPDATE_NOT_A_LIST_MSG: str = "The request body must be a list of {entities}!"
BULK_UPDATE_TOO_MANY_ITEMS_MSG: str = "At most {max_items} {entities} can be updated at once, but {count} were sent!"
BULK_UPDATE_INVALID_ITEMS_MSG: str = "No {entities} were updated, because some items are invalid: {reasons}"
BULK_UPDATE_DUPLICATE_IDS_MSG: str = "No {entities} were updated, because these ids are sent more than once: {ids}"
BULK_UPDATE_NOT_FOUND_MSG: str = "No {entities} were updated, because these ids do not exist: {ids}"
BULK_UPDATE_UNDO_INCOMPLETE_MSG: str = (
    "Updating the {entities} failed part-way, and these writes could not be undone: {{residue}}"
)
BULK_ITEM_NOT_AN_OBJECT_REASON: str = "item #{index} is not an object"
BULK_ITEM_INVALID_ID_REASON: str = "item #{index} has no integer public_id"
BULK_ITEM_SCHEMA_REASON: str = "item #{index} (public_id {public_id}): {errors}"
BULK_ITEM_REASON_SEPARATOR: str = " | "

# Response keys shared by the ISMS bulk-delete routes (ControlMeasure, Vulnerability, Threat): the ids
# that were deleted, and the ids that were skipped because they are still referenced elsewhere
ISMS_BULK_DELETE_DELETED_KEY: str = 'successfully'
ISMS_BULK_DELETE_IN_USE_KEY: str = 'in_use'

# Extra response keys of the Risk bulk-delete route: how many downstream RiskAssessments and their
# ControlMeasureAssignments the cascade removed alongside the deleted Risks
RISK_BULK_DELETED_RA_KEY: str = 'deleted_risk_assessments'
RISK_BULK_DELETED_CMA_KEY: str = 'deleted_control_measure_assignments'

# Fields an IsmsRiskAssessment must carry with a real value on every write path (create / update /
# duplicate). This mirrors what the frontend form marks as required, so the API refuses exactly the
# payloads the UI refuses - the remaining fields belong to later lifecycle stages (treatment, audit)
# and stay optional. Four of them are already non-nullable in the Cerberus schema; 'risk_owner_id' is
# nullable there, which is why the rule is enforced in one explicit place instead of relying on the
# schema's per-field flags
REQUIRED_RISK_ASSESSMENT_FIELDS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_ID.value,
    RiskAssessmentKey.OBJECT_ID_REF_TYPE.value,
    RiskAssessmentKey.OBJECT_ID.value,
    RiskAssessmentKey.RISK_OWNER_ID.value,
    RiskAssessmentKey.RISK_ASSESSMENT_DATE.value,
)


# Server error (HTTP 500) when a RiskAssessment write failed part-way and undoing what it had already written
# did not finish either: the named documents are left as the failed request made them and need a look by hand
RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG: str = (
    "Writing the RiskAssessment failed, and undoing what it had already written did not finish. "
    "These writes are still in effect and have to be checked by hand: {residue}"
)


# Refusal (HTTP 400) for an IsmsControlMeasureAssignment naming IsmsControlMeasures that do not exist, formatted
# with the sorted unknown ids
UNKNOWN_CONTROL_MEASURES_MSG: str = "Unknown ControlMeasure(s) referenced: {unknown}!"

# Refusals (HTTP 400) for a person reference that cannot be resolved at all: its value is not a public_id, or its
# '_ref_type' sibling names neither a CmdbPerson nor a CmdbPersonGroup. Formatted with the reference key and the
# offending value
INVALID_PERSON_REFERENCE_ID_MSG: str = "The '{key}' reference must be a public_id, got {value!r}!"
UNKNOWN_PERSON_REFERENCE_TYPE_MSG: str = (
    "The '{key}' reference names no known reference type: {value!r} (allowed: {allowed})!"
)

# The 400 a write answers when looking up the documents it references fails, formatted with what they are
REFERENCE_LOOKUP_FAILED_MSG: str = "Failed to look up the referenced {label} IDs in the database!"


class AssignmentDiffKey(BaseStrEnum):
    """The keys of the ControlMeasureAssignment diff a RiskAssessment update carries"""
    CREATED = 'created'
    UPDATED = 'updated'
    DELETED = 'deleted'


# Refusals (HTTP 400) of the ControlMeasureAssignments a RiskAssessment write carries. A create takes a list, an
# update the AssignmentDiffKey object; every entry is judged by the ControlMeasureAssignment write schema
ASSIGNMENTS_NOT_A_LIST_MSG: str = (
    "'control_measure_assignments' of a new RiskAssessment must be a list of ControlMeasureAssignments!"
)
ASSIGNMENTS_NOT_A_DIFF_MSG: str = (
    "'control_measure_assignments' of a RiskAssessment update must be an object of the lists {keys}!"
)
ASSIGNMENT_ENTRY_NOT_AN_OBJECT_MSG: str = "ControlMeasureAssignment {position} must be an object!"
ASSIGNMENT_ENTRY_INVALID_MSG: str = "ControlMeasureAssignment {position} is invalid: {errors}"
ASSIGNMENT_ID_INVALID_MSG: str = (
    "ControlMeasureAssignment {position} needs the integer 'public_id' of a stored assignment, not {value!r}!"
)
ASSIGNMENT_CONTROL_MEASURE_DUPLICATE_MSG: str = (
    "A ControlMeasure can be assigned to a RiskAssessment only once - more than once: {ids}!"
)
ASSIGNMENT_ALREADY_ASSIGNED_MSG: str = (
    "ControlMeasure ID:{control_measure_id} is already assigned to RiskAssessment ID:{risk_assessment_id}!"
)
