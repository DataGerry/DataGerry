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
from cmdb.models.extendable_option_model.option_type_enum import OptionType
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
    GET_SOURCE = "Failed to read the source {entity} of the duplicate from the database!"
    GET = "Failed to retrieve the {entity} with ID: {public_id} from the database!"
    GET_SELECTED = "Failed to read the selected {entities} from the database!"
    ITERATE = "Failed to retrieve {entities} from the database!"
    UPDATE = "Failed to update the {entity} with ID: {public_id}!"
    DELETE = "Failed to delete the {entity} with ID: {public_id}!"
    USED_BY_RISKS = "The {entity} with ID: {public_id} can not be deleted because it is used by Risks!"
    USED_BY_ASSIGNMENTS = "{entity} with ID:{public_id} is not deletable while used by ControlMeasureAssignments!"
    USED_BY_ASSESSMENTS = "{entity} with ID: {public_id} is referenced in RiskAssessments and cannot be deleted!"
    CALCULATION_BASIS_CHECK = "Failed to check whether the calculation basis is already used by another {entity}!"
    NAME_CHECK = "Failed to check whether the name is already used by another {entity}!"
    CAP_CHECK = "Failed to count the existing {entities}!"
    SCALE_READ = "Failed to read the Impact and Likelihood scales the {entity} is calculated from!"
    RISK_READ = "Failed to read the Risks the {entity} names from the database!"
    BULK_USAGE = "Failed to determine which {entities} are still in use!"
    BULK_DELETE = "Failed to delete one of the requested {entities}!"
    CATEGORY_DESCRIPTIONS = "Failed to update the ImpactCategories' descriptions of the {entity}!"
    # A RiskAssessment update's assignment diff: {entity} is the assignment, {public_id} the URL's RiskAssessment -
    # never the assignment's own id. The writes already made are undone before the 400 answers
    ASSIGNMENT_INSERT_UNDONE = (
        "Failed to insert a {entity} of the RiskAssessment with ID: {public_id} - nothing was changed!"
    )
    ASSIGNMENT_UPDATE_UNDONE = (
        "Failed to update a {entity} of the RiskAssessment with ID: {public_id} - nothing was changed!"
    )
    ASSIGNMENT_DELETE_UNDONE = (
        "Failed to delete a {entity} of the RiskAssessment with ID: {public_id} - nothing was changed!"
    )


# The 400 a create answers once its entity already holds the maximum number of entries; filled with the
# cap and the entity's plural label
ISMS_CAP_REACHED_MSG: str = "Only a maximum of {cap} {entity_label} can be created!"
ISMS_LIKELIHOODS_LABEL: str = LIKELIHOOD_LABEL.plural
ISMS_IMPACTS_LABEL: str = IMPACT_LABEL.plural
ISMS_RISK_CLASSES_LABEL: str = RISK_CLASS_LABEL.plural

# The refusals of the ProtectionGoal write routes. NAME_TAKEN is the name pre-check's answer and the unique index's
# when a concurrent write wins the race
PROTECTION_GOAL_NAME_TAKEN_MSG: str = "A ProtectionGoal with the name {name} already exists!"
PROTECTION_GOAL_PREDEFINED_CREATE_MSG: str = "Predefined ProtectionGoals cannot be created via API!"
PROTECTION_GOAL_PREDEFINED_FLAG_MSG: str = "The predefined property of ProtectionGoals cannot be edited!"
PROTECTION_GOAL_PREDEFINED_EDIT_MSG: str = "The predefined ProtectionGoals can not be edited!"
PROTECTION_GOAL_PREDEFINED_DELETE_MSG: str = "The predefined ProtectionGoals cannot be deleted!"
PROTECTION_GOAL_NOT_FOUND_MSG: str = "The ProtectionGoal with ID:{public_id} was not found!"

# Minimum number of configured entries per ISMS section before it counts as "ready" in the setup
# status reported by GET /isms/config/status
MIN_CONFIGURED_RISK_CLASSES: int = 3
MIN_CONFIGURED_LIKELIHOODS: int = 3
MIN_CONFIGURED_IMPACTS: int = 3
MIN_CONFIGURED_IMPACT_CATEGORIES: int = 1

