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
Validation schema for IsmsRiskAssessment

An IsmsRiskAssessment records the evaluation of a risk for an object or object group,
before and after treatment (collection ``isms.riskAssessment``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsRiskAssessment.SCHEMA.

Every field whose value belongs to an enum is pinned here with an ``allowed`` list built from that
enum, which makes validation - not the model - the place an unknown reference type, treatment option
or priority is refused. The keys come from ``RiskAssessmentKey``, so the schema and the model cannot
drift apart on a key name
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# The three shapes a date arrives in: the Mongo extended-JSON wrapper {'$date': ...} the frontend
# sends, a timestamp string from an API client, and a real datetime (an already-normalised payload).
# All three are normalised to a datetime before the document is stored
_DATE_TYPES: list[str] = ['dict', 'string', 'datetime']


def _get_date_schema(nullable: bool) -> dict[str, Any]:
    """
    Builds the Cerberus rules for one of the assessment's four date fields

    Args:
        nullable (bool): Whether the field may be null - false only for 'risk_assessment_date',
            which every write path requires

    Returns:
        dict[str, Any]: The Cerberus rules for a single date field
    """
    rules: dict[str, Any] = {
        'anyof_type': _DATE_TYPES,
        'required': True,
    }

    if nullable:
        rules['nullable'] = True
    else:
        # An empty wrapper is as unusable as no date at all
        rules['empty'] = False

    return rules


def _get_risk_calculation_schema(required_impacts: bool) -> dict[str, Any]:
    """
    Builds the Cerberus schema for one risk_calculation matrix (before or after treatment).

    Both matrices share the same shape; the parameter only controls whether the ``impacts`` list
    must be present, keeping the two definitions in sync from a single source.

    Args:
        required_impacts (bool): Whether the 'impacts' list is required in this matrix

    Returns:
        dict[str, Any]: The Cerberus rules for a single risk_calculation matrix
    """
    return {
        'type': 'dict',
        'required': True,
        'empty': False,
        'schema': {
            'impacts': {  # All impact category sliders
                'type': 'list',
                'required': required_impacts,
                'schema': {
                    'type': 'dict',
                    'schema': {
                        'impact_category_id': {  # public_id of IsmsImpactCategory
                            'type': 'integer',
                            'required': True,
                        },
                        'impact_id': {  # public_id of IsmsImpact (empty = unrated)
                            'type': 'integer',
                            'required': True,
                            'nullable': True,
                        }
                    }
                }
            },
            'likelihood_id': {  # public_id of IsmsLikelihood (empty = unrated)
                'type': 'integer',
                'required': True,
                'nullable': True,
            },
            'likelihood_value': {  # calculation_basis of selected IsmsLikelihood
                'type': 'float',
                'min': 0.0,
                'required': True,
                'nullable': True,
            },
            'maximum_impact_id': {  # public_id of the maximum IsmsImpact
                'type': 'integer',
                'required': True,
                'nullable': True,
            },
            'maximum_impact_value': {  # Maximum calculation_basis of the impact sliders
                'type': 'float',
                'min': 0.0,
                'required': True,
                'nullable': True,
            }
        }
    }


# pylint: disable=R0801
def get_isms_risk_assessment_schema() -> dict:
    """
    Builds the Cerberus validation schema for a IsmsRiskAssessment document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsRiskAssessment.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.isms_risk_assessment_constants import (
        CONTROL_MEASURE_ASSIGNMENTS_KEY,
        RiskAssessmentKey,
    )
    from cmdb.models.isms_model.priority_enum import Priority
    from cmdb.models.isms_model.treatment_option_enum import TreatmentOption
    from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
    from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

    # Allowed values for the reference-type discriminator fields, pinned to their enums
    object_ref_types: list[str] = [ref_type.value for ref_type in ObjectReferenceType]
    person_ref_types: list[str] = [ref_type.value for ref_type in PersonReferenceType]

    # Allowed values of the two remaining enum-typed fields, pinned the same way. Both were previously
    # unconstrained ('type': string / integer only), so an API client could store a treatment option or
    # a priority the frontend has no name for and the reports cannot group by
    treatment_options: list[str] = [option.value for option in TreatmentOption]
    priorities: list[int] = [priority.value for priority in Priority]

    return {
        RiskAssessmentKey.PUBLIC_ID.value: {
            'type': 'integer',
            'min': 1,
        },
        RiskAssessmentKey.RISK_ID.value: {  # public_id of referenced IsmsRisk
            'type': 'integer',
            'required': True,
            'empty': False
        },
        RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: {  # ObjectReferenceType Enum
            'type': 'string',
            'required': True,
            'empty': False,
            'allowed': object_ref_types,
        },
        # public_id of referenced CmdbObject or CmdbObjectGroup (depending on 'object_id_ref_type')
        RiskAssessmentKey.OBJECT_ID.value: {
            'type': 'integer',
            'min': 1,
            'required': True,
            'empty': False
        },
        # Risk calculation before treatment
        RiskAssessmentKey.RISK_CALCULATION_BEFORE.value: _get_risk_calculation_schema(required_impacts=True),
        RiskAssessmentKey.RISK_ASSESSOR_ID.value: {  # public_id of CmdbPerson
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value: {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
            'allowed': person_ref_types,
        },
        RiskAssessmentKey.RISK_OWNER_ID.value: {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.INTERVIEWED_PERSONS.value: {  # Multiselect of CmdbPersons
            'type': 'list',
            'required': True,
            'nullable': True
        },
        # Date of risk calculation before treatment
        RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: _get_date_schema(nullable=False),
        RiskAssessmentKey.ADDITIONAL_INFO.value: {  # Additional information field value
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        # Risk treatment
        RiskAssessmentKey.RISK_TREATMENT_OPTION.value: {  # TreatmentOption Enum
            'type': 'string',
            'required': True,
            'nullable': True,
            'allowed': treatment_options,
        },
        RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value: {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
            'allowed': person_ref_types,
        },
        RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value: {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.RISK_TREATMENT_DESCRIPTION.value: {  # Additional information text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        # Date of planned implementation
        RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: _get_date_schema(nullable=True),
        # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
        RiskAssessmentKey.IMPLEMENTATION_STATUS.value: {
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        # Date of finished implementation
        RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value: _get_date_schema(nullable=True),
        RiskAssessmentKey.REQUIRED_RESOURCES.value: {  # Required resources text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value: {  # Costs for implementation
            'type': 'float',
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION_CURRENCY.value: {  # Costs for implementation currency
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.PRIORITY.value: {  # Priority enum (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            'type': 'integer',
            'required': True,
            'nullable': True,
            'allowed': priorities,
        },
        # Risk calculation after treatment (impacts optional: an untreated assessment has no
        # after-treatment sliders yet, unlike the mandatory before-treatment matrix)
        RiskAssessmentKey.RISK_CALCULATION_AFTER.value: _get_risk_calculation_schema(required_impacts=False),
        # Checking the effectiveness of the measures
        RiskAssessmentKey.AUDIT_DONE_DATE.value: _get_date_schema(nullable=True),  # Audit done date
        RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value: {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
            'allowed': person_ref_types,
        },
        RiskAssessmentKey.AUDITOR_ID.value: {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        RiskAssessmentKey.AUDIT_RESULT.value: {  # Audit result text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        # Transport-only: the assignments travel with the assessment but are stored in their own
        # collection, so every write route pops this key before the assessment is written. It stays in
        # the schema because the validator purges unknown keys, and purging it would drop the payload
        CONTROL_MEASURE_ASSIGNMENTS_KEY: {  # list of control measure assignments
            'anyof_type': ['list', 'dict'],
        }
    }
