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
Integration tests for a RiskAssessment stored with null person ``_ref_type`` pairs, against the real collections

An assessment with no responsible person and no auditor may store both pairs as null. Every reader of those
fields copes:

  - the model reads the document back and writes it out unchanged
  - the risk-assessment report names nobody for both, and still names the people of an assessment that has them
  - the person and person-group delete cascades leave the null pairs alone - their criteria match nothing there
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.person_reference_helper import risk_assessment_reference_criteria
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import RiskAssessmentReportKey
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    risk_assessment_report_projection_stage,
    risk_assessment_report_stages,
)

from tests.functional.isms.test_functional_risk_assessment_route import _ra_body
# -------------------------------------------------------------------------------------------------------------------- #

EMPTY_RA_ID: int = 98701
STAFFED_RA_ID: int = 98702
RISK_ID: int = 98711
PERSON_ID: int = 98721
# The empty assessment's owner: anyone but PERSON_ID, so a cascade match on it could only come from a null pair
OTHER_OWNER_ID: int = 98723
GROUP_ID: int = 98722
PERSON_NAME: str = 'Null pair person'
GROUP_NAME: str = 'Null pair group'
RA_IDS: list[int] = [EMPTY_RA_ID, STAFFED_RA_ID]

RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
RESPONSIBLE_TYPE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value
AUDITOR_KEY: str = RiskAssessmentKey.AUDITOR_ID.value
AUDITOR_TYPE_KEY: str = RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value
REPORT_RESPONSIBLE_KEY: str = RiskAssessmentReportKey.RESPONSIBLE_PERSON.value
REPORT_AUDITOR_KEY: str = RiskAssessmentReportKey.AUDITOR.value
NULL_PAIRS: dict[str, Any] = {RESPONSIBLE_KEY: None, RESPONSIBLE_TYPE_KEY: None, AUDITOR_KEY: None,
                              AUDITOR_TYPE_KEY: None}


def _assessment(public_id: int, owner_id: int, **overrides: Any) -> dict[str, Any]:
    """A stored assessment of RISK_ID owned by the given person"""
    return _ra_body(public_id, risk_id=RISK_ID, risk_owner_id=owner_id, **overrides)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """An assessment with null pairs, one with a group responsible and a person auditor; purged after"""
    collections: dict[str, Any] = {
        'assessments': database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name),
        'risks': database_manager.get_collection(IsmsRisk.COLLECTION, database_name),
        'persons': database_manager.get_collection(CmdbPerson.COLLECTION, database_name),
        'groups': database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name),
    }

    def _purge() -> None:
        collections['assessments'].delete_many({'public_id': {'$in': RA_IDS}})
        collections['risks'].delete_many({'public_id': RISK_ID})
        collections['persons'].delete_many({'public_id': PERSON_ID})
        collections['groups'].delete_many({'public_id': GROUP_ID})

    _purge()
    collections['risks'].insert_one({'public_id': RISK_ID, 'name': 'Null pair risk'})
    collections['persons'].insert_one({'public_id': PERSON_ID, 'display_name': PERSON_NAME})
    collections['groups'].insert_one({'public_id': GROUP_ID, 'name': GROUP_NAME})
    collections['assessments'].insert_many([
        _assessment(EMPTY_RA_ID, OTHER_OWNER_ID, **NULL_PAIRS),
        _assessment(STAFFED_RA_ID, PERSON_ID, **{
            RESPONSIBLE_KEY: GROUP_ID, RESPONSIBLE_TYPE_KEY: PersonReferenceType.PERSON_GROUP.value,
            AUDITOR_KEY: PERSON_ID, AUDITOR_TYPE_KEY: PersonReferenceType.PERSON.value,
        }),
    ])
    yield collections
    _purge()


def test_the_model_reads_the_null_pairs_back_unchanged(database_manager) -> None:
    """Read through the manager and written out by the model, the pairs are still null"""
    stored: dict[str, Any] = RiskAssessmentManager(database_manager).get_item(EMPTY_RA_ID, as_dict=True)

    written: dict[str, Any] = IsmsRiskAssessment.to_json(IsmsRiskAssessment.from_data(stored))

    assert {key: written[key] for key in NULL_PAIRS} == NULL_PAIRS


def test_the_report_names_nobody_for_a_null_pair(collections) -> None:
    """Nobody for the null pairs; the group and the person of the staffed assessment by name"""
    rows: dict[int, dict[str, Any]] = {
        row['public_id']: row
        for row in collections['assessments'].aggregate([
            {'$match': {'public_id': {'$in': RA_IDS}}},
            *risk_assessment_report_stages(),
            risk_assessment_report_projection_stage(),
        ])
    }

    assert (rows[EMPTY_RA_ID][REPORT_RESPONSIBLE_KEY], rows[EMPTY_RA_ID][REPORT_AUDITOR_KEY]) == (None, None)
    assert (rows[STAFFED_RA_ID][REPORT_RESPONSIBLE_KEY], rows[STAFFED_RA_ID][REPORT_AUDITOR_KEY]) \
        == (GROUP_NAME, PERSON_NAME)


@pytest.mark.parametrize('referenced_id, reference_type', [
    (PERSON_ID, PersonReferenceType.PERSON), (GROUP_ID, PersonReferenceType.PERSON_GROUP),
])
def test_the_delete_cascades_do_not_match_a_null_pair(collections, referenced_id: int,
                                                      reference_type: PersonReferenceType) -> None:
    """The cascade criteria pair the id with its type, so a null pair is no one's reference"""
    matched: set[int] = {
        doc['public_id']
        for doc in collections['assessments'].find({
            '$and': [risk_assessment_reference_criteria(referenced_id, reference_type),
                     {'public_id': {'$in': RA_IDS}}],
        })
    }

    assert EMPTY_RA_ID not in matched
    assert STAFFED_RA_ID in matched