# The 400 of GET /isms/config/status when one of its counts or the RiskMatrix read fails
ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE: str = "Failed to read the ISMS configuration status from the database!"

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

# Most ids one ISMS bulk delete may name; a longer selection is refused before anything is read
MAX_ISMS_BULK_DELETE_ITEMS: int = 5000
BULK_DELETE_TOO_MANY_ITEMS_MSG: str = "At most {max_items} {entities} can be deleted at once, but {count} were sent!"

# The 400 of an Impact or Likelihood write whose calculation_basis another entry of the scale already holds -
# the pre-check's answer, and the unique index's when a concurrent write wins the race
CALCULATION_BASIS_TAKEN_MSG: str = "The calculation basis is already used by another {entity}!"

# The 400 of an Impact or Likelihood write whose calculation_basis is missing or no number
CALCULATION_BASIS_NOT_A_NUMBER_MSG: str = (
    "The calculation basis is either not provided or could not be converted to a float!"
)

# The 400 of a RiskAssessment write whose costs_for_implementation is no number
COSTS_NOT_A_NUMBER_MSG: str = "The 'Cost for Implementation' could not be converted to a float!"

# How many decimals the ISMS write routes keep of a client-supplied number
ISMS_NUMBER_DECIMALS: int = 2

class IsmsWriteAction(BaseStrEnum):
    """What a scale or category write route - or the RiskClass delete - was doing, as its undo's 500 names it"""
    CREATE = "Creating"
    UPDATE = "Updating"
    DELETE = "Deleting"


# Server error (HTTP 500) when an Impact, Likelihood or ImpactCategory write, or a RiskClass delete, failed part-way and
# undoing what it had already written did not finish - filled with an IsmsWriteAction and the entity's singular label
SCALE_WRITE_UNDO_INCOMPLETE_MSG: str = (
    "{action} the {entity} failed part-way, and undoing what it had already written did not finish. "
    "These writes are still in effect and have to be checked by hand: {{residue}}"
)

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
# The 400 of that check when the ControlMeasures could not be read - before anything is written
CONTROL_MEASURE_LOOKUP_FAILED_MSG: str = "Failed to check the referenced ControlMeasures in the database!"
# The 400 of a RiskAssessment update whose stored ControlMeasureAssignments could not be read - before anything is
# written; filled with the RiskAssessment's public_id
OWNED_ASSIGNMENTS_READ_MSG: str = (
    "Failed to read the ControlMeasureAssignments of the RiskAssessment with ID: {public_id} from the database!"
)
# The 400 of a RiskAssessment write naming an IsmsRisk that does not exist - the risk_id of a create / update, the
# body's risk_id or every target of a risk-mode duplicate
UNKNOWN_RISKS_MSG: str = "Unknown Risk(s) referenced: {unknown}!"

# The 400 of a RiskAssessment write whose assessed CmdbObject does not exist OR is of a type the caller may not READ -
# one answer for both, so it says nothing about objects the caller cannot see. The object of a create / of an update
# that changes it, the payload's object of a risk-mode duplicate, every target of an object-mode duplicate
UNKNOWN_ASSESSED_OBJECTS_MSG: str = "Unknown Object(s) referenced: {unknown}!"
# The same for an assessed CmdbObjectGroup, which carries no ACL: existence alone is judged
UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG: str = "Unknown ObjectGroup(s) referenced: {unknown}!"
# The 400 of that check when the assessed objects / groups or the caller's readable types could not be read
ASSESSED_OBJECT_LOOKUP_FAILED_MSG: str = "Failed to check the assessed Objects or ObjectGroups in the database!"

