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
Functional tests for the Risk and the ids of a RiskAssessment write, over HTTP

Pinned on create, update and duplicate:

  - ``risk_id`` 0, a negative number, a JSON boolean or a Risk that is not stored is a 400 - each used to be stored
    (``true`` as a boolean in an id field) - and nothing is written
  - a risk-mode duplicate refuses a target that names no stored Risk, writing none of the copies
  - ``object_id: true`` and an interviewed person ``true`` are refused like any other id that is no whole number
  - a failed read of the Risks is its own 400, not a 500
  - a stored Risk still passes (the control)
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    RISK_ASSESSMENT_LABEL,
    UNKNOWN_RISKS_MSG,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
from tests.functional.isms.test_functional_risk_assessment_route import (
    RISK_ID,
    _ra_body,
    purge_referenced_persons,
    purge_referenced_risks,
    seed_referenced_persons,
    seed_referenced_risks,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'
MESSAGE_KEY: str = 'message'
NEW_RA_ID: int = 99701
STORED_RA_ID: int = 99702
MISSING_RISK_ID: int = 99799
SECOND_RISK_ID: int = 99703
# Every risk_id a test here sends - what it wrote is found by these (the schema drops any marker key)
SENT_RISK_IDS: list[Any] = [RISK_ID, SECOND_RISK_ID, MISSING_RISK_ID, 0, -1, True]
NOT_AN_ID: list[Any] = [0, -1, True]
NOT_AN_ID_NAMES: list[str] = ['zero', 'negative', 'true']


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='assessments', autouse=True)
def fixture_assessments(database_manager: MongoDatabaseManager, database_name: str):
    """Persons, two stored Risks and one stored assessment; everything the tests write purged"""
    collection = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    risks: tuple[int, ...] = (RISK_ID, SECOND_RISK_ID)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': {'$in': [NEW_RA_ID, STORED_RA_ID]}},
                                        {'risk_id': {'$in': SENT_RISK_IDS}}]})
        purge_referenced_persons(database_manager, database_name)
        purge_referenced_risks(database_manager, database_name, risks)

    _purge()
    seed_referenced_persons(database_manager, database_name)
    seed_referenced_risks(database_manager, database_name, risks)
    collection.insert_one(_ra_body(STORED_RA_ID))
    yield collection
    _purge()


def _body(**overrides: Any) -> dict[str, Any]:
    """A complete body"""
    return _ra_body(NEW_RA_ID, **overrides)


def _written(assessments: Any) -> int:
    """How many assessments the tests wrote: every one but the stored one"""
    return assessments.count_documents({'public_id': {'$ne': STORED_RA_ID}, 'risk_id': {'$in': SENT_RISK_IDS}})


def _refused_risks(response: Any, unknown: list[int]) -> None:
    """The unknown-Risk 400"""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()[MESSAGE_KEY] == UNKNOWN_RISKS_MSG.format(unknown=unknown)


class TestCreate:
    """POST /isms/risk_assessments/"""

    @pytest.mark.parametrize('risk_id', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_a_risk_id_that_is_no_id_is_a_400(self, rest_api, assessments, risk_id: Any) -> None:
        """Each used to be stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(risk_id=risk_id))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'risk_id' in response.get_json()[MESSAGE_KEY]
        assert _written(assessments) == 0

    def test_a_risk_that_is_not_stored_is_a_400(self, rest_api, assessments) -> None:
        """Named in the message"""
        _refused_risks(rest_api.post(f'{ROUTE_URL}/', json=_body(risk_id=MISSING_RISK_ID)), [MISSING_RISK_ID])
        assert _written(assessments) == 0

    @pytest.mark.parametrize('overrides', [{'object_id': True}, {'interviewed_persons': [True]}],
                             ids=['object-true', 'interviewed-true'])
    def test_a_boolean_id_elsewhere_is_a_400(self, rest_api, assessments, overrides: dict[str, Any]) -> None:
        """The same rule for every id"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_body(**overrides)).status_code == HTTPStatus.BAD_REQUEST
        assert _written(assessments) == 0

    def test_a_stored_risk_passes(self, rest_api, assessments) -> None:
        """The control"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_body()).status_code == HTTPStatus.CREATED
        assert _written(assessments) == 1

    def test_a_failed_risk_read_is_its_own_400(self, rest_api, assessments, monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('risks unreadable')

        monkeypatch.setattr(BaseManager, 'get_many_from_other_collection', _failing)

        response = rest_api.post(f'{ROUTE_URL}/', json=_body())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == manager_error_message(
            RISK_ASSESSMENT_LABEL, IsmsManagerErrorMessage.RISK_READ,
        )
        assert _written(assessments) == 0


class TestUpdate:
    """PUT /isms/risk_assessments/<id>"""

    def test_moving_onto_a_missing_risk_is_a_400(self, rest_api, assessments) -> None:
        """The stored assessment keeps its Risk"""
        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_ra_body(STORED_RA_ID, risk_id=MISSING_RISK_ID))

        _refused_risks(response, [MISSING_RISK_ID])
        assert assessments.find_one({'public_id': STORED_RA_ID})['risk_id'] == RISK_ID

    @pytest.mark.parametrize('risk_id', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_a_risk_id_that_is_no_id_is_a_400(self, rest_api, assessments, risk_id: Any) -> None:
        """Nothing changes"""
        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_ra_body(STORED_RA_ID, risk_id=risk_id))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert assessments.find_one({'public_id': STORED_RA_ID})['risk_id'] == RISK_ID

    def test_moving_onto_another_stored_risk_passes(self, rest_api, assessments) -> None:
        """The control"""
        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_ra_body(STORED_RA_ID, risk_id=SECOND_RISK_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert assessments.find_one({'public_id': STORED_RA_ID})['risk_id'] == SECOND_RISK_ID


class TestDuplicate:
    """POST /isms/risk_assessments/duplicate/<mode>/<ids>"""

    def test_a_risk_mode_target_without_a_risk_writes_no_copy(self, rest_api, assessments) -> None:
        """All targets are judged before the first copy"""
        targets: str = f'{SECOND_RISK_ID},{MISSING_RISK_ID}'

        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{targets}?copy_cma=false',
                                 json=_ra_body(STORED_RA_ID))

        _refused_risks(response, [MISSING_RISK_ID])
        assert _written(assessments) == 0

    def test_risk_mode_targets_that_are_stored_pass(self, rest_api, assessments) -> None:
        """The control - one copy per target"""
        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{SECOND_RISK_ID}?copy_cma=false',
                                 json=_ra_body(STORED_RA_ID))

        assert response.status_code == HTTPStatus.OK
        assert _written(assessments) == 1

    def test_an_object_mode_copy_of_a_missing_risk_is_a_400(self, rest_api, assessments) -> None:
        """The copies carry the payload's own Risk"""
        response = rest_api.post(
            f'{ROUTE_URL}/duplicate/object_group/{STORED_RA_ID + 1}?copy_cma=false',
            json=_ra_body(STORED_RA_ID, risk_id=MISSING_RISK_ID),
        )

        _refused_risks(response, [MISSING_RISK_ID])
        assert _written(assessments) == 0
