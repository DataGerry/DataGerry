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
Functional smoke for the ``/isms/risk_assessments`` REST routes

Covers CRUD, the ``/duplicate`` route, the enriched GET-list, the delete cascade, error -> 400
mapping, and two regression guards from the audit: omitting ``control_measure_assignments`` must not
500 (insert AND update), and a null ``costs_for_implementation`` is accepted (it is nullable). The
routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment, IsmsRisk, IsmsImpact
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.risk_assessment_manager import (
    RiskAssessmentManagerInsertError,
    RiskAssessmentManagerGetError,
    RiskAssessmentManagerUpdateError,
    RiskAssessmentManagerDeleteError,
    RiskAssessmentManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'

RA_ID_FOR_GET: int = 99201
RA_ID_FOR_UPDATE: int = 99202
RA_ID_FOR_DELETE: int = 99203
RA_ID_FOR_CASCADE: int = 99204
RA_ID_FOR_ENRICH: int = 99205
RA_ID_FOR_DUPLICATE: int = 99206
OTHER_RA_ID: int = 99207
MISSING_RA_ID: int = 99299

CMA_ID_FOR_CASCADE: int = 99250
CMA_ID_TO_CREATE: int = 99251
CMA_ID_TO_DELETE: int = 99252
CMA_ID_FOREIGN: int = 99253
CMA_ID_CREATE_NO_ID: int = 99254
RISK_ID: int = 99260
OBJECT_GROUP_ID: int = 99270
IMPACT_LOW_ID: int = 99280
IMPACT_HIGH_ID: int = 99281
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
MISSING_CONTROL_MEASURE_ID: int = 99290

RISK_NAME: str = 'Enrichment Risk'
OBJECT_GROUP_NAME: str = 'Enrichment Group'

ALL_RA_IDS: list[int] = [
    RA_ID_FOR_GET, RA_ID_FOR_UPDATE, RA_ID_FOR_DELETE, RA_ID_FOR_CASCADE, RA_ID_FOR_ENRICH, RA_ID_FOR_DUPLICATE,
    OTHER_RA_ID,
]
ALL_CMA_IDS: list[int] = [
    CMA_ID_FOR_CASCADE, CMA_ID_TO_CREATE, CMA_ID_TO_DELETE, CMA_ID_FOREIGN, CMA_ID_CREATE_NO_ID,
]
ALL_RISK_IDS: list[int] = [RISK_ID]
ALL_OBJECT_GROUP_IDS: list[int] = [OBJECT_GROUP_ID]
ALL_IMPACT_IDS: list[int] = [IMPACT_LOW_ID, IMPACT_HIGH_ID]

OBJECT_GROUP_REF: str = ObjectReferenceType.OBJECT_GROUP
PERSON_REF: str = PersonReferenceType.PERSON


def _ra_body(public_id: int, **overrides: Any) -> dict[str, Any]:
    """Builds a schema-valid IsmsRiskAssessment body (all 26 required fields; nullable ones as None)."""
    body: dict[str, Any] = {
        'public_id': public_id,
        'risk_id': RISK_ID,
        'object_id_ref_type': OBJECT_GROUP_REF,
        'object_id': OBJECT_GROUP_ID,
        'risk_calculation_before': {
            'impacts': [], 'likelihood_id': 0, 'likelihood_value': 0.0,
            'maximum_impact_id': 0, 'maximum_impact_value': 0.0,
        },
        'risk_assessor_id': None,
        'risk_owner_id_ref_type': PERSON_REF,
        'risk_owner_id': None,
        'interviewed_persons': [],
        'risk_assessment_date': {'$date': 1600000000000},
        'additional_info': None,
        'risk_treatment_option': None,
        'responsible_persons_id_ref_type': PERSON_REF,
        'responsible_persons_id': None,
        'risk_treatment_description': None,
        'planned_implementation_date': None,
        'implementation_status': None,
        'finished_implementation_date': None,
        'required_resources': None,
        'costs_for_implementation': 0.0,
        'costs_for_implementation_currency': None,
        'priority': None,
        'risk_calculation_after': {
            'likelihood_id': 0, 'likelihood_value': 0.0, 'maximum_impact_id': 0, 'maximum_impact_value': 0.0,
        },
        'audit_done_date': None,
        'auditor_id_ref_type': PERSON_REF,
        'auditor_id': None,
        'audit_result': None,
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/risk_assessments routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any assessments / assignments / risks / object groups seeded by a test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RA_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CMA_IDS}})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_OBJECT_GROUP_IDS}})
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_IMPACT_IDS}})

    _purge()
    yield
    _purge()


