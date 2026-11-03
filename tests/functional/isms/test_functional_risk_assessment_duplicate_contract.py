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
Functional tests: what ``POST /isms/risk_assessments/duplicate/<mode>/<ids>`` stores, through the real REST app

  - the derived values are the server's, as on create: the maximum impact and likelihood value of both risk
    calculations recomputed from the stored scales, the costs rounded - whatever the payload carried
  - the target ids: each a distinct whole number from 1 to the largest 8-byte integer; anything else is one 400
    naming it, before anything is stored
  - the source has to be stored (404 otherwise)
  - every failed read or insert is its own 400, nothing left behind - and the create route's failed assignment
    insert too

The ISMS licence is stubbed
"""
from http import HTTPStatus
from typing import Any, Iterator
from urllib.parse import quote

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsLikelihood,
    IsmsRiskAssessment,
)
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.control_measure_assignment_manager import ControlMeasureAssignmentManagerInsertError
from cmdb.errors.manager.risk_assessment_manager import (
    RiskAssessmentManagerGetError,
    RiskAssessmentManagerScaleReadError,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_ASSIGNMENT_LABEL,
    DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG,
    DUPLICATE_SOURCE_NOT_FOUND_MSG,
    MAX_DUPLICATE_TARGET_ID,
    RISK_ASSESSMENT_LABEL,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
from tests.functional.isms.test_functional_risk_assessment_route import (
    RISK_ID,
    PERSON_REF,
    _ra_body,
    assignment_entry,
    purge_referenced_persons,
    purge_referenced_risks,
    seed_referenced_persons,
    seed_referenced_risks,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'
SOURCE_ID: int = 98701
MISSING_SOURCE_ID: int = 98709
FIRST_TARGET: int = 98711
SECOND_TARGET: int = 98712
SOURCE_ASSIGNMENT_ID: int = 98721
CONTROL_MEASURE_ID: int = 99295
IMPACT_LOW_ID: int = 98731
IMPACT_HIGH_ID: int = 98732
LIKELIHOOD_ID: int = 98741
IMPACT_LOW_BASIS: float = 7.71
IMPACT_HIGH_BASIS: float = 7.73
LIKELIHOOD_BASIS: float = 7.77
FORGED_IMPACT_ID: int = 999999
FORGED_VALUE: float = 999.0
SENT_COSTS: float = 7.129
ROUNDED_COSTS: float = 7.13
ZERO_TARGET: int = 0
SUPERSCRIPT_TWO: str = '²'

RISK_ID_KEY: str = RiskAssessmentKey.RISK_ID.value
OBJECT_ID_KEY: str = RiskAssessmentKey.OBJECT_ID.value
BEFORE_KEY: str = RiskAssessmentKey.RISK_CALCULATION_BEFORE.value
AFTER_KEY: str = RiskAssessmentKey.RISK_CALCULATION_AFTER.value
COSTS_KEY: str = RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value
TARGETS: list[int] = [FIRST_TARGET, SECOND_TARGET]


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='stored', autouse=True)
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The source with one assignment, the scales and the referenced persons; every duplicate removed afterwards"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
    impacts = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
    likelihoods = database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)

    def _purge() -> None:
        stored_ids: list[int] = [document['public_id'] for document in assessments.find(
            {'$or': [{'public_id': SOURCE_ID}, {RISK_ID_KEY: {'$in': TARGETS}}, {OBJECT_ID_KEY: ZERO_TARGET}]},
            {'public_id': 1},
        )]
        assessments.delete_many({'public_id': {'$in': stored_ids}})
        assignments.delete_many({'risk_assessment_id': {'$in': stored_ids}})
        impacts.delete_many({'public_id': {'$in': [IMPACT_LOW_ID, IMPACT_HIGH_ID]}})
        likelihoods.delete_many({'public_id': LIKELIHOOD_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})
        purge_referenced_persons(database_manager, database_name)
        purge_referenced_risks(database_manager, database_name, (RISK_ID, *TARGETS))

    _purge()
    seed_referenced_persons(database_manager, database_name)
    seed_referenced_risks(database_manager, database_name, (RISK_ID, *TARGETS))
    assessments.insert_one(_ra_body(SOURCE_ID))
    assignments.insert_one({'public_id': SOURCE_ASSIGNMENT_ID, 'risk_assessment_id': SOURCE_ID,
                            'control_measure_id': CONTROL_MEASURE_ID})
    impacts.insert_many([
        {'public_id': IMPACT_LOW_ID, 'name': 'Low', 'calculation_basis': IMPACT_LOW_BASIS},
        {'public_id': IMPACT_HIGH_ID, 'name': 'High', 'calculation_basis': IMPACT_HIGH_BASIS},
    ])
    likelihoods.insert_one({'public_id': LIKELIHOOD_ID, 'name': 'Likely', 'calculation_basis': LIKELIHOOD_BASIS})
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})

    yield assessments

    _purge()


def _duplicates(assessments: Any) -> list[dict[str, Any]]:
    """Every assessment the route stored on the test's targets"""
    return list(assessments.find(
        {'$or': [{RISK_ID_KEY: {'$in': TARGETS}}, {OBJECT_ID_KEY: ZERO_TARGET}]}, {'_id': 0},
    ))


