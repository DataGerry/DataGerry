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
Functional smoke for the ``/isms/control_measure_assignments`` REST routes

Covers CRUD, the manager-error -> 400 mapping, and the enriched GET-list route which joins each
assignment's RiskAssessment -> Risk + ObjectGroup into a ``naming.cma_summary``. The routes are
ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsRiskAssessment, IsmsRisk
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.control_measure_assignment_manager import (
    ControlMeasureAssignmentManagerInsertError,
    ControlMeasureAssignmentManagerGetError,
    ControlMeasureAssignmentManagerUpdateError,
    ControlMeasureAssignmentManagerDeleteError,
    ControlMeasureAssignmentManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/control_measure_assignments'

CMA_ID_FOR_GET: int = 98401
CMA_ID_FOR_UPDATE: int = 98402
CMA_ID_FOR_DELETE: int = 98403
CMA_ID_FOR_ENRICH: int = 98404
MISSING_CMA_ID: int = 98499

RISK_ASSESSMENT_ID: int = 98450
RISK_ID: int = 98451
OBJECT_GROUP_ID: int = 98452
CONTROL_MEASURE_ID: int = 98460
MISSING_CONTROL_MEASURE_ID: int = 98461

RISK_NAME: str = 'Enrichment Risk'
OBJECT_GROUP_NAME: str = 'Enrichment Group'

ALL_CMA_IDS: list[int] = [CMA_ID_FOR_GET, CMA_ID_FOR_UPDATE, CMA_ID_FOR_DELETE, CMA_ID_FOR_ENRICH]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]
ALL_RISK_IDS: list[int] = [RISK_ID]
ALL_OBJECT_GROUP_IDS: list[int] = [OBJECT_GROUP_ID]
ALL_CONTROL_MEASURE_IDS: list[int] = [CONTROL_MEASURE_ID]


def _cma_payload(public_id: int, risk_assessment_id: int = RISK_ASSESSMENT_ID) -> dict[str, Any]:
    """Builds a valid IsmsControlMeasureAssignment body (all schema-required fields present)."""
    return {
        'public_id': public_id,
        'control_measure_id': CONTROL_MEASURE_ID,
        'risk_assessment_id': risk_assessment_id,
        'planned_implementation_date': None,
        'implementation_status': 1,
        'finished_implementation_date': None,
        'priority': 1,
        'responsible_for_implementation_id_ref_type': 'PERSON',
        'responsible_for_implementation_id': 1,
    }


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/control_measure_assignments routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any assignments / assessments / risks / object groups seeded by a test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CMA_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_OBJECT_GROUP_IDS}})
        database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_MEASURE_IDS}})

    _purge()
    # Seed the ControlMeasure referenced by _cma_payload so the reference check passes
    database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name).insert_one(
        {'public_id': CONTROL_MEASURE_ID, 'title': 'Seeded Control', 'control_measure_type': 'CONTROL'}
    )
    yield
    _purge()


def _insert_cma(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts an IsmsControlMeasureAssignment doc directly via the collection."""
    database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
        .insert_one(_cma_payload(public_id))


class TestPostControlMeasureAssignment:
    """POST /isms/control_measure_assignments/ creates an assignment."""

    def test_creates_assignment(self, rest_api) -> None:
        """A POST with a valid body succeeds and the assignment becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_cma_payload(CMA_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_required_field_returns_400(self, rest_api) -> None:
        """A POST missing a required field fails schema validation with 400."""
        payload = _cma_payload(CMA_ID_FOR_GET)
        payload.pop('control_measure_id')

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_control_measure_returns_400(self, rest_api) -> None:
        """A POST referencing a non-existent control_measure_id is rejected with 400."""
        payload = _cma_payload(CMA_ID_FOR_GET)
        payload['control_measure_id'] = MISSING_CONTROL_MEASURE_ID

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST


class TestGetControlMeasureAssignment:
    """GET single + the enriched GET-list."""

    def test_get_single_returns_assignment(self, rest_api,
                                           database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching assignment."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{CMA_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == CMA_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_CMA_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_list_enriches_with_cma_summary(self, rest_api,
                                           database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The list route joins RiskAssessment -> Risk + ObjectGroup into naming.cma_summary."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_ENRICH)
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_id': RISK_ID,
            'object_id_ref_type': ObjectReferenceType.OBJECT_GROUP,
            'object_id': OBJECT_GROUP_ID,
        })
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .insert_one({'public_id': RISK_ID, 'name': RISK_NAME})
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .insert_one({'public_id': OBJECT_GROUP_ID, 'name': OBJECT_GROUP_NAME})

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        enriched = next(item for item in response.get_json()['results'] if item['public_id'] == CMA_ID_FOR_ENRICH)
        expected = f"#{RISK_ASSESSMENT_ID} - {RISK_NAME} @ {OBJECT_GROUP_NAME}"
        assert enriched['naming']['cma_summary'] == expected


class TestPutControlMeasureAssignment:
    """PUT /isms/control_measure_assignments/<id> updates a single assignment."""

    def test_update_persists_priority(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated priority."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_UPDATE)
        payload = _cma_payload(CMA_ID_FOR_UPDATE)
        payload['priority'] = 3

        response = rest_api.put(f'{ROUTE_URL}/{CMA_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CMA_ID_FOR_UPDATE}').get_json()['result']['priority'] == 3

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent assignment returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_CMA_ID}',
                            json=_cma_payload(MISSING_CMA_ID)).status_code == HTTPStatus.NOT_FOUND


class TestDeleteControlMeasureAssignment:
    """DELETE /isms/control_measure_assignments/<id> removes an assignment."""

    def test_delete_removes_assignment(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{CMA_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CMA_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent assignment returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CMA_ID}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureAssignmentManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_item',
                            _raiser(ControlMeasureAssignmentManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_cma_payload(CMA_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureAssignmentManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'iterate_items',
                            _raiser(ControlMeasureAssignmentManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureAssignmentManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'get_item',
                            _raiser(ControlMeasureAssignmentManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{CMA_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ControlMeasureAssignmentManagerUpdateError (assignment found) surfaces as 400."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_UPDATE)
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'update_item',
                            _raiser(ControlMeasureAssignmentManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{CMA_ID_FOR_UPDATE}', json=_cma_payload(CMA_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ControlMeasureAssignmentManagerDeleteError (assignment found) surfaces as 400."""
        _insert_cma(database_manager, database_name, CMA_ID_FOR_DELETE)
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'delete_item',
                            _raiser(ControlMeasureAssignmentManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CMA_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
