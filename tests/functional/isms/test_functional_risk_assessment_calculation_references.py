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
Functional tests for the risk-calculation ids and implementation states of a RiskAssessment write, over HTTP

Pinned on create, update and duplicate:

  - an ``impact_category_id``, ``impact_id``, ``likelihood_id`` or ``implementation_status`` of 0, a negative number
    or a JSON boolean is a 400 naming the field - each used to be stored (``true`` read as id 1 by the
    recalculation) - and nothing is written
  - an ImpactCategory, Impact or Likelihood that is not stored is a 400 naming every one with its field path
  - one ImpactCategory rated twice in a matrix is a 400
  - an implementation state that is no IMPLEMENTATION_STATE option - missing, or an option of another list - is a 400,
    the assessment's own and an embedded assignment's alike
  - a failed ImpactCategory or option read is its own 400, not a 500
  - a stored calculation passes, its derived values computed from the stored scales (the control)
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.extendable_options_manager import ExtendableOptionsManagerGetError
from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsLikelihood,
    IsmsRiskAssessment,
)
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    DUPLICATE_IMPACT_CATEGORIES_MSG,
    IMPACT_CATEGORY_LOOKUP_FAILED_MSG,
    IMPLEMENTATION_STATE_LOOKUP_FAILED_MSG,
    RISK_CALCULATION_REASON,
    RISK_CALCULATION_REASON_SEPARATOR,
    UNKNOWN_IMPLEMENTATION_STATES_MSG,
    UNKNOWN_RISK_CALCULATION_REFERENCES_MSG,
)
from tests.functional.isms.test_functional_risk_assessment_route import (
    CONTROL_MEASURE_ID,
    RISK_ID,
    _ra_body,
    assignment_entry,
    purge_referenced_persons,
    purge_referenced_risks,
    seed_referenced_persons,
    seed_referenced_risks,
)
from tests.utils.isms_reference_seed import (
    IMPACT_CATEGORY_IDS,
    IMPLEMENTATION_STATE_ID,
    MISSING_IMPACT_CATEGORY_ID,
    MISSING_OPTION_ID,
    OTHER_LIST_OPTION_ID,
    purge_impact_categories,
    seed_impact_categories,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'
MESSAGE_KEY: str = 'message'
NEW_RA_ID: int = 99801
STORED_RA_ID: int = 99802
SECOND_RISK_ID: int = 99803
IMPACT_LOW_ID: int = 99811
IMPACT_HIGH_ID: int = 99812
MISSING_IMPACT_ID: int = 99819
LIKELIHOOD_ID: int = 99821
MISSING_LIKELIHOOD_ID: int = 99829
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
BASIS_LIKELIHOOD: float = 2.0
CATEGORY_A, CATEGORY_B = IMPACT_CATEGORY_IDS
BEFORE: str = 'risk_calculation_before'
AFTER: str = 'risk_calculation_after'
SENT_RISK_IDS: list[int] = [RISK_ID, SECOND_RISK_ID]
NOT_AN_ID: list[Any] = [0, -1, True]
NOT_AN_ID_NAMES: list[str] = ['zero', 'negative', 'true']
UNKNOWN_STATES: list[int] = [MISSING_OPTION_ID, OTHER_LIST_OPTION_ID]
UNKNOWN_STATE_NAMES: list[str] = ['missing', 'other-list']


def _row(category: Any, impact: Any = None) -> dict[str, Any]:
    """One impacts row"""
    return {'impact_category_id': category, 'impact_id': impact}


def _matrix(rows: list[dict[str, Any]] | None = None, likelihood: Any = None) -> dict[str, Any]:
    """One matrix as the frontend sends it, the derived values null"""
    return {'impacts': rows if rows is not None else [], 'likelihood_id': likelihood, 'likelihood_value': None,
            'maximum_impact_id': None, 'maximum_impact_value': None}


def _rated(**overrides: Any) -> dict[str, Any]:
    """A body rating both categories before treatment, with a stored state"""
    return _ra_body(NEW_RA_ID, **{
        BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW_ID), _row(CATEGORY_B, IMPACT_HIGH_ID)], LIKELIHOOD_ID),
        AFTER: _matrix(),
        'implementation_status': IMPLEMENTATION_STATE_ID,
        **overrides,
    })