def _duplicate(rest_api: Any, segment: str, body: dict[str, Any] | None = None, mode: str = 'risk',
               copy_cma: bool = False) -> Any:
    """POST the duplicate route"""
    return rest_api.post(f'{ROUTE_URL}/duplicate/{mode}/{segment}?copy_cma={str(copy_cma).lower()}',
                         json=body or _ra_body(SOURCE_ID))


def _forged_calculation() -> dict[str, Any]:
    """A risk calculation whose derived values are made up"""
    return {
        'impacts': [{'impact_category_id': 1, 'impact_id': IMPACT_LOW_ID},
                    {'impact_category_id': 2, 'impact_id': IMPACT_HIGH_ID}],
        'likelihood_id': LIKELIHOOD_ID, 'likelihood_value': FORGED_VALUE,
        'maximum_impact_id': FORGED_IMPACT_ID, 'maximum_impact_value': FORGED_VALUE,
    }


def _raiser(error: Exception) -> Any:
    """A replacement that raises the error"""
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return _fail


class TestTheDerivedValuesAreTheServers:
    """As on create - the payload's values are overwritten, once for every duplicate"""

    def test_both_calculations_are_recomputed_on_every_duplicate(self, rest_api, stored: Any) -> None:
        """The highest impact and the likelihood's basis, not the forged numbers"""
        body: dict[str, Any] = _ra_body(SOURCE_ID, **{BEFORE_KEY: _forged_calculation(),
                                                      AFTER_KEY: _forged_calculation()})

        response = _duplicate(rest_api, f'{FIRST_TARGET},{SECOND_TARGET}', body)

        assert response.status_code == HTTPStatus.OK
        duplicates: list[dict[str, Any]] = _duplicates(stored)
        assert len(duplicates) == len(TARGETS)
        for duplicate in duplicates:
            for key in (BEFORE_KEY, AFTER_KEY):
                calculation: dict[str, Any] = duplicate[key]
                assert (calculation['maximum_impact_id'], calculation['maximum_impact_value'],
                        calculation['likelihood_value']) == (IMPACT_HIGH_ID, IMPACT_HIGH_BASIS, LIKELIHOOD_BASIS)

    def test_the_costs_are_rounded(self, rest_api, stored: Any) -> None:
        """Two decimals, as create keeps"""
        response = _duplicate(rest_api, str(FIRST_TARGET), _ra_body(SOURCE_ID, **{COSTS_KEY: SENT_COSTS}))

        assert response.status_code == HTTPStatus.OK
        assert _duplicates(stored)[0][COSTS_KEY] == ROUNDED_COSTS

    def test_a_failed_scale_read_is_its_own_400(self, rest_api, stored: Any, monkeypatch) -> None:
        """Nothing stored"""
        monkeypatch.setattr(RiskAssessmentManager, 'recalculate_risk_values',
                            _raiser(RiskAssessmentManagerScaleReadError('down')))

        response = _duplicate(rest_api, str(FIRST_TARGET))

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST, manager_error_message(RISK_ASSESSMENT_LABEL, IsmsManagerErrorMessage.SCALE_READ))
        assert not _duplicates(stored)


