# DATAGERRY - OpenSource Enterprise CMDB
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
Document keys of an IsmsRiskAssessment

The keys of the ``isms.riskAssessment`` documents, named once. They were previously spelled out as
bare literals in four independent places - the model's ``from_data``, its ``to_json``, its
``INDEX_KEYS`` and the Cerberus schema - plus the route layer's required-field tuple, so a renamed
or mistyped key showed up as a silently missing value rather than as an error.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo
filter key or a projection key, so what reaches the database is a plain string.

The nested keys *inside* the two risk-calculation matrices are not listed here - they belong to
``RiskCalculationKey`` in ``risk_calculation_constants``, which is shared with the managers that
recompute those matrices
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class RiskAssessmentKey(BaseStrEnum):
    """
    Top-level field keys of an IsmsRiskAssessment document
    """
    PUBLIC_ID = 'public_id'
    RISK_ID = 'risk_id'
    OBJECT_ID_REF_TYPE = 'object_id_ref_type'
    OBJECT_ID = 'object_id'
    RISK_CALCULATION_BEFORE = 'risk_calculation_before'
    RISK_ASSESSOR_ID = 'risk_assessor_id'
    RISK_OWNER_ID_REF_TYPE = 'risk_owner_id_ref_type'
    RISK_OWNER_ID = 'risk_owner_id'
    INTERVIEWED_PERSONS = 'interviewed_persons'
    RISK_ASSESSMENT_DATE = 'risk_assessment_date'
    ADDITIONAL_INFO = 'additional_info'
    RISK_TREATMENT_OPTION = 'risk_treatment_option'
    RESPONSIBLE_PERSONS_ID_REF_TYPE = 'responsible_persons_id_ref_type'
    RESPONSIBLE_PERSONS_ID = 'responsible_persons_id'
    RISK_TREATMENT_DESCRIPTION = 'risk_treatment_description'
    PLANNED_IMPLEMENTATION_DATE = 'planned_implementation_date'
    IMPLEMENTATION_STATUS = 'implementation_status'
    FINISHED_IMPLEMENTATION_DATE = 'finished_implementation_date'
    REQUIRED_RESOURCES = 'required_resources'
    COSTS_FOR_IMPLEMENTATION = 'costs_for_implementation'
    COSTS_FOR_IMPLEMENTATION_CURRENCY = 'costs_for_implementation_currency'
    PRIORITY = 'priority'
    RISK_CALCULATION_AFTER = 'risk_calculation_after'
    AUDIT_DONE_DATE = 'audit_done_date'
    AUDITOR_ID_REF_TYPE = 'auditor_id_ref_type'
    AUDITOR_ID = 'auditor_id'
    AUDIT_RESULT = 'audit_result'


# The four date-typed fields, in document order. Every write path normalises exactly these into real
# BSON dates (see IsmsRiskAssessment.DATE_FIELDS), which is what lets MongoDB sort and range-filter them
RISK_ASSESSMENT_DATE_KEYS: tuple[RiskAssessmentKey, ...] = (
    RiskAssessmentKey.RISK_ASSESSMENT_DATE,
    RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE,
    RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE,
    RiskAssessmentKey.AUDIT_DONE_DATE,
)

# Transport-only key of the write payloads: the frontend sends the assessment's ControlMeasure
# assignments alongside it, but they are documents of their own collection. Every write route pops it
# before the assessment is stored, so it is deliberately NOT a RiskAssessmentKey - see the model's
# module docstring on why a key outside the model's set must never be persisted
CONTROL_MEASURE_ASSIGNMENTS_KEY: str = 'control_measure_assignments'
