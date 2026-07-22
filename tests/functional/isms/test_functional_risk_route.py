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
Functional smoke for the ``/isms/risks`` REST routes

Covers CRUD, the risk_type / required-field validation (invalid type and incomplete data -> 400),
the manager-error -> 400 mapping, and the DELETE cascade that removes the Risk's RiskAssessments and
their ControlMeasureAssignments. The routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment, IsmsControlMeasureAssignment, RiskType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.risk_manager import (
    RiskManagerInsertError,
    RiskManagerGetError,
    RiskManagerUpdateError,
    RiskManagerDeleteError,
    RiskManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risks'

RISK_ID_FOR_GET: int = 98101
RISK_ID_FOR_UPDATE: int = 98102
RISK_ID_FOR_DELETE: int = 98103
RISK_ID_FOR_CASCADE: int = 98104
MISSING_RISK_ID: int = 98199

CASCADE_RISK_ASSESSMENT_ID: int = 98150
CASCADE_CONTROL_ASSIGNMENT_ID: int = 98151

CATEGORY_ID: int = 1

ALL_RISK_IDS: list[int] = [RISK_ID_FOR_GET, RISK_ID_FOR_UPDATE, RISK_ID_FOR_DELETE, RISK_ID_FOR_CASCADE]
ALL_RISK_ASSESSMENT_IDS: list[int] = [CASCADE_RISK_ASSESSMENT_ID]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CASCADE_CONTROL_ASSIGNMENT_ID]


def _risk_payload(public_id: int, risk_type: str = RiskType.THREAT, name: str = 'Risk') -> dict[str, Any]:
    """Builds a valid IsmsRisk body for the given risk_type (with its required extra fields)."""
    payload: dict[str, Any] = {
        'public_id': public_id, 'name': name, 'risk_type': risk_type, 'category_id': CATEGORY_ID,
    }
    if risk_type == RiskType.THREAT_X_VULNERABILITY:
        payload['threats'] = [1]
        payload['vulnerabilities'] = [1]
    elif risk_type == RiskType.THREAT:
        payload['threats'] = [1]
    elif risk_type == RiskType.EVENT:
        payload['consequences'] = 'A consequence'
        payload['description'] = 'A description'

    return payload


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/risks routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any risks / assessments / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_risk(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a minimal IsmsRisk doc directly via the collection."""
    database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': 'Risk', 'risk_type': RiskType.THREAT, 'threats': [1]})


class TestPostRisk:
    """POST /isms/risks/ creates an IsmsRisk with its risk_type validation."""

    def test_creates_risk(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid THREAT body succeeds and the risk becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_payload(RISK_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_invalid_risk_type_returns_400(self, rest_api) -> None:
        """A POST with an unknown risk_type is rejected with 400."""
        payload = _risk_payload(RISK_ID_FOR_GET)
        payload['risk_type'] = 'NOT_A_RISK_TYPE'

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_incomplete_data_returns_400(self, rest_api) -> None:
        """A THREAT risk without the required threats field is rejected with 400."""
        payload = _risk_payload(RISK_ID_FOR_GET)
        payload.pop('threats')

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST


class TestGetRisk:
    """GET /isms/risks/<id> and GET /isms/risks/ return the expected envelopes."""

    def test_get_single_returns_risk(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching risk."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{RISK_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == RISK_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_RISK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/risks/ returns a results envelope whose length matches X-Total-Count."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutRisk:
    """PUT /isms/risks/<id> updates a single IsmsRisk."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{RISK_ID_FOR_UPDATE}',
                                json=_risk_payload(RISK_ID_FOR_UPDATE, name='Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RISK_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent risk returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_RISK_ID}',
                            json=_risk_payload(MISSING_RISK_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_update_invalid_risk_type_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Updating with an unknown risk_type is rejected with 400."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_UPDATE)
        payload = _risk_payload(RISK_ID_FOR_UPDATE)
        payload['risk_type'] = 'NOT_A_RISK_TYPE'

        assert rest_api.put(f'{ROUTE_URL}/{RISK_ID_FOR_UPDATE}', json=payload).status_code == HTTPStatus.BAD_REQUEST


class TestDeleteRisk:
    """DELETE /isms/risks/<id> removes the risk and cascades to its ISMS dependents."""

    def test_delete_removes_risk(self, rest_api,
                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{RISK_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RISK_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent risk returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_RISK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_cascades_to_assessments_and_assignments(self, rest_api,
                                                           database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """Deleting a risk removes its RiskAssessments and their ControlMeasureAssignments."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_CASCADE)
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .insert_one({'public_id': CASCADE_RISK_ASSESSMENT_ID, 'risk_id': RISK_ID_FOR_CASCADE})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .insert_one({'public_id': CASCADE_CONTROL_ASSIGNMENT_ID, 'risk_assessment_id': CASCADE_RISK_ASSESSMENT_ID})

        response = rest_api.delete(f'{ROUTE_URL}/{RISK_ID_FOR_CASCADE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .find_one({'public_id': CASCADE_RISK_ASSESSMENT_ID}) is None
        assert database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CASCADE_CONTROL_ASSIGNMENT_ID}) is None


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(RiskManager, 'insert_item', _raiser(RiskManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_payload(RISK_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(RiskManager, 'iterate_items', _raiser(RiskManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(RiskManager, 'get_item', _raiser(RiskManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RISK_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskManagerUpdateError (risk found, valid data) surfaces as 400."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_UPDATE)
        monkeypatch.setattr(RiskManager, 'update_item', _raiser(RiskManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{RISK_ID_FOR_UPDATE}', json=_risk_payload(RISK_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskManagerDeleteError (risk found) surfaces as 400."""
        _insert_risk(database_manager, database_name, RISK_ID_FOR_DELETE)
        monkeypatch.setattr(RiskManager, 'delete_with_follow_up', _raiser(RiskManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{RISK_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