def _insert_ra(database_manager: MongoDatabaseManager, database_name: str, public_id: int, **overrides: Any) -> None:
    """Inserts an IsmsRiskAssessment doc directly via the collection."""
    database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .insert_one(_ra_body(public_id, **overrides))


class TestPostRiskAssessment:
    """POST /isms/risk_assessments/ creates an assessment (and its regression guards)."""

    def test_creates_without_control_measure_assignments(self, rest_api) -> None:
        """Omitting control_measure_assignments must succeed, not 500 (insert regression)."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_ra_body(RA_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_null_costs_is_accepted(self, rest_api) -> None:
        """A null costs_for_implementation is accepted (the field is nullable)."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_ra_body(RA_ID_FOR_GET, costs_for_implementation=None))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_missing_required_field_returns_400(self, rest_api) -> None:
        """A POST missing a required field fails schema validation with 400."""
        payload = _ra_body(RA_ID_FOR_GET)
        payload.pop('risk_id')

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_object_ref_type_returns_400(self, rest_api) -> None:
        """An object_id_ref_type outside the ObjectReferenceType enum is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json=_ra_body(RA_ID_FOR_GET, object_id_ref_type='BOGUS'))\
            .status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_person_ref_type_returns_400(self, rest_api) -> None:
        """A person ref_type outside the PersonReferenceType enum is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json=_ra_body(RA_ID_FOR_GET, risk_owner_id_ref_type='NOBODY'))\
            .status_code == HTTPStatus.BAD_REQUEST

    def test_insert_rejects_unknown_control_measure(self, rest_api) -> None:
        """A control_measure_assignment referencing a non-existent ControlMeasure is rejected with 400."""
        payload = _ra_body(RA_ID_FOR_GET, control_measure_assignments=[
            {'public_id': CMA_ID_TO_CREATE, 'control_measure_id': MISSING_CONTROL_MEASURE_ID},
        ])

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_recompute_overwrites_client_maximum_impact(self, rest_api,
                                                       database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """maximum_impact is derived server-side from the impacts, ignoring the client-sent values."""
        impact_collection = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
        impact_collection.insert_one({'public_id': IMPACT_LOW_ID, 'name': 'Low', 'calculation_basis': BASIS_LOW})
        impact_collection.insert_one({'public_id': IMPACT_HIGH_ID, 'name': 'High', 'calculation_basis': BASIS_HIGH})

        payload = _ra_body(RA_ID_FOR_GET, risk_calculation_before={
            'impacts': [
                {'impact_category_id': 1, 'impact_id': IMPACT_LOW_ID},
                {'impact_category_id': 2, 'impact_id': IMPACT_HIGH_ID},
            ],
            'likelihood_id': None, 'likelihood_value': 0.0,
            'maximum_impact_id': 999999, 'maximum_impact_value': 999.0,
        })

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        stored = rest_api.get(f'{ROUTE_URL}/{created_id}').get_json()['result']['risk_calculation_before']
        assert stored['maximum_impact_id'] == IMPACT_HIGH_ID
        assert stored['maximum_impact_value'] == BASIS_HIGH


class TestGetRiskAssessment:
    """GET single + the enriched GET-list."""

    def test_get_single_returns_assessment(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching assessment."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{RA_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == RA_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_RA_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_list_enriches_naming(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The list route resolves risk name + object group name into the naming block."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_ENRICH)
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .insert_one({'public_id': RISK_ID, 'name': RISK_NAME})
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .insert_one({'public_id': OBJECT_GROUP_ID, 'name': OBJECT_GROUP_NAME})

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        enriched = next(item for item in response.get_json()['results'] if item['public_id'] == RA_ID_FOR_ENRICH)
        assert enriched['naming']['risk_id_name'] == RISK_NAME
        assert enriched['naming']['object_group_id_name'] == OBJECT_GROUP_NAME


class TestPutRiskAssessment:
    """PUT /isms/risk_assessments/<id> updates an assessment."""

    def test_update_without_control_measure_assignments(self, rest_api,
                                                       database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """Omitting control_measure_assignments must succeed, not 500 (the HIGH update regression)."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=_ra_body(RA_ID_FOR_UPDATE))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent assessment returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_RA_ID}',
                            json=_ra_body(MISSING_RA_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_update_applies_control_measure_assignment_changes(self, rest_api,
                                                             database_manager: MongoDatabaseManager,
                                                             database_name: str) -> None:
        """The created / deleted entries of control_measure_assignments are applied on update."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)
        cma_collection = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
        cma_collection.insert_one({'public_id': CMA_ID_TO_DELETE, 'risk_assessment_id': RA_ID_FOR_UPDATE})

        payload = _ra_body(RA_ID_FOR_UPDATE, control_measure_assignments={
            'created': [{'public_id': CMA_ID_TO_CREATE, 'risk_assessment_id': RA_ID_FOR_UPDATE}],
            'updated': [],
            'deleted': [CMA_ID_TO_DELETE],
        })

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert cma_collection.find_one({'public_id': CMA_ID_TO_CREATE}) is not None
        assert cma_collection.find_one({'public_id': CMA_ID_TO_DELETE}) is None

    def test_created_cma_without_id_is_linked_to_ra(self, rest_api,
                                                   database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """A created assignment carrying no risk_assessment_id is linked to the updated RiskAssessment."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)
        cma_collection = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

        payload = _ra_body(RA_ID_FOR_UPDATE, control_measure_assignments={
            'created': [{'public_id': CMA_ID_CREATE_NO_ID}],
            'updated': [],
            'deleted': [],
        })

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        created = cma_collection.find_one({'public_id': CMA_ID_CREATE_NO_ID})
        assert created is not None
        assert created['risk_assessment_id'] == RA_ID_FOR_UPDATE

    def test_update_rejects_deleting_foreign_cma(self, rest_api,
                                               database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Deleting an assignment linked to another RiskAssessment is rejected with 400 and preserved."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)
        cma_collection = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
        cma_collection.insert_one({'public_id': CMA_ID_FOREIGN, 'risk_assessment_id': OTHER_RA_ID})

        payload = _ra_body(RA_ID_FOR_UPDATE, control_measure_assignments={
            'created': [], 'updated': [], 'deleted': [CMA_ID_FOREIGN],
        })

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert cma_collection.find_one({'public_id': CMA_ID_FOREIGN}) is not None

    def test_update_rejects_updating_foreign_cma(self, rest_api,
                                               database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Updating an assignment linked to another RiskAssessment is rejected with 400."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)
        cma_collection = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
        cma_collection.insert_one({'public_id': CMA_ID_FOREIGN, 'risk_assessment_id': OTHER_RA_ID})

        payload = _ra_body(RA_ID_FOR_UPDATE, control_measure_assignments={
            'created': [],
            'updated': [{'public_id': CMA_ID_FOREIGN}],
            'deleted': [],
        })

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDuplicateRiskAssessment:
    """POST /isms/risk_assessments/duplicate/<mode>/<ids>."""

    def test_duplicate_risk_mode_creates_assessments(self, rest_api,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """Duplicating in 'risk' mode returns the created assessment ids."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_DUPLICATE)
        payload = _ra_body(RA_ID_FOR_DUPLICATE)

        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{RISK_ID}?copy_cma=false', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_ids = response.get_json()
        assert isinstance(created_ids, list) and len(created_ids) == 1
        # cleanup the duplicated assessment
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': created_ids}})

    def test_duplicate_invalid_mode_returns_400(self, rest_api) -> None:
        """An unknown duplication mode is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/duplicate/not_a_mode/{RISK_ID}',
                             json=_ra_body(RA_ID_FOR_DUPLICATE)).status_code == HTTPStatus.BAD_REQUEST


class TestDeleteRiskAssessment:
    """DELETE /isms/risk_assessments/<id> removes the assessment and cascades to assignments."""

    def test_delete_removes_assessment(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{RA_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RA_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent assessment returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_RA_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_cascades_to_control_measure_assignments(self, rest_api,
                                                          database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """Deleting an assessment removes its linked ControlMeasureAssignments."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_CASCADE)
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .insert_one({'public_id': CMA_ID_FOR_CASCADE, 'risk_assessment_id': RA_ID_FOR_CASCADE})

        response = rest_api.delete(f'{ROUTE_URL}/{RA_ID_FOR_CASCADE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CMA_ID_FOR_CASCADE}) is None


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskAssessmentManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(RiskAssessmentManager, 'insert_item',
                            _raiser(RiskAssessmentManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_ra_body(RA_ID_FOR_GET)).status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskAssessmentManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(RiskAssessmentManager, 'iterate_items',
                            _raiser(RiskAssessmentManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskAssessmentManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(RiskAssessmentManager, 'get_item',
                            _raiser(RiskAssessmentManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RA_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskAssessmentManagerUpdateError (assessment found) surfaces as 400."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_UPDATE)
        monkeypatch.setattr(RiskAssessmentManager, 'update_item',
                            _raiser(RiskAssessmentManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID_FOR_UPDATE}', json=_ra_body(RA_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskAssessmentManagerDeleteError (assessment found) surfaces as 400."""
        _insert_ra(database_manager, database_name, RA_ID_FOR_DELETE)
        monkeypatch.setattr(RiskAssessmentManager, 'delete_with_follow_up',
                            _raiser(RiskAssessmentManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{RA_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
