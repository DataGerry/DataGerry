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
Validation schema for IsmsControlMeasureAssignment

An IsmsControlMeasureAssignment links an IsmsControlMeasure to an IsmsRiskAssessment
and tracks its implementation (collection ``isms.controlMeasureAssignment``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsControlMeasureAssignment.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# The three shapes a date arrives in: the Mongo extended-JSON wrapper {'$date': ...} the frontend
# sends, a timestamp string from an API client, and a real datetime (an already-normalised payload).
# All three are normalised to a datetime before the document is stored - declared as a plain 'dict',
# a date field lets the wrapper itself be persisted
_DATE_TYPES: list[str] = ['dict', 'string', 'datetime']
def get_isms_control_measure_assignment_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsControlMeasureAssignment document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsControlMeasureAssignment.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
    from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
    from cmdb.models.isms_model.priority_enum import Priority

    # Allowed values of the reference-type discriminator, pinned to its enum: an unknown value would name
    # neither collection, so no person or person-group delete would ever clear the reference beside it
    person_ref_types: list[str] = [ref_type.value for ref_type in PersonReferenceType]
    # Pinned the same way as the RiskAssessment's priority: a value the frontend has no name for is refused
    priorities: list[int] = [priority.value for priority in Priority]

    return {
        ControlMeasureAssignmentKey.PUBLIC_ID.value: {  # public_id of the IsmsControlMeasureAssignment
            'type': 'integer',
            'min': 1,
        },
        ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value: {  # public_id of the assigned IsmsControlMeasure
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        # public_id of the IsmsRiskAssessment the measure is assigned to
        ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        ControlMeasureAssignmentKey.PLANNED_IMPLEMENTATION_DATE.value: {  # Date of planned implementation
            'anyof_type': _DATE_TYPES,
            'required': True,
            'nullable': True,
        },
        # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
        ControlMeasureAssignmentKey.IMPLEMENTATION_STATUS.value: {
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        ControlMeasureAssignmentKey.FINISHED_IMPLEMENTATION_DATE.value: {  # Date of finished implementation
            'anyof_type': _DATE_TYPES,
            'required': True,
            'nullable': True,
        },
        ControlMeasureAssignmentKey.PRIORITY.value: {  # Priority value (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            'type': 'integer',
            'required': True,
            'nullable': True,
            'allowed': priorities,
        },
        # PersonReferenceType value (PERSON / PERSON_GROUP)
        ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value: {
            'type': 'string',
            'required': True,
            'nullable': True,
            'allowed': person_ref_types,
        },
        # public_id of the responsible CmdbPerson or CmdbPersonGroup
        ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value: {
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
    }
