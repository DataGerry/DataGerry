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
"""
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_risk_assessment_schema() -> dict:
    """
    Builds the Cerberus validation schema for a IsmsRiskAssessment document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsRiskAssessment.SCHEMA
    """
    return {
        'public_id': {
            'type': 'integer',
            'min': 1,
        },
        'risk_id': {  # public_id of referenced IsmsRisk
            'type': 'integer',
            'required': True,
            'empty': False
        },
        'object_id_ref_type': {  # ObjectReferenceType Enum
            'type': 'string',
            'required': True,
            'empty': False
        },
        'object_id': {  # public_id of referenced CmdbObject or CmdbObjectGroup (dependening on 'object_reference_type')
            'type': 'integer',
            'min': 1,
            'required': True,
            'empty': False
        },
        # Risk calculation before treatment
        'risk_calculation_before': {
            'type': 'dict',
            'required': True,
            'empty': False,
            'schema': {
                'impacts': {  # All impact category sliders
                    'type': 'list',
                    'required': True,
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
        },
        'risk_assessor_id': {  # public_id of CmdbPerson
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        'risk_owner_id_ref_type': {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
        },
        'risk_owner_id': {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        'interviewed_persons': {  # Multiselect of CmdbPersons
            'type': 'list',
            'required': True,
            'nullable': True
        },
        'risk_assessment_date': {  # Date of risk calculation before treatment
            'type': 'dict',
            'required': True,
            'empty': False
        },
        'additional_info': {  # Additional information field value
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        # Risk treatment
        'risk_treatment_option': {  # TreatmentOption Enum
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'responsible_persons_id_ref_type': {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
        },
        'responsible_persons_id': {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        'risk_treatment_description': {  # Additional information text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'planned_implementation_date': {  # Date of planned implementation
            'type': 'dict',
            'required': True,
            'nullable': True
        },
        'implementation_status': {  # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'finished_implementation_date': {  # Date of finished implementation
            'type': 'dict',
            'required': True,
            'nullable': True
        },
        'required_resources': {  # Required resources text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'costs_for_implementation': {  # Costs for implementation
            'type': 'float',
            'required': True,
            'nullable': True,
        },
        'costs_for_implementation_currency': {  # Costs for implementation currency
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'priority': {  # Priority enum (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        # Risk calculation after treatment
        'risk_calculation_after': {
            'type': 'dict',
            'required': True,
            'empty': False,
            'schema': {
                'impacts': {  # All impact category sliders
                    'type': 'list',
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
        },
        # Checking the effectiveness of the measures
        'audit_done_date': {  # Audit done date
            'type': 'dict',
            'required': True,
            'nullable': True
        },
        'auditor_id_ref_type': {  # PersonReferenceType Enum
            'type': 'string',
            'required': True,
        },
        'auditor_id': {  # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
        'audit_result': {  # Audit result text area field
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        # optional control measure assignments
        'control_measure_assignments': {  # list of control meassure assignments
            'anyof_type': ['list', 'dict'],
        }
    }
