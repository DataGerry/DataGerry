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
# All three are normalised to a datetime before the document is stored - a date field used to be
# declared as a plain 'dict', which is what let the wrapper itself be persisted
_DATE_TYPES: list[str] = ['dict', 'string', 'datetime']
# pylint: disable=R0801
def get_isms_control_measure_assignment_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsControlMeasureAssignment document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsControlMeasureAssignment.SCHEMA
    """
    return {
        'public_id': {  # public_id of the IsmsControlMeasureAssignment
            'type': 'integer',
            'min': 1,
        },
        'control_measure_id': {  # public_id of the assigned IsmsControlMeasure
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'risk_assessment_id': {  # public_id of the IsmsRiskAssessment the measure is assigned to
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'planned_implementation_date': {  # Date of planned implementation
            'anyof_type': _DATE_TYPES,
            'required': True,
            'nullable': True,
        },
        'implementation_status': {  # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'finished_implementation_date': {  # Date of finished implementation
            'anyof_type': _DATE_TYPES,
            'required': True,
            'nullable': True,
        },
        'priority': {  # Priority value (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'responsible_for_implementation_id_ref_type': {  # PersonReferenceType value (PERSON / PERSON_GROUP)
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'responsible_for_implementation_id': {  # public_id of the responsible CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
    }