# The 400 of a RiskAssessment write whose risk calculation names an ImpactCategory, an Impact or a Likelihood that
# does not exist: one reason per field path, every one named, joined by RISK_CALCULATION_REASON_SEPARATOR
UNKNOWN_RISK_CALCULATION_REFERENCES_MSG: str = "The risk calculation references unknown IDs - {reasons}!"
# The 400 of a RiskAssessment write that rates one ImpactCategory more than once in a risk calculation: one reason
# per matrix, naming the categories rated twice
DUPLICATE_IMPACT_CATEGORIES_MSG: str = (
    "An ImpactCategory may be rated once per risk calculation - rated more than once: {reasons}!"
)
# How many rows of one ImpactCategory a risk-calculation matrix may hold
MAX_ROWS_PER_IMPACT_CATEGORY: int = 1
# One reason of either refusal: the field path and the sorted ids
RISK_CALCULATION_REASON: str = "{field}: {ids}"
RISK_CALCULATION_REASON_SEPARATOR: str = "; "
# Joins the keys of a field path inside the RiskAssessment document, as the refusals name it
RISK_CALCULATION_PATH_SEPARATOR: str = "."
# The 400 of that check when the ImpactCategories could not be read - before anything is written
IMPACT_CATEGORY_LOOKUP_FAILED_MSG: str = "Failed to check the referenced ImpactCategories in the database!"


class RiskCalculationReferenceKind(BaseStrEnum):
    """What an id inside a RiskAssessment's risk calculation names - each kind is resolved in its own collection"""
    IMPACT_CATEGORY = 'impact_category'
    IMPACT = 'impact'
    LIKELIHOOD = 'likelihood'

# The 400 of an ISMS write naming a CmdbExtendableOption that is no option of the list its field draws from - a missing
# option and an option of another list alike. Filled with the field's label, its OptionType and the sorted ids
UNKNOWN_OPTIONS_MSG: str = (
    "Unknown {label}(s) referenced: {unknown} - each has to be an option of the {option_type} list!"
)
# The 400 of that check when the options could not be read - before anything is written
OPTION_LOOKUP_FAILED_MSG: str = "Failed to check the referenced {label}(s) in the database!"


class IsmsOptionField(NamedTuple):
    """An ISMS field storing a CmdbExtendableOption id: the list it draws from, and how a refusal names it"""
    option_type: OptionType
    label: str


# The ISMS fields holding an option id - every write naming one checks it against its list
IMPLEMENTATION_STATE_OPTION: IsmsOptionField = IsmsOptionField(OptionType.IMPLEMENTATION_STATE, 'implementation state')
THREAT_VULNERABILITY_SOURCE_OPTION: IsmsOptionField = IsmsOptionField(OptionType.THREAT_VULNERABILITY, 'source')
CONTROL_MEASURE_SOURCE_OPTION: IsmsOptionField = IsmsOptionField(OptionType.CONTROL_MEASURE, 'source')
RISK_CATEGORY_OPTION: IsmsOptionField = IsmsOptionField(OptionType.RISK, 'Risk category')

# The implementation-state refusals, as the RiskAssessment, ControlMeasureAssignment and ControlMeasure writes answer
UNKNOWN_IMPLEMENTATION_STATES_MSG: str = UNKNOWN_OPTIONS_MSG.format(
    label=IMPLEMENTATION_STATE_OPTION.label, option_type=IMPLEMENTATION_STATE_OPTION.option_type.value,
    unknown='{unknown}',
)
IMPLEMENTATION_STATE_LOOKUP_FAILED_MSG: str = OPTION_LOOKUP_FAILED_MSG.format(label=IMPLEMENTATION_STATE_OPTION.label)

# Refusals (HTTP 400) for a person reference that cannot be resolved at all: its value is not a public_id, or its
# '_ref_type' sibling names neither a CmdbPerson nor a CmdbPersonGroup. Formatted with the reference key and the
# offending value
INVALID_PERSON_REFERENCE_ID_MSG: str = "The '{key}' reference must be a public_id, got {value!r}!"
UNKNOWN_PERSON_REFERENCE_TYPE_MSG: str = (
    "The '{key}' reference names no known reference type: {value!r} (allowed: {allowed})!"
)