def _reason(field: str, ids: list[int]) -> str:
    """One reason of a refusal"""
    return RISK_CALCULATION_REASON.format(field=field, ids=ids)


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='assessments', autouse=True)
def fixture_assessments(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Persons, Risks, the scales, the categories, a ControlMeasure and one stored assessment; all removed again"""
    collection = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    impacts = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
    likelihoods = database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        stored: list[int] = [document['public_id'] for document in collection.find(
            {'$or': [{'public_id': {'$in': [NEW_RA_ID, STORED_RA_ID]}}, {'risk_id': {'$in': SENT_RISK_IDS}}]},
            {'public_id': 1},
        )]
        collection.delete_many({'public_id': {'$in': stored}})
        assignments.delete_many({'risk_assessment_id': {'$in': stored}})
        impacts.delete_many({'public_id': {'$in': [IMPACT_LOW_ID, IMPACT_HIGH_ID]}})
        likelihoods.delete_many({'public_id': LIKELIHOOD_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})
        purge_impact_categories(database_manager, database_name)
        purge_referenced_persons(database_manager, database_name)
        purge_referenced_risks(database_manager, database_name, tuple(SENT_RISK_IDS))

    _purge()
    seed_referenced_persons(database_manager, database_name)
    seed_referenced_risks(database_manager, database_name, tuple(SENT_RISK_IDS))
    seed_impact_categories(database_manager, database_name)
    impacts.insert_many([{'public_id': IMPACT_LOW_ID, 'name': 'Low', 'calculation_basis': BASIS_LOW},
                         {'public_id': IMPACT_HIGH_ID, 'name': 'High', 'calculation_basis': BASIS_HIGH}])
    likelihoods.insert_one({'public_id': LIKELIHOOD_ID, 'name': 'Likely', 'calculation_basis': BASIS_LIKELIHOOD})
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})
    collection.insert_one(_ra_body(STORED_RA_ID))
    yield collection
    _purge()


def _written(assessments: Any) -> int:
    """How many assessments the tests wrote: every one but the stored one"""
    return assessments.count_documents({'public_id': {'$ne': STORED_RA_ID}, 'risk_id': {'$in': SENT_RISK_IDS}})


def _refused(response: Any, message: str) -> None:
    """A 400 with exactly this message"""
    assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (HTTPStatus.BAD_REQUEST, message)


def _unknown(*reasons: str) -> str:
    """The unknown-reference 400's message"""
    return UNKNOWN_RISK_CALCULATION_REFERENCES_MSG.format(reasons=RISK_CALCULATION_REASON_SEPARATOR.join(reasons))


# Each id field of the risk calculation, as the body sets it to a value
ID_FIELDS: dict[str, Any] = {
    'impact_category_id': lambda value: {BEFORE: _matrix([_row(value)])},
    'impact_id': lambda value: {BEFORE: _matrix([_row(CATEGORY_A, value)])},
    'likelihood_id': lambda value: {AFTER: _matrix(likelihood=value)},
    'implementation_status': lambda value: {'implementation_status': value},
}


class TestCreate:
    """POST /isms/risk_assessments/"""

    def test_a_stored_calculation_passes_and_is_derived(self, rest_api, assessments) -> None:
        """The control: the highest impact and the likelihood's basis are stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rated())

        assert response.status_code == HTTPStatus.CREATED
        stored: dict[str, Any] = assessments.find_one({'public_id': response.get_json()['result_id']})[BEFORE]
        assert (stored['maximum_impact_id'], stored['maximum_impact_value'], stored['likelihood_value']) == (
            IMPACT_HIGH_ID, BASIS_HIGH, BASIS_LIKELIHOOD,
        )

    @pytest.mark.parametrize('field', list(ID_FIELDS))
    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_an_id_that_is_no_id_is_a_400_naming_the_field(self, rest_api, assessments, field: str,
                                                           value: Any) -> None:
        """Each used to be stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rated(**ID_FIELDS[field](value)))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert field in response.get_json()[MESSAGE_KEY]
        assert _written(assessments) == 0

    def test_every_unknown_reference_is_named_with_its_field_path(self, rest_api, assessments) -> None:
        """One 400 for all of them, in document order"""
        body: dict[str, Any] = _rated(**{
            BEFORE: _matrix([_row(MISSING_IMPACT_CATEGORY_ID, MISSING_IMPACT_ID)], MISSING_LIKELIHOOD_ID),
            AFTER: _matrix([_row(CATEGORY_A, MISSING_IMPACT_ID)]),
        })

        _refused(rest_api.post(f'{ROUTE_URL}/', json=body), _unknown(
            _reason(f'{BEFORE}.impacts.impact_category_id', [MISSING_IMPACT_CATEGORY_ID]),
            _reason(f'{BEFORE}.impacts.impact_id', [MISSING_IMPACT_ID]),
            _reason(f'{BEFORE}.likelihood_id', [MISSING_LIKELIHOOD_ID]),
            _reason(f'{AFTER}.impacts.impact_id', [MISSING_IMPACT_ID]),
        ))
        assert _written(assessments) == 0

    def test_a_category_rated_twice_is_a_400(self, rest_api, assessments) -> None:
        """The report would list it twice"""
        body: dict[str, Any] = _rated(**{BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW_ID),
                                                          _row(CATEGORY_A, IMPACT_HIGH_ID)])})

        _refused(rest_api.post(f'{ROUTE_URL}/', json=body), DUPLICATE_IMPACT_CATEGORIES_MSG.format(
            reasons=_reason(f'{BEFORE}.impacts', [CATEGORY_A]),
        ))
        assert _written(assessments) == 0

    def test_a_category_left_out_is_legal(self, rest_api, assessments) -> None:
        """It reads as unrated"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_rated(**{BEFORE: _matrix([_row(CATEGORY_A)])}))

        assert response.status_code == HTTPStatus.CREATED

    @pytest.mark.parametrize('state', UNKNOWN_STATES, ids=UNKNOWN_STATE_NAMES)
    def test_a_state_that_is_no_implementation_state_is_a_400(self, rest_api, assessments, state: int) -> None:
        """An option of another list as much as a missing one"""
        _refused(rest_api.post(f'{ROUTE_URL}/', json=_rated(implementation_status=state)),
                 UNKNOWN_IMPLEMENTATION_STATES_MSG.format(unknown=[state]))
        assert _written(assessments) == 0

    def test_an_embedded_assignments_unknown_state_is_a_400(self, rest_api, assessments) -> None:
        """The assignments are stored with the assessment, so their states are judged with it"""
        body: dict[str, Any] = _rated(control_measure_assignments=[
            assignment_entry(implementation_status=OTHER_LIST_OPTION_ID),
        ])

        _refused(rest_api.post(f'{ROUTE_URL}/', json=body),
                 UNKNOWN_IMPLEMENTATION_STATES_MSG.format(unknown=[OTHER_LIST_OPTION_ID]))
        assert _written(assessments) == 0

    def test_a_failed_category_read_is_its_own_400(self, rest_api, assessments, monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('categories unreadable')

        monkeypatch.setattr(RiskAssessmentManager, 'get_missing_impact_category_ids', _failing)

        _refused(rest_api.post(f'{ROUTE_URL}/', json=_rated()), IMPACT_CATEGORY_LOOKUP_FAILED_MSG)
        assert _written(assessments) == 0

    def test_a_failed_option_read_is_its_own_400(self, rest_api, assessments, monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise ExtendableOptionsManagerGetError('options unreadable')

        monkeypatch.setattr(ExtendableOptionsManager, 'get_missing_option_ids', _failing)

        _refused(rest_api.post(f'{ROUTE_URL}/', json=_rated()), IMPLEMENTATION_STATE_LOOKUP_FAILED_MSG)
        assert _written(assessments) == 0


class TestUpdate:
    """PUT /isms/risk_assessments/<id>"""

    def test_a_stored_calculation_passes(self, rest_api, assessments) -> None:
        """The control"""
        body: dict[str, Any] = {**_rated(), 'public_id': STORED_RA_ID}

        assert rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=body).status_code == HTTPStatus.ACCEPTED
        assert assessments.find_one({'public_id': STORED_RA_ID})[BEFORE]['maximum_impact_id'] == IMPACT_HIGH_ID

    def test_an_unknown_impact_is_a_400_and_nothing_changes(self, rest_api, assessments) -> None:
        """The stored calculation is kept"""
        stored_before: dict[str, Any] = assessments.find_one({'public_id': STORED_RA_ID})
        body: dict[str, Any] = {**_rated(**{BEFORE: _matrix([_row(CATEGORY_A, MISSING_IMPACT_ID)])}),
                                'public_id': STORED_RA_ID}

        _refused(rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=body),
                 _unknown(_reason(f'{BEFORE}.impacts.impact_id', [MISSING_IMPACT_ID])))
        assert assessments.find_one({'public_id': STORED_RA_ID}) == stored_before

    def test_a_created_assignments_unknown_state_is_a_400(self, rest_api, assessments) -> None:
        """Before any assignment is written"""
        body: dict[str, Any] = {**_rated(control_measure_assignments={
            'created': [assignment_entry(implementation_status=MISSING_OPTION_ID)], 'updated': [], 'deleted': [],
        }), 'public_id': STORED_RA_ID}

        _refused(rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=body),
                 UNKNOWN_IMPLEMENTATION_STATES_MSG.format(unknown=[MISSING_OPTION_ID]))


class TestDuplicate:
    """POST /isms/risk_assessments/duplicate/<mode>/<ids>"""

    def test_an_unknown_likelihood_writes_no_copy(self, rest_api, assessments) -> None:
        """Checked once, before the first copy"""
        body: dict[str, Any] = {**_rated(**{AFTER: _matrix(likelihood=MISSING_LIKELIHOOD_ID)}),
                                'public_id': STORED_RA_ID}

        _refused(rest_api.post(f'{ROUTE_URL}/duplicate/risk/{SECOND_RISK_ID}?copy_cma=false', json=body),
                 _unknown(_reason(f'{AFTER}.likelihood_id', [MISSING_LIKELIHOOD_ID])))
        assert _written(assessments) == 0

    def test_an_unknown_state_writes_no_copy(self, rest_api, assessments) -> None:
        """The copies carry the payload's state"""
        body: dict[str, Any] = {**_rated(implementation_status=OTHER_LIST_OPTION_ID), 'public_id': STORED_RA_ID}

        _refused(rest_api.post(f'{ROUTE_URL}/duplicate/risk/{SECOND_RISK_ID}?copy_cma=false', json=body),
                 UNKNOWN_IMPLEMENTATION_STATES_MSG.format(unknown=[OTHER_LIST_OPTION_ID]))
        assert _written(assessments) == 0

    def test_a_stored_calculation_is_copied(self, rest_api, assessments) -> None:
        """The control"""
        body: dict[str, Any] = {**_rated(), 'public_id': STORED_RA_ID}

        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{SECOND_RISK_ID}?copy_cma=false', json=body)

        assert response.status_code == HTTPStatus.OK
        assert _written(assessments) == 1
