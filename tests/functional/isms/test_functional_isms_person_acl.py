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
Functional coverage for the type ACL on persons and groups named by an ISMS document

Persons are objects of a Type carrying PERSON. A reader holding the ISMS rights but no READ on a person's Type:

  - writes no assessment naming that person (403, nothing stored) - the administrator does
  - sees the assessment, but not that person's name: the list's naming leaves it out, both risk reports leave the
    responsible person blank - a readable person is named as before, and the administrator sees every name
"""
import json
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    RiskAssessmentReportKey,
    RiskTreatmentPlanReportKey,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    RISK_ASSESSMENT_NAMING_KEY,
    RiskAssessmentNamingKey,
)
from tests.functional.isms.test_functional_risk_assessment_route import (
    PERSON_ID,
    _ra_body,
    purge_referenced_persons,
    purge_referenced_risks,
    seed_referenced_persons,
    seed_referenced_risks,
)
from tests.utils.person_objects import person_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

RA_URL: str = '/isms/risk_assessments'
REPORTS_URL: str = '/isms/reports'

HIDDEN_TYPE_ID: int = 96601
HIDDEN_PERSON_ID: int = 96602
HIDDEN_NAME: str = 'Hidden Person'
STORED_RA_ID: int = 96610
CREATED_RA_ID: int = 96611
# The id of a created assessment is the server's: what this module creates carries the marker instead
MARKER_KEY: str = RiskAssessmentKey.ADDITIONAL_INFO.value
MARKER: str = 'isms-person-acl-marker'
READER_GROUP_ID: int = 96620
READER_ID: int = 96621
READER_NAME: str = 'isms-person-acl-reader'
READER_RIGHTS: list[str] = ['base.isms.*', 'base.framework.object.view']

HIDDEN_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {
    str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}}}


def _hidden_type() -> dict[str, Any]:
    """A PERSON Type only the administrators may read"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, 'isms-hidden-person', HIDDEN_TYPE_ID)
    document.update({'system_type': False, 'acl': HIDDEN_ACL})

    return document


def _hidden_person() -> dict[str, Any]:
    """The person of the hidden Type"""
    document: dict[str, Any] = person_object_doc(HIDDEN_PERSON_ID, SpecialType.PERSON, HIDDEN_NAME)
    document['type_id'] = HIDDEN_TYPE_ID

    return document


SEEDS: dict[str, list[dict[str, Any]]] = {
    CmdbType.COLLECTION: [_hidden_type()],
    CmdbObject.COLLECTION: [_hidden_person()],
    IsmsRiskAssessment.COLLECTION: [_ra_body(
        STORED_RA_ID, responsible_persons_id=HIDDEN_PERSON_ID, interviewed_persons=[PERSON_ID, HIDDEN_PERSON_ID],
        risk_assessment_date=datetime.now(timezone.utc),
    )],
    CmdbUserGroup.COLLECTION: [
        {'public_id': READER_GROUP_ID, 'name': READER_NAME, 'label': READER_NAME, 'rights': READER_RIGHTS},
    ],
    CmdbUser.COLLECTION: [{'public_id': READER_ID, 'user_name': READER_NAME, 'active': True,
                           'group_id': READER_GROUP_ID, 'registration_time': datetime.now(timezone.utc)}],
}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The open person (the shared seed), the hidden Type and person, the assessment and the reader"""
    collection = partial(database_manager.get_collection, db_name=database_name)

    def _purge() -> None:
        for name, docs in SEEDS.items():
            collection(name).delete_many({'public_id': {'$in': [doc['public_id'] for doc in docs]}})

        collection(IsmsRiskAssessment.COLLECTION).delete_many({MARKER_KEY: MARKER})
        purge_referenced_persons(database_manager, database_name)
        purge_referenced_risks(database_manager, database_name)

    _purge()
    seed_referenced_persons(database_manager, database_name)
    seed_referenced_risks(database_manager, database_name)

    for name, docs in SEEDS.items():
        collection(name).insert_many([dict(doc) for doc in docs])

    yield collection(IsmsRiskAssessment.COLLECTION)

    _purge()


@pytest.fixture(name='reader')
def fixture_reader() -> CmdbUser:
    """The seeded reader: every ISMS right, no READ on the hidden person Type"""
    return CmdbUser(public_id=READER_ID, user_name=READER_NAME, active=True, group_id=READER_GROUP_ID)


def _created_body() -> dict[str, Any]:
    """An assessment naming the hidden person as responsible, carrying the marker"""
    return _ra_body(CREATED_RA_ID, responsible_persons_id=HIDDEN_PERSON_ID, **{MARKER_KEY: MARKER})


def _naming(rest_api, **kwargs: Any) -> dict[str, Any]:
    """The naming block of the stored assessment in the list"""
    response = rest_api.get(f'{RA_URL}/', query_string={
        'limit': 0, 'filter': json.dumps({'public_id': STORED_RA_ID})}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return response.get_json()['results'][0][RISK_ASSESSMENT_NAMING_KEY]


def _report_value(rest_api, report: str, column: str, **kwargs: Any) -> Any:
    """One column of the stored assessment's report row"""
    response = rest_api.get(f'{REPORTS_URL}/{report}', query_string={
        'limit': 0, 'filter': json.dumps({'public_id': STORED_RA_ID})}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return response.get_json()['results'][0].get(column)


class TestWriting:
    """A write naming a person the writer may not read"""

    def test_the_reader_is_forbidden_and_nothing_is_stored(self, rest_api, reader: CmdbUser, _seeded) -> None:
        """403 naming the id"""
        response = rest_api.post(f'{RA_URL}/', json=_created_body(), user=reader)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert str(HIDDEN_PERSON_ID) in response.get_json()['message']
        assert _seeded.count_documents({MARKER_KEY: MARKER}) == 0

    def test_the_administrator_may(self, rest_api) -> None:
        """The same body is stored"""
        response = rest_api.post(f'{RA_URL}/', json=_created_body())

        assert response.status_code == HTTPStatus.CREATED, response.get_json()


class TestReading:
    """The hidden person's name is left out for the reader, shown to the administrator"""

    def test_the_list_naming(self, rest_api, reader: CmdbUser) -> None:
        """No responsible name; only the readable interviewee named"""
        naming = _naming(rest_api, user=reader)

        assert naming[RiskAssessmentNamingKey.RESPONSIBLE_PERSONS_ID_NAME.value] is None
        assert HIDDEN_NAME not in naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value]
        assert len(naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value]) == 1

    def test_the_list_naming_of_the_administrator(self, rest_api) -> None:
        """Every name"""
        naming = _naming(rest_api)

        assert naming[RiskAssessmentNamingKey.RESPONSIBLE_PERSONS_ID_NAME.value] == HIDDEN_NAME
        assert HIDDEN_NAME in naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value]

    @pytest.mark.parametrize('report, column', [
        ('risk_assessments', RiskAssessmentReportKey.RESPONSIBLE_PERSON.value),
        ('risk_treatment_plan', RiskTreatmentPlanReportKey.RESPONSIBLE_PERSON.value),
    ])
    def test_the_reports(self, rest_api, reader: CmdbUser, report: str, column: str) -> None:
        """Blank for the reader, named for the administrator"""
        assert not _report_value(rest_api, report, column, user=reader)
        assert _report_value(rest_api, report, column) == HIDDEN_NAME
