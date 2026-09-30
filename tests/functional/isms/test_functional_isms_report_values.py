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
Functional tests for the VALUES the two aggregation reports resolve

`test_functional_isms_report_route.py` checks that the reports respond, page, sort, search and filter.
This module seeds one fully-populated RiskAssessment - every reference it can carry pointing at its own
document with its own distinguishable value - and asserts every resolved column of both report rows. A
lookup joined on the wrong key, or a projection reading the wrong field, shows up as a wrong value here
rather than as a still-parseable row. A second assessment references person GROUPS, for the other arm
of each person-or-group column.

The routes are ISMS-license gated, so the check is stubbed.
"""
import json
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsRiskAssessment,
    IsmsRiskClass,
    IsmsRiskMatrix,
)
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/reports'
RISK_ASSESSMENTS_REPORT: str = 'risk_assessments'
RISK_TREATMENT_PLAN_REPORT: str = 'risk_treatment_plan'

# Extendable options: the risk's category and the assessment's implementation status
CATEGORY_OPTION_ID: int = 99801
CATEGORY_VALUE: str = 'ValCategory'
STATUS_OPTION_ID: int = 99802
STATUS_VALUE: str = 'ValImplemented'

PROTECTION_GOAL_ID: int = 99803
PROTECTION_GOAL_NAME: str = 'ValGoal'

# The risk. Its description differs from its identifier, so a column reading the wrong one shows
RISK_ID: int = 99804
RISK_NAME: str = 'ValRiskName'
RISK_IDENTIFIER: str = 'VAL-ID-1'
RISK_DESCRIPTION: str = 'ValRiskDescription'

# One person per person reference, so a lookup joined on another reference's key names the wrong person
ASSESSOR_ID: int = 99810
ASSESSOR_NAME: str = 'Val Assessor'
OWNER_ID: int = 99811
OWNER_NAME: str = 'Val Owner'
RESPONSIBLE_ID: int = 99812
RESPONSIBLE_NAME: str = 'Val Responsible'
AUDITOR_ID: int = 99813
AUDITOR_NAME: str = 'Val Auditor'
INTERVIEWEE_ID: int = 99814
INTERVIEWEE_NAME: str = 'Val Interviewee'

# One person group per group reference of the second assessment
OWNER_GROUP_ID: int = 99815
OWNER_GROUP_NAME: str = 'Val Owner Group'
RESPONSIBLE_GROUP_ID: int = 99816
RESPONSIBLE_GROUP_NAME: str = 'Val Responsible Group'
AUDITOR_GROUP_ID: int = 99817
AUDITOR_GROUP_NAME: str = 'Val Auditor Group'

# Scale entries: a name, a calculation basis and a description that must NOT show
LIKELIHOOD_BEFORE_ID: int = 99820
LIKELIHOOD_BEFORE_NAME: str = 'ValLikelyBefore'
LIKELIHOOD_BEFORE_BASIS: int = 2
LIKELIHOOD_AFTER_ID: int = 99821
LIKELIHOOD_AFTER_NAME: str = 'ValLikelyAfter'
LIKELIHOOD_AFTER_BASIS: int = 1
IMPACT_BEFORE_ID: int = 99822
IMPACT_BEFORE_NAME: str = 'ValImpactBefore'
IMPACT_BEFORE_BASIS: int = 3
IMPACT_AFTER_ID: int = 99823
IMPACT_AFTER_NAME: str = 'ValImpactAfter'
IMPACT_AFTER_BASIS: int = 1
SCALE_DESCRIPTION: str = 'ValScaleDescription'

# Two impact categories, so the after-treatment rollup reading the before-treatment category shows
IMPACT_CATEGORY_BEFORE_ID: int = 99824
IMPACT_CATEGORY_BEFORE_NAME: str = 'ValImpactCategoryBefore'
IMPACT_CATEGORY_AFTER_ID: int = 99827
IMPACT_CATEGORY_AFTER_NAME: str = 'ValImpactCategoryAfter'

# The risk classes the two matrix cells point at: a name and a colour that differ
RISK_CLASS_BEFORE_ID: int = 99825
RISK_CLASS_BEFORE_NAME: str = 'ValClassBefore'
RISK_CLASS_BEFORE_COLOR: str = '#aa0000'
RISK_CLASS_AFTER_ID: int = 99826
RISK_CLASS_AFTER_NAME: str = 'ValClassAfter'
RISK_CLASS_AFTER_COLOR: str = '#00bb00'
CELL_BEFORE_VALUE: int = 6
CELL_AFTER_VALUE: int = 1

CONTROL_MEASURE_ID: int = 99830
CONTROL_MEASURE_TITLE: str = 'ValControl'
ASSIGNMENT_ID: int = 99831

OBJECT_GROUP_ID: int = 99841
OBJECT_GROUP_NAME: str = 'ValObjectGroup'

# The two assessments: persons referenced, and person groups referenced
PERSON_ASSESSMENT_ID: int = 99840
GROUP_ASSESSMENT_ID: int = 99842
PRIORITY: int = 2
PRIORITY_LABEL: str = 'Medium'
TREATMENT_OPTION: str = 'REDUCE'
PERSON_REF: str = 'PERSON'
PERSON_GROUP_REF: str = 'PERSON_GROUP'
OBJECT_GROUP_REF: str = 'OBJECT_GROUP'
OBJECT_GROUP_TYPE_LABEL: str = 'Object group'


def _label(basis: int, name: str) -> str:
    """The "<calculation basis> - <name>" label the report builds for a scale entry."""
    return f'{basis} - {name}'


def _assessment(public_id: int, ref_type: str, owner: int, responsible: int, auditor: int) -> dict[str, Any]:
    """One fully-populated RiskAssessment document; only the three person-or-group references vary."""
    return {
        'public_id': public_id,
        'risk_id': RISK_ID,
        'object_id_ref_type': OBJECT_GROUP_REF,
        'object_id': OBJECT_GROUP_ID,
        'risk_assessor_id': ASSESSOR_ID,
        'risk_owner_id_ref_type': ref_type,
        'risk_owner_id': owner,
        'responsible_persons_id_ref_type': ref_type,
        'responsible_persons_id': responsible,
        'auditor_id_ref_type': ref_type,
        'auditor_id': auditor,
        'interviewed_persons': [INTERVIEWEE_ID],
        'implementation_status': STATUS_OPTION_ID,
        'priority': PRIORITY,
        'risk_treatment_option': TREATMENT_OPTION,
        'risk_calculation_before': {
            'likelihood_id': LIKELIHOOD_BEFORE_ID,
            'maximum_impact_id': IMPACT_BEFORE_ID,
            'impacts': [{'impact_category_id': IMPACT_CATEGORY_BEFORE_ID, 'impact_id': IMPACT_BEFORE_ID}],
        },
        'risk_calculation_after': {
            'likelihood_id': LIKELIHOOD_AFTER_ID,
            'maximum_impact_id': IMPACT_AFTER_ID,
            'impacts': [{'impact_category_id': IMPACT_CATEGORY_AFTER_ID, 'impact_id': IMPACT_AFTER_ID}],
        },
    }


SEEDED_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    CmdbExtendableOption.COLLECTION: [
        {'public_id': CATEGORY_OPTION_ID, 'value': CATEGORY_VALUE, 'option_type': OptionType.RISK.value},
        {'public_id': STATUS_OPTION_ID, 'value': STATUS_VALUE,
         'option_type': OptionType.IMPLEMENTATION_STATE.value},
    ],
    IsmsProtectionGoal.COLLECTION: [{'public_id': PROTECTION_GOAL_ID, 'name': PROTECTION_GOAL_NAME}],
    IsmsRisk.COLLECTION: [{
        'public_id': RISK_ID, 'name': RISK_NAME, 'identifier': RISK_IDENTIFIER, 'description': RISK_DESCRIPTION,
        'category_id': CATEGORY_OPTION_ID, 'protection_goals': [PROTECTION_GOAL_ID],
    }],
    CmdbPerson.COLLECTION: [
        {'public_id': person_id, 'display_name': name} for person_id, name in (
            (ASSESSOR_ID, ASSESSOR_NAME), (OWNER_ID, OWNER_NAME), (RESPONSIBLE_ID, RESPONSIBLE_NAME),
            (AUDITOR_ID, AUDITOR_NAME), (INTERVIEWEE_ID, INTERVIEWEE_NAME),
        )
    ],
    CmdbPersonGroup.COLLECTION: [
        {'public_id': group_id, 'name': name} for group_id, name in (
            (OWNER_GROUP_ID, OWNER_GROUP_NAME), (RESPONSIBLE_GROUP_ID, RESPONSIBLE_GROUP_NAME),
            (AUDITOR_GROUP_ID, AUDITOR_GROUP_NAME),
        )
    ],
    IsmsLikelihood.COLLECTION: [
        {'public_id': LIKELIHOOD_BEFORE_ID, 'name': LIKELIHOOD_BEFORE_NAME,
         'calculation_basis': LIKELIHOOD_BEFORE_BASIS, 'description': SCALE_DESCRIPTION},
        {'public_id': LIKELIHOOD_AFTER_ID, 'name': LIKELIHOOD_AFTER_NAME,
         'calculation_basis': LIKELIHOOD_AFTER_BASIS, 'description': SCALE_DESCRIPTION},
    ],
    IsmsImpact.COLLECTION: [
        {'public_id': IMPACT_BEFORE_ID, 'name': IMPACT_BEFORE_NAME,
         'calculation_basis': IMPACT_BEFORE_BASIS, 'description': SCALE_DESCRIPTION},
        {'public_id': IMPACT_AFTER_ID, 'name': IMPACT_AFTER_NAME,
         'calculation_basis': IMPACT_AFTER_BASIS, 'description': SCALE_DESCRIPTION},
    ],
    IsmsImpactCategory.COLLECTION: [
        {'public_id': IMPACT_CATEGORY_BEFORE_ID, 'name': IMPACT_CATEGORY_BEFORE_NAME},
        {'public_id': IMPACT_CATEGORY_AFTER_ID, 'name': IMPACT_CATEGORY_AFTER_NAME},
    ],
    IsmsRiskClass.COLLECTION: [
        {'public_id': RISK_CLASS_BEFORE_ID, 'name': RISK_CLASS_BEFORE_NAME, 'color': RISK_CLASS_BEFORE_COLOR},
        {'public_id': RISK_CLASS_AFTER_ID, 'name': RISK_CLASS_AFTER_NAME, 'color': RISK_CLASS_AFTER_COLOR},
    ],
    IsmsControlMeasure.COLLECTION: [{'public_id': CONTROL_MEASURE_ID, 'title': CONTROL_MEASURE_TITLE}],
    IsmsControlMeasureAssignment.COLLECTION: [{
        'public_id': ASSIGNMENT_ID, 'control_measure_id': CONTROL_MEASURE_ID,
        'risk_assessment_id': PERSON_ASSESSMENT_ID,
    }],
    CmdbObjectGroup.COLLECTION: [{'public_id': OBJECT_GROUP_ID, 'name': OBJECT_GROUP_NAME}],
    IsmsRiskAssessment.COLLECTION: [
        _assessment(PERSON_ASSESSMENT_ID, PERSON_REF, OWNER_ID, RESPONSIBLE_ID, AUDITOR_ID),
        _assessment(GROUP_ASSESSMENT_ID, PERSON_GROUP_REF, OWNER_GROUP_ID, RESPONSIBLE_GROUP_ID, AUDITOR_GROUP_ID),
    ],
}

# The two cells the assessments' calculations land on, added to the RiskMatrix singleton
MATRIX_CELLS: list[dict[str, Any]] = [
    {'likelihood_id': LIKELIHOOD_BEFORE_ID, 'impact_id': IMPACT_BEFORE_ID,
     'calculated_value': CELL_BEFORE_VALUE, 'risk_class_id': RISK_CLASS_BEFORE_ID},
    {'likelihood_id': LIKELIHOOD_AFTER_ID, 'impact_id': IMPACT_AFTER_ID,
     'calculated_value': CELL_AFTER_VALUE, 'risk_class_id': RISK_CLASS_AFTER_ID},
]

RISK_BEFORE_BADGE: dict[str, Any] = {
    'value': CELL_BEFORE_VALUE, 'risk_class_id': RISK_CLASS_BEFORE_ID, 'color': RISK_CLASS_BEFORE_COLOR,
}
RISK_AFTER_BADGE: dict[str, Any] = {
    'value': CELL_AFTER_VALUE, 'risk_class_id': RISK_CLASS_AFTER_ID, 'color': RISK_CLASS_AFTER_COLOR,
}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated report routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """
    Seeds every referenced document plus the two matrix cells, and removes exactly those again

    The RiskMatrix is a singleton another test may already have created, so the cells are pushed onto it
    and pulled off again; a matrix this fixture had to create is deleted instead
    """
    for collection, documents in SEEDED_DOCUMENTS.items():
        database_manager.get_collection(collection, database_name).insert_many([dict(doc) for doc in documents])

    matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
    created_matrix: bool = matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID}) is None

    if created_matrix:
        matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': []})

    matrices.update_one({'public_id': RISK_MATRIX_PUBLIC_ID}, {'$push': {'risk_matrix': {'$each': MATRIX_CELLS}}})

    try:
        yield
    finally:
        if created_matrix:
            matrices.delete_one({'public_id': RISK_MATRIX_PUBLIC_ID})
        else:
            matrices.update_one(
                {'public_id': RISK_MATRIX_PUBLIC_ID},
                {'$pull': {'risk_matrix': {'likelihood_id': {'$in': [LIKELIHOOD_BEFORE_ID, LIKELIHOOD_AFTER_ID]}}}},
            )

        for collection, documents in SEEDED_DOCUMENTS.items():
            database_manager.get_collection(collection, database_name).delete_many(
                {'public_id': {'$in': [doc['public_id'] for doc in documents]}}
            )


def _report_row(rest_api, report: str, assessment_id: int) -> dict[str, Any]:
    """The one row a report answers for an assessment, found through the report's own filter."""
    query = urlencode({'limit': 0, 'filter': json.dumps({'public_id': assessment_id})})
    response = rest_api.get(f'{ROUTE_URL}/{report}?{query}')

    assert response.status_code == HTTPStatus.OK
    rows = response.get_json()['results']
    assert len(rows) == 1

    return rows[0]


