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
Functional census of the messages the ISMS routes answer when a manager fails

The per-entity route suites pin the STATUS of every manager-error mapping; this suite pins the TEXT.
Every ``IsmsManagerErrorMessage`` template is reached through at least one real request, and the two
templates that need no payload (``GET``, ``ITERATE``) through every entity, so a route whose table
names the wrong template - or the wrong entity's label - fails here. Each expected message is built
from the template the route is REQUIRED to use, not read back from the route, and every seeded id is
distinct, so a swapped template or a mis-filled ``{public_id}`` changes the text being compared.

The report routes are covered too: a failure to read the data a report is built from is a 400 with
the report's own ``IsmsReportErrorMessage``, anything else stays the generic 500.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.isms import RiskMatrixReportBuilder
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.manager.isms_manager.vulnerability_manager import VulnerabilityManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsThreat
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes import isms_report_routes
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import IsmsReportErrorMessage
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_ASSIGNMENT_LABEL,
    CONTROL_MEASURE_LABEL,
    IMPACT_CATEGORY_LABEL,
    IMPACT_LABEL,
    LIKELIHOOD_LABEL,
    PROTECTION_GOAL_LABEL,
    RISK_ASSESSMENT_LABEL,
    RISK_CLASS_LABEL,
    RISK_LABEL,
    RISK_MATRIX_LABEL,
    THREAT_LABEL,
    VULNERABILITY_LABEL,
    IsmsEntityLabel,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
