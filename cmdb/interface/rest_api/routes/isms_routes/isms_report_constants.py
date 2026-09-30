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
Keys and labels of the ISMS report pipelines

Three kinds of name live here, and none of them is a stored document key - those belong to the owning
model's `*Key` enum (`RiskAssessmentKey`, `RiskKey`, `PersonKey`, ...):

* `ReportAlias`: the intermediate fields a report pipeline joins its references under (a `$lookup`'s
  `as`), read again by the later stages and never part of a response
* the response keys of each report row (`RiskAssessmentReportKey`, `RiskTreatmentPlanReportKey`) and of the
  nested rows both reports share (`RiskBadgeKey`, `ImpactCategoryRowKey`, `ReportFacetKey`). Several share a
  spelling with a document key (`implementation_status`, `priority`) but carry a resolved display value,
  so they are kept apart from the model enums
* the display labels the pipelines write into a row
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class ReportAlias(BaseStrEnum):
    """The intermediate fields the report pipelines join their references under"""
    RISK = 'risk'
    RISK_CATEGORY = 'risk_category'
    PROTECTION_GOALS = 'protection_goals'
    IMPLEMENTATION_STATUS = 'implementation_status'
    OBJECT = 'object'
    OBJECT_GROUP = 'object_group'
    OBJECT_TYPE = 'object_type'
    RISK_ASSESSOR_PERSON = 'risk_assessor_person'
    RISK_OWNER_PERSON = 'risk_owner_person'
    RISK_OWNER_GROUP = 'risk_owner_group'
    RESPONSIBLE_PERSON = 'responsible_person'
    RESPONSIBLE_PERSON_GROUP = 'responsible_person_group'
    AUDITOR_PERSON = 'auditor_person'
    AUDITOR_GROUP = 'auditor_group'
    INTERVIEWED_PERSONS_DATA = 'interviewed_persons_data'
    RISK_BEFORE = 'risk_before'
    RISK_BEFORE_CLASS = 'risk_before_class'
    RISK_AFTER = 'risk_after'
    RISK_AFTER_CLASS = 'risk_after_class'
    IMPACT_CATEGORY_BEFORE = 'impact_category_before'
    IMPACT_BEFORE = 'impact_before'
    IMPACT_CATEGORY_AFTER = 'impact_category_after'
    IMPACT_AFTER = 'impact_after'
    LIKELIHOOD_BEFORE = 'likelihood_before'
    LIKELIHOOD_AFTER = 'likelihood_after'
    CONTROL_ASSIGNMENTS = 'control_assignments'
    CONTROL_MEASURES = 'control_measures'
    # The whole document a `$group` keeps aside while it builds one rolled-up array
    DOC = 'doc'


# The `$let` variables of the risk-matrix cell join, read as `$$likelihood_id` / `$$impact_id`
MATRIX_CELL_LIKELIHOOD_VARIABLE: str = 'likelihood_id'
MATRIX_CELL_IMPACT_VARIABLE: str = 'impact_id'

# The `$map` variables of the RiskAssessment projection
PROTECTION_GOAL_VARIABLE: str = 'pg'
INTERVIEWED_PERSON_VARIABLE: str = 'person'


class RiskAssessmentReportKey(BaseStrEnum):
    """
    The computed columns of a RiskAssessment report row

    The columns that pass a stored field through unchanged are spelled with `RiskAssessmentKey`
    """
    RISK_TITLE = 'risk_title'
    RISK_CATEGORY = 'risk_category'
    PROTECTION_GOALS = 'protection_goals'
    RISK_OWNER = 'risk_owner'
    RESPONSIBLE_PERSON = 'responsible_person'
    AUDITOR = 'auditor'
    IMPLEMENTATION_STATUS = 'implementation_status'
    PRIORITY = 'priority'
    ASSIGNED_OBJECT = 'assigned_object'
    ASSIGNED_OBJECT_TYPE = 'assigned_object_type'
    RISK_ASSESSOR = 'risk_assessor'
    INTERVIEWED_PERSONS = 'interviewed_persons'
    IMPACT_CATEGORIES_BEFORE = 'impact_categories_before'
    IMPACT_CATEGORIES_AFTER = 'impact_categories_after'
    LIKELIHOOD_VALUE_BEFORE = 'likelihood_value_before'
    LIKELIHOOD_VALUE_AFTER = 'likelihood_value_after'
    RISK_TREATMENT_OPTION = 'risk_treatment_option'


class RiskTreatmentPlanReportKey(BaseStrEnum):
    """
    The computed columns of a Risk Treatment Plan report row

    The columns that pass a stored field through unchanged are spelled with `RiskAssessmentKey`
    """
    RISK_NAME = 'risk_name'
    RISK_IDENTIFIER = 'risk_identifier'
    RISK_CATEGORY = 'risk_category'
    PROTECTION_GOALS = 'protection_goals'
    OBJECT = 'object'
    OBJECT_TYPE = 'object_type'
    RISK_TREATMENT_OPTION = 'risk_treatment_option'
    IMPLEMENTATION_STATUS = 'implementation_status'
    RESPONSIBLE_PERSON = 'responsible_person'
    CONTROL_MEASURES = 'control_measures'


class RiskBadgeKey(BaseStrEnum):
    """The risk-class badges both risk reports show, and the keys of one badge"""
    RISK_BEFORE = 'risk_before'
    RISK_AFTER = 'risk_after'
    VALUE = 'value'
    RISK_CLASS_ID = 'risk_class_id'
    COLOR = 'color'


class ImpactCategoryRowKey(BaseStrEnum):
    """The keys of one entry of a RiskAssessment row's `impact_categories_before` / `_after` list"""
    IMPACT_CATEGORY = 'impact_category'
    IMPACT_VALUE = 'impact_value'


class ReportFacetKey(BaseStrEnum):
    """The two branches of a report's paging `$facet`: the page's rows and the full count"""
    DATA = 'data'
    TOTAL = 'total'


# The label of an assessed object group, in place of the type label an assessed object shows
OBJECT_GROUP_TYPE_LABEL: str = 'Object group'

# Separates a scale entry's calculation basis from its name ("3 - High")
CALCULATION_BASIS_SEPARATOR: str = ' - '

# The stored priority of an assessment -> the label the RiskAssessment report shows for it
PRIORITY_LABELS: dict[int, str] = {
    1: 'Low',
    2: 'Medium',
    3: 'High',
    4: 'Very High',
}
