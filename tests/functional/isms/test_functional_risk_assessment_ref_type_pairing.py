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
Functional tests for the pairing of a RiskAssessment's person ids with their ``_ref_type``, through the real app

A ``_ref_type`` (owner, responsible persons, auditor) may be null exactly while its id is. Pinned:

  - an assessment without an owner is refused as one - the required-field guard names ``risk_owner_id`` - whatever
    its ``_ref_type`` says
  - a set id beside a null ``_ref_type`` is refused naming the key: on create, on update when the type changed,
    and on the duplicate route
  - an assessment with no responsible person and no auditor, and null types for both, is stored as sent
  - an update re-saving such an assessment unchanged still passes
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import UNKNOWN_PERSON_REFERENCE_TYPE_MSG

from tests.functional.isms.test_functional_risk_assessment_route import (
    PERSON_GROUP_ID,
    PERSON_ID,
    RISK_ID,
    _ra_body,
    purge_referenced_persons,
    seed_referenced_persons,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'

STORED_RA_ID: int = 98801
MARKER_KEY: str = RiskAssessmentKey.ADDITIONAL_INFO.value
MARKER: str = 'ref-type-pairing-marker'

OWNER_KEY: str = RiskAssessmentKey.RISK_OWNER_ID.value
OWNER_TYPE_KEY: str = RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value
RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
RESPONSIBLE_TYPE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value
AUDITOR_KEY: str = RiskAssessmentKey.AUDITOR_ID.value
AUDITOR_TYPE_KEY: str = RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value

PERSON: str = PersonReferenceType.PERSON.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value
MISSING_OWNER_MSG: str = f'missing required field(s): {OWNER_KEY}'
# The leading text of the refusal for a reference naming no known type
UNKNOWN_TYPE_PREFIX: str = UNKNOWN_PERSON_REFERENCE_TYPE_MSG.split('{', 1)[0]

# (id key, type key, the id a set reference carries)
PAIRS: list[Any] = [
    pytest.param(OWNER_KEY, OWNER_TYPE_KEY, PERSON_ID, id='owner'),
    pytest.param(RESPONSIBLE_KEY, RESPONSIBLE_TYPE_KEY, PERSON_GROUP_ID, id='responsible'),
    pytest.param(AUDITOR_KEY, AUDITOR_TYPE_KEY, PERSON_ID, id='auditor'),
]


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='assessments', autouse=True)
def fixture_assessments(database_manager: MongoDatabaseManager, database_name: str):
    """The assessment collection with the referenced persons seeded; what the tests write is purged after"""
    collection = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{MARKER_KEY: MARKER}, {'public_id': STORED_RA_ID}]})
        purge_referenced_persons(database_manager, database_name)

    _purge()
    seed_referenced_persons(database_manager, database_name)
    yield collection
    _purge()


def _body(**overrides: Any) -> dict[str, Any]:
    """A complete assessment body carrying the marker"""
    return _ra_body(STORED_RA_ID, **{MARKER_KEY: MARKER, **overrides})


def _assert_refused(response: Any, fragment: str) -> None:
    """A 400 whose message holds the fragment"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()
    assert fragment in response.get_json()['message'], response.get_json()['message']


class TestAMissingOwner:
    """No owner is reported as no owner, whatever the type beside it"""

    @pytest.mark.parametrize('owner_type', [None, PERSON, PERSON_GROUP])
    def test_on_create(self, rest_api, assessments, owner_type: Any) -> None:
        """The guard's message, naming risk_owner_id, and nothing stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(**{OWNER_KEY: None, OWNER_TYPE_KEY: owner_type}))

        _assert_refused(response, MISSING_OWNER_MSG)
        assert assessments.count_documents({MARKER_KEY: MARKER}) == 0

    def test_on_update(self, rest_api, assessments) -> None:
        """The stored assessment unchanged"""
        assessments.insert_one(_body())

        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_body(**{OWNER_KEY: None, OWNER_TYPE_KEY: None}))

        _assert_refused(response, MISSING_OWNER_MSG)
        assert assessments.find_one({'public_id': STORED_RA_ID})[OWNER_KEY] == PERSON_ID


class TestASetIdWithoutAType:
    """An id says nothing about its collection without its type"""

    @pytest.mark.parametrize('id_key, type_key, referenced_id', PAIRS)
    def test_on_create(self, rest_api, assessments, id_key: str, type_key: str, referenced_id: int) -> None:
        """Refused naming the key, nothing stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(**{id_key: referenced_id, type_key: None}))

        _assert_refused(response, UNKNOWN_TYPE_PREFIX)
        assert f"'{id_key}'" in response.get_json()['message']
        assert assessments.count_documents({MARKER_KEY: MARKER}) == 0

    @pytest.mark.parametrize('id_key, type_key, referenced_id', PAIRS)
    def test_on_update_when_the_type_changes(self, rest_api, assessments, id_key: str, type_key: str,
                                             referenced_id: int) -> None:
        """A stored reference whose type is blanked is a new reference, judged like one"""
        stored_type: str = PERSON_GROUP if referenced_id == PERSON_GROUP_ID else PERSON
        assessments.insert_one(_body(**{id_key: referenced_id, type_key: stored_type}))

        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_body(**{id_key: referenced_id, type_key: None}))

        _assert_refused(response, UNKNOWN_TYPE_PREFIX)
        assert assessments.find_one({'public_id': STORED_RA_ID})[type_key] == stored_type

    def test_on_the_duplicate_route(self, rest_api, assessments) -> None:
        """Every duplicate would carry the source's references, so they are judged in full"""
        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{RISK_ID}?copy_cma=false',
                                 json=_body(**{AUDITOR_KEY: PERSON_ID, AUDITOR_TYPE_KEY: None}))

        _assert_refused(response, UNKNOWN_TYPE_PREFIX)
        assert assessments.count_documents({MARKER_KEY: MARKER}) == 0


class TestNoReferenceNoType:
    """An empty reference may carry a null type"""

    def test_a_create_without_responsible_and_auditor_stores_both_pairs_null(self, rest_api, assessments) -> None:
        """Stored as sent"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(**{
            RESPONSIBLE_KEY: None, RESPONSIBLE_TYPE_KEY: None, AUDITOR_KEY: None, AUDITOR_TYPE_KEY: None,
        }))

        assert response.status_code == HTTPStatus.CREATED, response.get_json()
        stored: dict[str, Any] = assessments.find_one({'public_id': response.get_json()['result_id']})
        assert [stored[key] for key in (RESPONSIBLE_KEY, RESPONSIBLE_TYPE_KEY, AUDITOR_KEY, AUDITOR_TYPE_KEY)] \
            == [None, None, None, None]

    def test_an_unchanged_resave_passes(self, rest_api, assessments) -> None:
        """The stored null pairs are no new references"""
        body: dict[str, Any] = _body(**{AUDITOR_KEY: None, AUDITOR_TYPE_KEY: None})
        assessments.insert_one(dict(body))

        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=body)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert assessments.find_one({'public_id': STORED_RA_ID})[AUDITOR_TYPE_KEY] is None

    def test_the_frontend_shape_still_passes(self, rest_api, assessments) -> None:
        """An owner with its type, the other two empty with PERSON - what the form sends"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body())

        assert response.status_code == HTTPStatus.CREATED, response.get_json()