from cmdb.errors.framework_isms import RiskMatrixReportError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerIterationError
from cmdb.errors.manager.control_measure_assignment_manager import (
    ControlMeasureAssignmentManagerGetError,
    ControlMeasureAssignmentManagerIterationError,
)
from cmdb.errors.manager.control_measure_manager import (
    ControlMeasureManagerGetError,
    ControlMeasureManagerIterationError,
)
from cmdb.errors.manager.impact_category_manager import (
    ImpactCategoryManagerGetError,
    ImpactCategoryManagerIterationError,
)
from cmdb.errors.manager.impact_manager import ImpactManagerGetError, ImpactManagerIterationError
from cmdb.errors.manager.likelihood_manager import LikelihoodManagerGetError, LikelihoodManagerIterationError
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerGetError,
    ProtectionGoalManagerIterationError,
)
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerGetError
from cmdb.errors.manager.risk_class_manager import RiskClassManagerGetError, RiskClassManagerIterationError
from cmdb.errors.manager.risk_manager import RiskManagerGetError, RiskManagerIterationError
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerGetError
from cmdb.errors.manager.threat_manager import (
    ThreatManagerDeleteError,
    ThreatManagerGetError,
    ThreatManagerInsertError,
    ThreatManagerIterationError,
    ThreatManagerRiskUsageError,
    ThreatManagerUpdateError,
)
from cmdb.errors.manager.vulnerability_manager import (
    VulnerabilityManagerGetError,
    VulnerabilityManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_PREFIX: str = '/isms'
REPORTS_URL: str = f'{ISMS_PREFIX}/reports'
THREATS_URL: str = f'{ISMS_PREFIX}/threats'

# Distinct per request, so a template filled with the wrong argument - or none - reads differently
SINGLE_GET_ID: int = 97801
STORED_THREAT_ID: int = 97802
BULK_THREAT_ID: int = 97803

THREAT_NAME: str = 'Error-message Threat'

MESSAGE_KEY: str = 'message'


# (route path under /isms, manager, its get error, its iteration error or None, the entity's labels)
ENTITIES: list[tuple[str, type, type[Exception], type[Exception] | None, IsmsEntityLabel]] = [
    ('control_measures', ControlMeasureManager, ControlMeasureManagerGetError,
     ControlMeasureManagerIterationError, CONTROL_MEASURE_LABEL),
    ('control_measure_assignments', ControlMeasureAssignmentManager, ControlMeasureAssignmentManagerGetError,
     ControlMeasureAssignmentManagerIterationError, CONTROL_MEASURE_ASSIGNMENT_LABEL),
    ('impact_categories', ImpactCategoryManager, ImpactCategoryManagerGetError,
     ImpactCategoryManagerIterationError, IMPACT_CATEGORY_LABEL),
    ('impacts', ImpactManager, ImpactManagerGetError, ImpactManagerIterationError, IMPACT_LABEL),
    ('likelihoods', LikelihoodManager, LikelihoodManagerGetError, LikelihoodManagerIterationError, LIKELIHOOD_LABEL),
    ('protection_goals', ProtectionGoalManager, ProtectionGoalManagerGetError,
     ProtectionGoalManagerIterationError, PROTECTION_GOAL_LABEL),
    ('risk_assessments', RiskAssessmentManager, RiskAssessmentManagerGetError, None, RISK_ASSESSMENT_LABEL),
    ('risk_classes', RiskClassManager, RiskClassManagerGetError, RiskClassManagerIterationError, RISK_CLASS_LABEL),
    ('risks', RiskManager, RiskManagerGetError, RiskManagerIterationError, RISK_LABEL),
    ('risk_matrix', RiskMatrixManager, RiskMatrixManagerGetError, None, RISK_MATRIX_LABEL),
    ('threats', ThreatManager, ThreatManagerGetError, ThreatManagerIterationError, THREAT_LABEL),
    ('vulnerabilities', VulnerabilityManager, VulnerabilityManagerGetError,
     VulnerabilityManagerIterationError, VULNERABILITY_LABEL),
]

LISTED_ENTITIES = [entity for entity in ENTITIES if entity[3] is not None]


def _raiser(exc: Exception):
    """Builds a stand-in for a manager method that always raises ``exc``."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _expected(label: IsmsEntityLabel, template: IsmsManagerErrorMessage, public_id: int | None = None) -> str:
    """The message a route must answer: the template it is required to use, filled for the request."""
    message: str = manager_error_message(label, template)

    return message.format(public_id=public_id) if public_id is not None else message


def _threat_payload() -> dict[str, Any]:
    """An IsmsThreat body the write schema accepts."""
    return {'name': THREAT_NAME}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture
def stored_threat(database_manager: MongoDatabaseManager, database_name: str):
    """One stored IsmsThreat, so the update and delete routes get past their existence check."""
    collection = database_manager.get_collection(IsmsThreat.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': [STORED_THREAT_ID, BULK_THREAT_ID]}})
    collection.insert_one({'public_id': STORED_THREAT_ID, 'name': THREAT_NAME})
    yield STORED_THREAT_ID
    collection.delete_many({'public_id': {'$in': [STORED_THREAT_ID, BULK_THREAT_ID]}})


class TestEveryEntityNamesItself:
    """The two payload-free templates, through every entity: a label copied from a sibling shows here."""

    @pytest.mark.parametrize('path, manager, get_error, _iteration_error, label', ENTITIES,
                             ids=[entity[0] for entity in ENTITIES])
    def test_a_failed_read_names_the_entity_and_the_id(self, rest_api, monkeypatch, path: str, manager: type,
                                                       get_error: type[Exception], _iteration_error: Any,
                                                       label: IsmsEntityLabel) -> None:
        """GET: the entity's singular label and the requested id."""
        monkeypatch.setattr(manager, 'get_item', _raiser(get_error('boom')))

        response = rest_api.get(f'{ISMS_PREFIX}/{path}/{SINGLE_GET_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(label, IsmsManagerErrorMessage.GET, SINGLE_GET_ID)

    @pytest.mark.parametrize('path, manager, _get_error, iteration_error, label', LISTED_ENTITIES,
                             ids=[entity[0] for entity in LISTED_ENTITIES])
    def test_a_failed_list_names_the_entities(self, rest_api, monkeypatch, path: str, manager: type,
                                              _get_error: Any, iteration_error: type[Exception],
                                              label: IsmsEntityLabel) -> None:
        """ITERATE: the entity's plural label."""
        monkeypatch.setattr(manager, 'iterate_items', _raiser(iteration_error('boom')))

        response = rest_api.get(f'{ISMS_PREFIX}/{path}/')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(label, IsmsManagerErrorMessage.ITERATE)

    @pytest.mark.parametrize('path, manager, _get_error, _iteration_error, _label', LISTED_ENTITIES,
                             ids=[entity[0] for entity in LISTED_ENTITIES])
    def test_any_other_list_failure_stays_a_500(self, rest_api, monkeypatch, path: str, manager: type,
                                                _get_error: Any, _iteration_error: Any, _label: Any) -> None:
        """An error the table does not name reaches the generic tail, not the 400."""
        monkeypatch.setattr(manager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ISMS_PREFIX}/{path}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestEveryTemplateIsReached:
    """The remaining templates, through the Threat routes - the one entity that uses all of them."""

    def test_insert(self, rest_api, monkeypatch) -> None:
        """INSERT: the write itself failed."""
        monkeypatch.setattr(ThreatManager, 'insert_item', _raiser(ThreatManagerInsertError('boom')))

        response = rest_api.post(f'{THREATS_URL}/', json=_threat_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(THREAT_LABEL, IsmsManagerErrorMessage.INSERT)

    def test_get_created(self, rest_api, monkeypatch) -> None:
        """GET_CREATED: the write went through, reading it back failed."""
        monkeypatch.setattr(ThreatManager, 'insert_item', lambda *_a, **_k: SINGLE_GET_ID)
        monkeypatch.setattr(ThreatManager, 'get_item', _raiser(ThreatManagerGetError('boom')))

        response = rest_api.post(f'{THREATS_URL}/', json=_threat_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(THREAT_LABEL, IsmsManagerErrorMessage.GET_CREATED)

    def test_update(self, rest_api, monkeypatch, stored_threat: int) -> None:
        """UPDATE: the stored Threat was found, writing the change failed."""
        monkeypatch.setattr(ThreatManager, 'update_item', _raiser(ThreatManagerUpdateError('boom')))

        response = rest_api.put(f'{THREATS_URL}/{stored_threat}', json=_threat_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(
            THREAT_LABEL, IsmsManagerErrorMessage.UPDATE, stored_threat,
        )

    def test_delete(self, rest_api, monkeypatch, stored_threat: int) -> None:
        """DELETE: the stored Threat was found, removing it failed."""
        monkeypatch.setattr(ThreatManager, 'delete_with_follow_up', _raiser(ThreatManagerDeleteError('boom')))

        response = rest_api.delete(f'{THREATS_URL}/{stored_threat}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(
            THREAT_LABEL, IsmsManagerErrorMessage.DELETE, stored_threat,
        )

    def test_used_by_risks(self, rest_api, monkeypatch, stored_threat: int) -> None:
        """USED_BY_RISKS: a refusal, not a failure - same 400, its own message."""
        monkeypatch.setattr(ThreatManager, 'delete_with_follow_up', _raiser(ThreatManagerRiskUsageError('used')))

        response = rest_api.delete(f'{THREATS_URL}/{stored_threat}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(
            THREAT_LABEL, IsmsManagerErrorMessage.USED_BY_RISKS, stored_threat,
        )

    def test_bulk_usage(self, rest_api, monkeypatch) -> None:
        """BULK_USAGE: the grouped in-use check failed before anything was deleted."""
        monkeypatch.setattr(ThreatManager, 'get_used_threat_ids', _raiser(ThreatManagerGetError('boom')))

        response = rest_api.delete(f'{THREATS_URL}/delete/{BULK_THREAT_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(THREAT_LABEL, IsmsManagerErrorMessage.BULK_USAGE)

    def test_bulk_delete(self, rest_api, monkeypatch) -> None:
        """BULK_DELETE: one of the unused Threats could not be deleted."""
        monkeypatch.setattr(ThreatManager, 'get_used_threat_ids', lambda *_a, **_k: set())
        monkeypatch.setattr(ThreatManager, 'delete_item', _raiser(ThreatManagerDeleteError('boom')))

        response = rest_api.delete(f'{THREATS_URL}/delete/{BULK_THREAT_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == _expected(THREAT_LABEL, IsmsManagerErrorMessage.BULK_DELETE)


class TestReportReadFailures:
    """A report whose data cannot be read is a 400 with the report's own message."""

    @pytest.mark.parametrize('error', [
        BaseManagerIterationError('aggregation failed'),
        RiskAssessmentManagerIterationError('iteration failed'),
    ], ids=['base-iteration', 'risk-assessment-iteration'])
    def test_risk_treatment_plan_aggregation(self, rest_api, monkeypatch, error: Exception) -> None:
        """Both iteration errors the aggregation can surface answer the same 400."""
        monkeypatch.setattr(RiskAssessmentManager, 'aggregate_within_time_limit', _raiser(error))

        response = rest_api.get(f'{REPORTS_URL}/risk_treatment_plan')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == IsmsReportErrorMessage.RISK_TREATMENT_PLAN.value

    @pytest.mark.parametrize('report, message', [
        ('risk_treatment_plan', IsmsReportErrorMessage.RISK_TREATMENT_PLAN),
        ('risk_assessments', IsmsReportErrorMessage.RISK_ASSESSMENTS),
    ])
    def test_object_summaries(self, rest_api, monkeypatch, report: str, message: IsmsReportErrorMessage) -> None:
        """The batched object summary lookup is a read of the report's data too."""
        monkeypatch.setattr(RiskAssessmentManager, 'aggregate_within_time_limit', lambda *_a, **_k: [])
        monkeypatch.setattr(isms_report_routes, 'extract_report_page', lambda _rows: ([{}], 1))
        monkeypatch.setattr(isms_report_routes, 'resolve_assessed_objects',
                            _raiser(ObjectsManagerGetError('boom')))

        response = rest_api.get(f'{REPORTS_URL}/{report}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == message.value

    def test_risk_assessments_aggregation(self, rest_api, monkeypatch) -> None:
        """The RiskAssessment report reads through the same aggregation."""
        monkeypatch.setattr(
            RiskAssessmentManager, 'aggregate_within_time_limit', _raiser(BaseManagerIterationError('boom')),
        )

        response = rest_api.get(f'{REPORTS_URL}/risk_assessments')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == IsmsReportErrorMessage.RISK_ASSESSMENTS.value

    def test_soa_control_measures(self, rest_api, monkeypatch) -> None:
        """The SOA reads the whole ControlMeasure set with get_many."""
        monkeypatch.setattr(ControlMeasureManager, 'get_many', _raiser(BaseManagerGetError('boom')))

        response = rest_api.get(f'{REPORTS_URL}/soa')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == IsmsReportErrorMessage.SOA.value

    def test_risk_matrix_build(self, rest_api, monkeypatch) -> None:
        """The RiskMatrix report's builder refuses the stored configuration."""
        monkeypatch.setattr(RiskMatrixReportBuilder, 'build_risk_matrix_report',
                            _raiser(RiskMatrixReportError('boom')))

        response = rest_api.get(f'{REPORTS_URL}/risk_matrix')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == IsmsReportErrorMessage.RISK_MATRIX.value
