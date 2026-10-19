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
Functional tests: every Impact, Likelihood and ImpactCategory write is all-or-nothing

Each route writes more than its own document - the ImpactCategories' descriptions of an Impact, the RiskAssessments
holding a category or using a changed calculation_basis, and the RiskMatrix rebuilt from the scales. These tests let
the earlier writes land, break a later one, and assert the five collections are exactly as they were before the
request; a failure of the category fan-out answers its own 400, a failure of the RiskMatrix write the generic 500;
an undo that cannot finish answers the 500 naming what is left.
"""
# pylint: disable=protected-access
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsRiskAssessment,
    IsmsRiskMatrix,
)
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    IMPACT_LABEL,
    IsmsManagerErrorMessage,
)
from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.errors.manager.impact_category_manager import ImpactCategoryManagerDeleteError
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

IMPACTS_URL: str = '/isms/impacts'
LIKELIHOODS_URL: str = '/isms/likelihoods'
CATEGORIES_URL: str = '/isms/impact_categories'

IMPACT_USED_ID: int = 97101
IMPACT_FREE_ID: int = 97102
LIKELIHOOD_USED_ID: int = 97111
LIKELIHOOD_FREE_ID: int = 97112
CATEGORY_ID: int = 97121
RA_ID: int = 97131

# Weights no other test uses, so the calculation-basis pre-check never meets a leftover
IMPACT_USED_BASIS: float = 71.11
IMPACT_FREE_BASIS: float = 72.22
LIKELIHOOD_USED_BASIS: float = 73.33
LIKELIHOOD_FREE_BASIS: float = 74.44
NEW_BASIS: float = 75.55
CHANGED_BASIS: float = 76.66

# Every document a create route writes carries this name, so it can be purged without knowing its server-drawn id
MARKER_NAME: str = 'scale-atomicity-marker'
DESCRIPTION_TEXT: str = 'kept description'

COLLECTIONS: tuple[str, ...] = (
    IsmsImpact.COLLECTION, IsmsLikelihood.COLLECTION, IsmsImpactCategory.COLLECTION,
    IsmsRiskAssessment.COLLECTION, IsmsRiskMatrix.COLLECTION,
)


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str):
    """Two impacts, two likelihoods, one category, one assessment using the 'used' pair, and the stored matrix."""
    def collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        collection(IsmsImpact.COLLECTION).delete_many(
            {'$or': [{'public_id': {'$in': [IMPACT_USED_ID, IMPACT_FREE_ID]}}, {'name': MARKER_NAME}]})
        collection(IsmsLikelihood.COLLECTION).delete_many(
            {'$or': [{'public_id': {'$in': [LIKELIHOOD_USED_ID, LIKELIHOOD_FREE_ID]}}, {'name': MARKER_NAME}]})
        collection(IsmsImpactCategory.COLLECTION).delete_many(
            {'$or': [{'public_id': CATEGORY_ID}, {'name': MARKER_NAME}]})
        collection(IsmsRiskAssessment.COLLECTION).delete_many({'public_id': RA_ID})

    _purge()
    collection(IsmsImpact.COLLECTION).insert_many([
        {'public_id': IMPACT_USED_ID, 'name': 'Used', 'calculation_basis': IMPACT_USED_BASIS, 'description': None},
        {'public_id': IMPACT_FREE_ID, 'name': 'Free', 'calculation_basis': IMPACT_FREE_BASIS, 'description': None},
    ])
    collection(IsmsLikelihood.COLLECTION).insert_many([
        {'public_id': LIKELIHOOD_USED_ID, 'name': 'Used', 'calculation_basis': LIKELIHOOD_USED_BASIS,
         'description': None},
        {'public_id': LIKELIHOOD_FREE_ID, 'name': 'Free', 'calculation_basis': LIKELIHOOD_FREE_BASIS,
         'description': None},
    ])
    collection(IsmsImpactCategory.COLLECTION).insert_one({
        'public_id': CATEGORY_ID, 'name': 'Category', 'sort': 1, 'impact_descriptions': [
            {'impact_id': IMPACT_USED_ID, 'value': DESCRIPTION_TEXT},
            {'impact_id': IMPACT_FREE_ID, 'value': DESCRIPTION_TEXT},
        ],
    })
    matrix: dict[str, Any] = {
        'impacts': [{'impact_category_id': CATEGORY_ID, 'impact_id': IMPACT_USED_ID}],
        'maximum_impact_id': IMPACT_USED_ID, 'maximum_impact_value': IMPACT_USED_BASIS,
        'likelihood_id': LIKELIHOOD_USED_ID, 'likelihood_value': LIKELIHOOD_USED_BASIS,
    }
    collection(IsmsRiskAssessment.COLLECTION).insert_one({
        'public_id': RA_ID, 'risk_calculation_before': dict(matrix), 'risk_calculation_after': dict(matrix),
    })

    if collection(IsmsRiskMatrix.COLLECTION).find_one({'public_id': RISK_MATRIX_PUBLIC_ID}) is None:
        collection(IsmsRiskMatrix.COLLECTION).insert_one(
            {'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': [], 'matrix_unit': None})

    yield collection
    _purge()


def _snapshot(collection: Callable[[str], Any]) -> dict[str, list[dict[str, Any]]]:
    """Every document of the five collections the scale writes touch, without MongoDB's id, in public_id order"""
    return {name: list(collection(name).find({}, {'_id': 0}).sort('public_id', 1)) for name in COLLECTIONS}