@pytest.mark.usefixtures('seeded')
class TestRiskAssessmentReportValues:
    """Every computed column of a RiskAssessment report row carries the value of the document it names."""

    def test_the_risk_columns(self, rest_api) -> None:
        """Title, category and protection goals come from the risk and its references."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['risk_title'] == RISK_NAME
        assert row['risk_category'] == CATEGORY_VALUE
        assert row['protection_goals'] == [PROTECTION_GOAL_NAME]

    def test_each_person_column_names_its_own_person(self, rest_api) -> None:
        """Every person reference resolves to the person it holds - never to another reference's person."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['risk_assessor'] == ASSESSOR_NAME
        assert row['risk_owner'] == OWNER_NAME
        assert row['responsible_person'] == RESPONSIBLE_NAME
        assert row['auditor'] == AUDITOR_NAME
        assert row['interviewed_persons'] == [INTERVIEWEE_NAME]

    def test_each_group_column_names_its_own_group(self, rest_api) -> None:
        """With PERSON_GROUP references, the same three columns show the groups' names."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, GROUP_ASSESSMENT_ID)

        assert row['risk_owner'] == OWNER_GROUP_NAME
        assert row['responsible_person'] == RESPONSIBLE_GROUP_NAME
        assert row['auditor'] == AUDITOR_GROUP_NAME

    def test_the_status_priority_and_object_columns(self, rest_api) -> None:
        """Option ids become their values, the priority its label, an object group its name."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['implementation_status'] == STATUS_VALUE
        assert row['priority'] == PRIORITY_LABEL
        assert row['risk_treatment_option'] == TREATMENT_OPTION
        assert row['assigned_object'] == OBJECT_GROUP_NAME
        assert row['assigned_object_type'] == OBJECT_GROUP_TYPE_LABEL

    def test_the_risk_badges(self, rest_api) -> None:
        """Each badge shows its own matrix cell's value and its own class's id and colour."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['risk_before'] == RISK_BEFORE_BADGE
        assert row['risk_after'] == RISK_AFTER_BADGE

    def test_the_likelihood_labels(self, rest_api) -> None:
        """A likelihood shows as "<basis> - <name>", before and after treatment."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['likelihood_value_before'] == _label(LIKELIHOOD_BEFORE_BASIS, LIKELIHOOD_BEFORE_NAME)
        assert row['likelihood_value_after'] == _label(LIKELIHOOD_AFTER_BASIS, LIKELIHOOD_AFTER_NAME)

    def test_the_impact_category_rollups(self, rest_api) -> None:
        """Each rollup lists its own calculation's category and the "<basis> - <name>" of its impact."""
        row = _report_row(rest_api, RISK_ASSESSMENTS_REPORT, PERSON_ASSESSMENT_ID)

        assert row['impact_categories_before'] == [{
            'impact_category': IMPACT_CATEGORY_BEFORE_NAME,
            'impact_value': _label(IMPACT_BEFORE_BASIS, IMPACT_BEFORE_NAME),
        }]
        assert row['impact_categories_after'] == [{
            'impact_category': IMPACT_CATEGORY_AFTER_NAME,
            'impact_value': _label(IMPACT_AFTER_BASIS, IMPACT_AFTER_NAME),
        }]