# The 400 a write answers when looking up the documents it references fails, formatted with what they are
REFERENCE_LOOKUP_FAILED_MSG: str = "Failed to look up the referenced {label} IDs in the database!"

# The 400s of a write whose id lists name a document that does not exist, or name one twice: one reason per field
# (``ID_REFERENCE_REASON``), every one named, joined by ``ID_REFERENCE_REASON_SEPARATOR``. Filled with the entity
# (e.g. "Risk", "ImpactCategory 7")
UNKNOWN_REFERENCED_IDS_MSG: str = "The {entity} references unknown IDs - {reasons}!"
REPEATED_REFERENCED_IDS_MSG: str = "The {entity} names an ID more than once - {reasons}!"
ID_REFERENCE_REASON: str = "{field}: {ids}"
ID_REFERENCE_REASON_SEPARATOR: str = "; "
# The field path of an ImpactCategory's described Impact, as those reasons name it
IMPACT_DESCRIPTION_ID_FIELD: str = "impact_descriptions.impact_id"
# How an ImpactCategory of a bulk update is named in those refusals
IMPACT_CATEGORY_ENTITY: str = "ImpactCategory {public_id}"


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

# The query flag of a duplicate asking for the source's ControlMeasure assignments to be copied too (default true)
COPY_CMA_PARAM: str = 'copy_cma'

# The modes of POST /isms/risk_assessments/duplicate/<mode>/<ids>: what the comma-separated ids name
RISK_DUPLICATE_MODE: str = 'risk'
OBJECT_DUPLICATE_MODE: str = 'object'
OBJECT_GROUP_DUPLICATE_MODE: str = 'object_group'
DUPLICATE_MODES: tuple[str, ...] = (OBJECT_DUPLICATE_MODE, RISK_DUPLICATE_MODE, OBJECT_GROUP_DUPLICATE_MODE)

# How the comma-separated target ids of a duplicate are split, and the bounds of one id: a public_id starts at 1,
# and MongoDB stores at most an 8-byte signed integer
DUPLICATE_TARGET_SEPARATOR: str = ','
MIN_DUPLICATE_TARGET_ID: int = 1
MAX_DUPLICATE_TARGET_ID: int = 2 ** 63 - 1

# The 400 of a duplicate whose target ids are not each a distinct whole number in those bounds, decided before
# anything is read or written; it names every invalid token and every repeated id, the reasons joined by the
# separator
DUPLICATE_TARGETS_REFUSED_MSG: str = "No RiskAssessment was duplicated: {reasons}"
DUPLICATE_TARGETS_INVALID_REASON: str = (
    "these target ids are no whole number from {minimum} to {maximum}: {tokens}"
)
DUPLICATE_TARGETS_REPEATED_REASON: str = "these target ids are sent more than once: {ids}"
DUPLICATE_TARGETS_REASON_SEPARATOR: str = "; "

# The 404 of a duplicate whose source public_id names no stored RiskAssessment
DUPLICATE_SOURCE_NOT_FOUND_MSG: str = "The RiskAssessment with ID:{public_id} was not found!"

# The 400 of a duplicate when the source's ControlMeasureAssignments, copied onto every duplicate, cannot be read
DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG: str = (
    "Failed to read the ControlMeasureAssignments of the source RiskAssessment from the database!"
)

# The block the RiskAssessment list adds to every assessment: the display names of what its ids reference
RISK_ASSESSMENT_NAMING_KEY: str = 'naming'


class RiskAssessmentNamingKey(BaseStrEnum):
    """
    Keys of the ``naming`` block of a listed RiskAssessment

    Each holds the display name of what one reference of the assessment points at, or None when it names nothing
    the list could resolve
    """
    RISK_ID_NAME = 'risk_id_name'
    OBJECT_GROUP_ID_NAME = 'object_group_id_name'
    OBJECT_ID_NAME = 'object_id_name'
    INTERVIEWED_PERSONS_NAMES = 'interviewed_persons_names'
    RESPONSIBLE_PERSONS_ID_NAME = 'responsible_persons_id_name'