def _raiser(error: Exception) -> Callable[..., None]:
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _applied_then_raising(real: Callable[..., Any], error: Exception) -> Callable[..., None]:
    """A replacement whose write lands - and then reports a failure"""
    def _run(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        raise error

    return _run


@pytest.fixture(name='matrix_write_fails')
def fixture_matrix_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The RiskMatrix rebuild - the last write of every scale route - fails after it landed"""
    monkeypatch.setattr(RiskMatrixManager, 'update_item', _applied_then_raising(
        RiskMatrixManager.update_item, RiskMatrixManagerUpdateError('down')))


def _scale_body(basis: float, name: str = MARKER_NAME) -> dict[str, Any]:
    """An Impact / Likelihood body"""
    return {'name': name, 'calculation_basis': basis, 'description': None}


@pytest.mark.usefixtures('matrix_write_fails')
class TestAFailedMatrixRebuildTakesTheScaleWriteBack:
    """The RiskMatrix fails last: the scale entry and everything written for it are back as they were - a 500."""

    @pytest.mark.parametrize('url', [IMPACTS_URL, LIKELIHOODS_URL], ids=['impact', 'likelihood'])
    def test_a_create(self, rest_api, database, url: str) -> None:
        """The new entry and (for an Impact) its description in every category are gone again"""
        before = _snapshot(database)

        response = rest_api.post(f'{url}/', json=_scale_body(NEW_BASIS))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(database) == before

    @pytest.mark.parametrize('url, public_id', [(IMPACTS_URL, IMPACT_USED_ID), (LIKELIHOODS_URL, LIKELIHOOD_USED_ID)],
                             ids=['impact', 'likelihood'])
    def test_an_update_changing_the_basis(self, rest_api, database, url: str, public_id: int) -> None:
        """The entry and the RiskAssessments rewritten for its new weight are back"""
        before = _snapshot(database)

        response = rest_api.put(f'{url}/{public_id}', json=_scale_body(CHANGED_BASIS, 'Used'))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(database) == before

    @pytest.mark.parametrize('url, public_id', [(IMPACTS_URL, IMPACT_USED_ID), (LIKELIHOODS_URL, LIKELIHOOD_USED_ID)],
                             ids=['impact', 'likelihood'])
    def test_an_update_keeping_the_basis(self, rest_api, database, url: str, public_id: int) -> None:
        """The plain update is recorded with the stored entry and put back"""
        before = _snapshot(database)

        response = rest_api.put(f'{url}/{public_id}', json=_scale_body(
            IMPACT_USED_BASIS if url == IMPACTS_URL else LIKELIHOOD_USED_BASIS, 'Renamed'))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(database) == before

    @pytest.mark.parametrize('url, public_id', [(IMPACTS_URL, IMPACT_FREE_ID), (LIKELIHOODS_URL, LIKELIHOOD_FREE_ID)],
                             ids=['impact', 'likelihood'])
    def test_a_delete(self, rest_api, database, url: str, public_id: int) -> None:
        """The entry is back under its id, and (for an Impact) every category's description of it, text included"""
        before = _snapshot(database)

        response = rest_api.delete(f'{url}/{public_id}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(database) == before


class TestAFailedCategoryFanOut:
    """The Impact's descriptions in the categories fail: the route's own 400, and nothing left behind."""

    def test_a_create_whose_descriptions_fail_answers_400_and_keeps_no_impact(self, rest_api, database,
                                                                             monkeypatch) -> None:
        """The descriptions landed, then failed: the Impact and the descriptions are gone"""
        monkeypatch.setattr(ImpactCategoryManager, 'update_many', _applied_then_raising(
            ImpactCategoryManager.update_many, BaseManagerUpdateError('down')))
        before = _snapshot(database)

        response = rest_api.post(f'{IMPACTS_URL}/', json=_scale_body(NEW_BASIS))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == IsmsManagerErrorMessage.CATEGORY_DESCRIPTIONS.value.format(
            entity=IMPACT_LABEL.singular)
        assert _snapshot(database) == before

    def test_a_delete_whose_descriptions_fail_answers_400_and_keeps_the_impact(self, rest_api, database,
                                                                              monkeypatch) -> None:
        """The pull landed, then failed: the Impact and its descriptions are back"""
        monkeypatch.setattr(ImpactCategoryManager, '_pull_impact_descriptions', _applied_then_raising(
            ImpactCategoryManager._pull_impact_descriptions, BaseManagerUpdateError('down')))
        before = _snapshot(database)

        response = rest_api.delete(f'{IMPACTS_URL}/{IMPACT_FREE_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(database) == before


class TestCategoryWrites:
    """A category's own create and delete reach every RiskAssessment - all of it, or none."""

    def test_a_create_whose_push_fails_keeps_no_category_and_no_entry(self, rest_api, database,
                                                                    monkeypatch) -> None:
        """The push landed in the assessments, then failed: the 400, and neither category nor entry remains"""
        monkeypatch.setattr(ImpactCategoryManager, 'add_impact_category_to_risk_assessments', _applied_then_raising(
            ImpactCategoryManager.add_impact_category_to_risk_assessments, BaseManagerUpdateError('down')))
        before = _snapshot(database)

        response = rest_api.post(f'{CATEGORIES_URL}/', json={'name': MARKER_NAME, 'impact_descriptions': []})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(database) == before

    def test_a_delete_whose_document_delete_fails_restores_the_assessments(self, rest_api, database,
                                                                          monkeypatch) -> None:
        """The assessments were already rewritten when the delete failed: their impacts and maximum are back"""
        monkeypatch.setattr(ImpactCategoryManager, 'delete_item', _raiser(ImpactCategoryManagerDeleteError('down')))
        before = _snapshot(database)

        response = rest_api.delete(f'{CATEGORIES_URL}/{CATEGORY_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(database) == before

    def test_a_delete_that_landed_and_failed_brings_the_category_back(self, rest_api, database,
                                                                     monkeypatch) -> None:
        """The document delete itself landed, then reported a failure: the category is back under its id"""
        monkeypatch.setattr(ImpactCategoryManager, 'delete_item', _applied_then_raising(
            ImpactCategoryManager.delete_item, ImpactCategoryManagerDeleteError('down')))
        before = _snapshot(database)

        response = rest_api.delete(f'{CATEGORIES_URL}/{CATEGORY_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(database) == before


class TestASuccessfulWriteKeepsEverything:
    """The ledger only acts on failure: a clean request leaves every write in place."""

    def test_a_deleted_impact_is_gone_from_the_categories(self, rest_api, database) -> None:
        """The free Impact and its descriptions are removed; the used one's description is kept"""
        response = rest_api.delete(f'{IMPACTS_URL}/{IMPACT_FREE_ID}')

        assert response.status_code == HTTPStatus.ACCEPTED
        category = database(IsmsImpactCategory.COLLECTION).find_one({'public_id': CATEGORY_ID})
        assert category['impact_descriptions'] == [{'impact_id': IMPACT_USED_ID, 'value': DESCRIPTION_TEXT}]

    def test_a_refused_delete_changes_nothing(self, rest_api, database) -> None:
        """An Impact a RiskAssessment uses is refused before anything is written"""
        before = _snapshot(database)

        response = rest_api.delete(f'{IMPACTS_URL}/{IMPACT_USED_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(database) == before


class TestADeleteThatFoundNothing:
    """Another request removed the entry between the route's read and its delete: nothing is recorded for it."""

    @pytest.mark.usefixtures('matrix_write_fails')
    @pytest.mark.parametrize('url, public_id, manager', [
        (IMPACTS_URL, IMPACT_FREE_ID, ImpactManager), (LIKELIHOODS_URL, LIKELIHOOD_FREE_ID, LikelihoodManager),
    ], ids=['impact', 'likelihood'])
    def test_a_later_failure_does_not_bring_the_entry_back(self, rest_api, database, monkeypatch, url: str,
                                                           public_id: int, manager: type) -> None:
        """The concurrent delete stands: the undo restores what this request wrote, never the vanished entry"""
        collection_name: str = IsmsImpact.COLLECTION if manager is ImpactManager else IsmsLikelihood.COLLECTION

        def _gone_meanwhile(_self: Any, entry_id: int) -> bool:
            database(collection_name).delete_one({'public_id': entry_id})
            return False

        monkeypatch.setattr(manager, 'delete_if_unused', _gone_meanwhile)

        response = rest_api.delete(f'{url}/{public_id}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert database(collection_name).find_one({'public_id': public_id}) is None


class TestAnUndoThatCannotFinish:
    """The undo of the matrix fails too: the 500 names the action, the entity and the write still in effect."""

    def test_the_500_names_what_is_left(self, rest_api, database, monkeypatch) -> None:
        """The matrix write landed, failed, and cannot be restored"""
        monkeypatch.setattr(RiskMatrixManager, 'update_item', _applied_then_raising(
            RiskMatrixManager.update_item, RiskMatrixManagerUpdateError('down')))
        monkeypatch.setattr(RiskMatrixManager, 'replace', _raiser(RuntimeError('restore failed')))

        response = rest_api.post(f'{LIKELIHOODS_URL}/', json=_scale_body(NEW_BASIS))
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith('Creating the Likelihood failed part-way')
        assert IsmsRiskMatrix.COLLECTION in message
        assert not database(IsmsLikelihood.COLLECTION).find_one({'name': MARKER_NAME})