@pytest.mark.usefixtures('seeded')
class TestRiskTreatmentPlanReportValues:
    """Every computed column of a Risk Treatment Plan row carries the value of the document it names."""

    def test_the_risk_columns(self, rest_api) -> None:
        """Name, identifier (not the description), category and protection goals come from the risk."""
        row = _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, PERSON_ASSESSMENT_ID)

        assert row['risk_name'] == RISK_NAME
        assert row['risk_identifier'] == RISK_IDENTIFIER
        assert row['risk_category'] == CATEGORY_VALUE
        assert row['protection_goals'] == [PROTECTION_GOAL_NAME]

    def test_the_object_status_and_person_columns(self, rest_api) -> None:
        """The object group, the resolved status and the responsible person's name."""
        row = _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, PERSON_ASSESSMENT_ID)

        assert row['object'] == OBJECT_GROUP_NAME
        assert row['object_type'] == OBJECT_GROUP_TYPE_LABEL
        assert row['implementation_status'] == STATUS_VALUE
        assert row['risk_treatment_option'] == TREATMENT_OPTION
        assert row['responsible_person'] == RESPONSIBLE_NAME

    def test_a_group_reference_shows_the_group(self, rest_api) -> None:
        """With a PERSON_GROUP reference, the responsible column shows the group's name."""
        row = _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, GROUP_ASSESSMENT_ID)

        assert row['responsible_person'] == RESPONSIBLE_GROUP_NAME

    def test_the_risk_badges(self, rest_api) -> None:
        """Each badge shows its own matrix cell's value and its own class's id and colour."""
        row = _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, PERSON_ASSESSMENT_ID)

        assert row['risk_before'] == RISK_BEFORE_BADGE
        assert row['risk_after'] == RISK_AFTER_BADGE

    def test_the_assigned_control_measures(self, rest_api) -> None:
        """Only the controls assigned to THIS assessment are listed - the other assessment has none."""
        assert _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, PERSON_ASSESSMENT_ID)['control_measures'] == [
            CONTROL_MEASURE_TITLE
        ]
        assert _report_row(rest_api, RISK_TREATMENT_PLAN_REPORT, GROUP_ASSESSMENT_ID)['control_measures'] == []