class TestTheTargetIds:
    """Each a distinct whole number in range - refused before anything is stored"""

    @pytest.mark.parametrize('segment', [
        f'{FIRST_TARGET},abc,-2',
        f'{FIRST_TARGET},{FIRST_TARGET}',
        f'{FIRST_TARGET},{quote(SUPERSCRIPT_TWO)}',
        f'{FIRST_TARGET},{MAX_DUPLICATE_TARGET_ID + 1}',
        f'{FIRST_TARGET},{ZERO_TARGET}',
    ])
    def test_a_bad_target_is_a_400_and_nothing_is_stored(self, rest_api, stored: Any, segment: str) -> None:
        """Not a silent drop, a second copy, a 500 or a failed insert"""
        response = _duplicate(rest_api, segment)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not _duplicates(stored)

    def test_an_object_id_of_zero_is_refused(self, rest_api, stored: Any) -> None:
        """The schema's minimum, which the path used to skip"""
        body: dict[str, Any] = _ra_body(SOURCE_ID)

        response = _duplicate(rest_api, str(ZERO_TARGET), body, mode='object_group')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not _duplicates(stored)

    def test_the_message_names_every_bad_token(self, rest_api) -> None:
        """One refusal for all of them"""
        message: str = _duplicate(rest_api, f'{FIRST_TARGET},abc,-2').get_json()['message']

        assert "'abc'" in message and "'-2'" in message


class TestTheSourceHasToBeStored:
    """The body's public_id decides whose assignments are copied"""

    def test_a_missing_source_is_a_404(self, rest_api, stored: Any) -> None:
        """Nothing stored"""
        response = _duplicate(rest_api, str(FIRST_TARGET), _ra_body(MISSING_SOURCE_ID))

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.NOT_FOUND, DUPLICATE_SOURCE_NOT_FOUND_MSG.format(public_id=MISSING_SOURCE_ID))
        assert not _duplicates(stored)

    def test_a_failed_source_read_is_its_own_400(self, rest_api, stored: Any, monkeypatch) -> None:
        """Nothing stored"""
        monkeypatch.setattr(RiskAssessmentManager, 'find_existing_public_ids',
                            _raiser(RiskAssessmentManagerGetError('down')))

        response = _duplicate(rest_api, str(FIRST_TARGET))

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST, manager_error_message(RISK_ASSESSMENT_LABEL, IsmsManagerErrorMessage.GET_SOURCE))
        assert not _duplicates(stored)

    def test_the_stored_sources_assignments_are_copied(self, rest_api, database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """One copy per duplicate, on the duplicate"""
        response = _duplicate(rest_api, f'{FIRST_TARGET},{SECOND_TARGET}', copy_cma=True)

        created: list[int] = response.get_json()
        copies = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name).find(
            {'risk_assessment_id': {'$in': created}})
        assert sorted(copy['risk_assessment_id'] for copy in copies) == sorted(created)


class TestAFailedAssignmentStepIsA400:
    """Reading the source's assignments, storing their copies - and the create route's assignment insert"""

    def test_a_failed_assignment_read_is_its_own_400(self, rest_api, stored: Any, monkeypatch) -> None:
        """Nothing stored; the scales, read the same way, still read"""
        real = RiskAssessmentManager.get_many_from_other_collection

        def _failing_for_assignments(manager: RiskAssessmentManager, collection: str, *args: Any,
                                     **kwargs: Any) -> list[dict[str, Any]]:
            if collection == IsmsControlMeasureAssignment.COLLECTION:
                raise BaseManagerGetError('down')
            return real(manager, collection, *args, **kwargs)

        monkeypatch.setattr(RiskAssessmentManager, 'get_many_from_other_collection', _failing_for_assignments)

        response = _duplicate(rest_api, str(FIRST_TARGET), copy_cma=True)

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST, DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG)
        assert not _duplicates(stored)

    def test_a_failed_assignment_copy_is_a_400_and_undone(self, rest_api, stored: Any, monkeypatch) -> None:
        """The duplicate stored before it is taken back"""
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_many_items',
                            _raiser(ControlMeasureAssignmentManagerInsertError('down')))

        response = _duplicate(rest_api, str(FIRST_TARGET), copy_cma=True)

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST,
            manager_error_message(CONTROL_MEASURE_ASSIGNMENT_LABEL, IsmsManagerErrorMessage.INSERT))
        assert not _duplicates(stored)

    def test_a_failed_assignment_insert_on_create_is_a_400_and_undone(
            self, rest_api, stored: Any, monkeypatch) -> None:
        """The created assessment is taken back"""
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_many_items',
                            _raiser(ControlMeasureAssignmentManagerInsertError('down')))
        body: dict[str, Any] = _ra_body(SOURCE_ID, **{
            RISK_ID_KEY: FIRST_TARGET, 'control_measure_assignments': [assignment_entry(
                CONTROL_MEASURE_ID, responsible_for_implementation_id_ref_type=PERSON_REF)],
        })

        response = rest_api.post(f'{ROUTE_URL}/', json=body)

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST,
            manager_error_message(CONTROL_MEASURE_ASSIGNMENT_LABEL, IsmsManagerErrorMessage.INSERT))
        assert not _duplicates(stored)
