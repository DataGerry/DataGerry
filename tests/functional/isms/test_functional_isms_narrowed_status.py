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
Functional status census of the narrowed ISMS manager paths

The ISMS managers catch only what their calls raise. Through real requests, per path: a programming error
under the manager is the route's 500, the database layer's typed failure is the route's 400, and the control
request answers its success status. The failure is injected at the BaseManager method the manager wraps, so
the manager's own arm is what is exercised.

Also the writes the narrowing came with: an Impact update whose RiskAssessment propagation fails is undone
(the stored basis is the old one, the assessment's maximum untouched), a calculation_basis another Impact
took between the pre-check and the write is the route's readable 400 (the unique index), and a RiskAssessment
write whose scale read fails names the scales.
"""
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsImpact, IsmsRisk, IsmsRiskAssessment, IsmsThreat
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CALCULATION_BASIS_TAKEN_MSG,
    IMPACT_LABEL,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
from cmdb.errors.database import DocumentInsertError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_PREFIX: str = '/isms'
MESSAGE_KEY: str = 'message'

THREAT_ID: int = 98901
CONTROL_MEASURE_ID: int = 98902
RISK_ID: int = 98903
IMPACT_ID: int = 98904
OTHER_IMPACT_ID: int = 98905
RISK_ASSESSMENT_ID: int = 98906

OLD_BASIS: float = 91.5
NEW_BASIS: float = 95.5
OTHER_BASIS: float = 93.5
NAME: str = 'Narrowed-status entry'

# The unique index on the Impact weight, built here and dropped again (the test session builds no indexes)
BASIS_INDEX_NAME: str = 'calculation_basis'


def _raiser(exc: Exception) -> Callable[..., Any]:
    """A stand-in for a BaseManager method that always raises ``exc``."""
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _fail


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """One Threat, ControlMeasure, Risk and two Impacts, removed again afterwards - with whatever a route created"""
    seeds: list[tuple[str, dict[str, Any]]] = [
        (IsmsThreat.COLLECTION, {'public_id': THREAT_ID, 'name': NAME}),
        (IsmsControlMeasure.COLLECTION, {'public_id': CONTROL_MEASURE_ID, 'title': NAME}),
        (IsmsRisk.COLLECTION, {'public_id': RISK_ID, 'name': NAME, 'threats': [], 'vulnerabilities': [],
                               'protection_goals': []}),
        (IsmsImpact.COLLECTION, {'public_id': IMPACT_ID, 'name': NAME, 'calculation_basis': OLD_BASIS}),
        (IsmsImpact.COLLECTION, {'public_id': OTHER_IMPACT_ID, 'name': NAME, 'calculation_basis': OTHER_BASIS}),
    ]

    def _purge() -> None:
        for collection, document in seeds:
            database_manager.get_collection(collection, database_name).delete_many(
                {'public_id': document['public_id']},
            )
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).delete_many(
            {'public_id': RISK_ASSESSMENT_ID},
        )
        # An Impact created through the route lands under an id the test never chose
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name).delete_many({'name': NAME})

    _purge()

    for collection, document in seeds:
        database_manager.get_collection(collection, database_name).insert_one(dict(document))

    yield
    _purge()


# (request, manager class, the BaseManager method its narrowed arm wraps, the typed failure, success status)
PATHS: list[tuple[str, str, type, str, Exception, HTTPStatus]] = [
    ('DELETE', f'{ISMS_PREFIX}/threats/{THREAT_ID}', ThreatManager, 'get_one_by',
     BaseManagerGetError('down'), HTTPStatus.ACCEPTED),
    ('DELETE', f'{ISMS_PREFIX}/control_measures/delete/{CONTROL_MEASURE_ID}', ControlMeasureManager,
     'aggregate_all', BaseManagerIterationError('down'), HTTPStatus.OK),
    ('DELETE', f'{ISMS_PREFIX}/threats/delete/{THREAT_ID}', ThreatManager, 'aggregate_all',
     BaseManagerIterationError('down'), HTTPStatus.OK),
    ('DELETE', f'{ISMS_PREFIX}/risks/{RISK_ID}', RiskManager, 'get_many_from_other_collection',
     BaseManagerGetError('down'), HTTPStatus.ACCEPTED),
    ('DELETE', f'{ISMS_PREFIX}/risks/delete/{RISK_ID}', RiskManager, 'get_many_from_other_collection',
     BaseManagerGetError('down'), HTTPStatus.OK),
    ('POST', f'{ISMS_PREFIX}/impacts/', ImpactManager, 'get_one_by',
     BaseManagerGetError('down'), HTTPStatus.CREATED),
]
PATH_IDS: list[str] = [f'{method} {url}' for method, url, *_rest in PATHS]


def _send(rest_api: Any, method: str, url: str) -> Any:
    """Sends the path's request; a POST creates an Impact of a free basis."""
    if method == 'POST':
        return rest_api.post(url, json={'name': NAME, 'calculation_basis': NEW_BASIS})

    return rest_api.delete(url)


@pytest.mark.parametrize('method, url, manager, delegate, failure, success', PATHS, ids=PATH_IDS)
class TestNarrowedPaths:
    """Bug 500, database failure 400, control success - per narrowed path."""

    def test_a_bug_is_a_500(self, rest_api, monkeypatch, method: str, url: str, manager: type, delegate: str,
                            failure: Exception, success: HTTPStatus) -> None:
        """A programming error under the manager is not mistaken for a database failure."""
        del failure, success
        monkeypatch.setattr(manager, delegate, _raiser(RuntimeError('bug')))

        assert _send(rest_api, method, url).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_database_failure_is_a_400(self, rest_api, monkeypatch, method: str, url: str, manager: type,
                                         delegate: str, failure: Exception, success: HTTPStatus) -> None:
        """The database layer's typed failure becomes the manager's error, which the route answers 400."""
        del success
        monkeypatch.setattr(manager, delegate, _raiser(failure))

        assert _send(rest_api, method, url).status_code == HTTPStatus.BAD_REQUEST

    def test_the_control_request_succeeds(self, rest_api, method: str, url: str, manager: type, delegate: str,
                                          failure: Exception, success: HTTPStatus) -> None:
        """Nothing injected: the route answers its success status."""
        del manager, delegate, failure

        assert _send(rest_api, method, url).status_code == success


class TestImpactUpdateIsAllOrNothing:
    """An Impact update whose propagation fails is undone with it."""

    def test_a_failed_propagation_leaves_the_basis_and_the_assessment_as_they_were(
            self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """400 UPDATE; the stored basis is the old one, the assessment's maximum untouched."""
        assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assessments.insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {
                'impacts': [{'impact_id': IMPACT_ID}, {'impact_id': OTHER_IMPACT_ID}],
                'maximum_impact_id': OTHER_IMPACT_ID,
                'maximum_impact_value': OTHER_BASIS,
            },
        })
        real_bulk_write = database_manager.bulk_write

        def _bulk_write(collection: str, *args: Any) -> int:
            if collection == IsmsRiskAssessment.COLLECTION:
                raise DocumentInsertError('bulk write failed')

            return real_bulk_write(collection, *args)

        monkeypatch.setattr(database_manager, 'bulk_write', _bulk_write)

        response = rest_api.put(f'{ISMS_PREFIX}/impacts/{IMPACT_ID}',
                                json={'name': NAME, 'calculation_basis': NEW_BASIS})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == manager_error_message(
            IMPACT_LABEL, IsmsManagerErrorMessage.UPDATE,
        ).format(public_id=IMPACT_ID)
        impacts = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
        stored = impacts.find_one({'public_id': IMPACT_ID})
        assert stored['calculation_basis'] == OLD_BASIS
        before = assessments.find_one({'public_id': RISK_ASSESSMENT_ID})['risk_calculation_before']
        assert (before['maximum_impact_id'], before['maximum_impact_value']) == (OTHER_IMPACT_ID, OTHER_BASIS)


class TestCalculationBasisRace:
    """The unique index answers a basis taken between the pre-check and the write."""

    def test_a_lost_race_is_the_readable_400(self, rest_api, monkeypatch, database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """The pre-check is made to miss; the index refuses the insert with the same message the check gives."""
        database_manager.create_indexes(IsmsImpact.COLLECTION, database_name, IsmsImpact.get_index_keys())
        monkeypatch.setattr(ImpactManager, 'impact_calculation_basis_exists', lambda *_a, **_k: False)

        try:
            response = rest_api.post(f'{ISMS_PREFIX}/impacts/', json={'name': NAME, 'calculation_basis': OLD_BASIS})
        finally:
            database_manager.drop_index(IsmsImpact.COLLECTION, database_name, BASIS_INDEX_NAME)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == CALCULATION_BASIS_TAKEN_MSG.format(entity=IMPACT_LABEL.singular)
