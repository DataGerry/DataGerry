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
Functional tests for the ISMS configuration status route over HTTP

GET /isms/config/status answers with the per-section configuration flags. It needs no right, by design: every
ISMS screen reads it, so any logged-in user of a licensed installation reaches it, whichever rights their group
holds. Because nothing guards it, it only reads - pinned here:

  - a user whose group holds no right at all, and one holding a single report right, get the flags
  - a missing RiskMatrix is reported as not ready and is NOT recreated (``GET /isms/risk_matrix/1`` does that)
  - a stored grid whose size does not match the scales is not ready, even with every cell classed
  - a failed count or RiskMatrix read is a 400 naming the status, an unexpected error a 500
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import RiskMatrixManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.isms_model import IsmsImpact, IsmsImpactCategory, IsmsLikelihood, IsmsRiskClass, IsmsRiskMatrix
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE
from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

STATUS_URL: str = '/isms/config/status'
RISK_MATRIX_ID: int = 1
STATUS_KEYS: set[str] = {'risk_classes', 'likelihoods', 'impacts', 'impact_categories', 'risk_matrix'}

RIGHTLESS_GROUP_ID: int = 88401
REPORT_GROUP_ID: int = 88402
RIGHTLESS_USER_ID: int = 88411
REPORT_USER_ID: int = 88412
REPORT_VIEW_RIGHT: str = 'base.isms.report.view'

# Scale entries seeded on top of whatever the collections hold, so every minimum is reached
SEEDED_RISK_CLASS_IDS: list[int] = [88421, 88422, 88423]
SEEDED_LIKELIHOOD_IDS: list[int] = [88431, 88432, 88433]
SEEDED_IMPACT_IDS: list[int] = [88441, 88442, 88443]
SEEDED_IMPACT_CATEGORY_IDS: list[int] = [88451]
CLASSED: int = 88421


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated config route is reachable in these route-behaviour tests"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


def _risk_matrix_doc(database_manager: MongoDatabaseManager, database_name: str) -> dict | None:
    """Reads the singleton RiskMatrix document straight from the collection"""
    return database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name).find_one(
        {'public_id': RISK_MATRIX_ID}
    )


def test_status_returns_all_section_flags(rest_api) -> None:
    """The status route answers 200 with a boolean flag for every configuration section"""
    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK
    assert STATUS_KEYS.issubset(response.json.keys())
    assert all(isinstance(value, bool) for value in response.json.values())


@pytest.fixture(name='stored_matrix')
def fixture_stored_matrix(database_manager: MongoDatabaseManager, database_name: str):
    """The singleton RiskMatrix collection, its stored document restored after the test"""
    matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
    stored = _risk_matrix_doc(database_manager, database_name)
    yield matrices
    matrices.delete_many({'public_id': RISK_MATRIX_ID})

    if stored:
        matrices.insert_one(stored)


def test_status_reports_a_missing_risk_matrix_as_unfinished_and_writes_nothing(
        rest_api, database_manager: MongoDatabaseManager, database_name: str, stored_matrix) -> None:
    """A route no right guards only reads - recreating the singleton is GET /isms/risk_matrix/1's job"""
    stored_matrix.delete_many({'public_id': RISK_MATRIX_ID})

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.json['risk_matrix'] is False
    assert _risk_matrix_doc(database_manager, database_name) is None


def test_status_reports_an_empty_risk_matrix_as_unfinished(
        rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    A grid with no cells is not a finished risk-matrix step

    ``all([])`` is vacuously true, so an unguarded ``check_risk_classes_set_in_matrix`` would answer
    True for an empty grid. With every scale at its minimum that would reach the wizard as
    ``'risk_matrix': True`` - the step reported complete for a matrix nothing can be evaluated
    against. The scale-minimum guard in build_isms_config_status would mask it here, so this
    asserts the flag directly against an empty grid.
    """
    matrix_collection = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
    matrix_collection.update_one({'public_id': RISK_MATRIX_ID}, {'$set': {'risk_matrix': []}})

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.json['risk_matrix'] is False


@pytest.mark.parametrize('manager, method, error', [
    (RiskClassManager, 'count_documents', BaseManagerGetError('down')),
    (RiskMatrixManager, 'get_item', RiskMatrixManagerGetError('down')),
], ids=['count', 'risk-matrix-read'])
def test_status_read_failure_returns_400(rest_api, monkeypatch, manager: Any, method: str,
                                         error: Exception) -> None:
    """A failed read is named, like every other ISMS route's, not a 500"""
    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(manager, method, _fail)

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == ISMS_CONFIG_STATUS_READ_FAILED_MESSAGE


def test_status_unexpected_error_returns_500(rest_api, monkeypatch) -> None:
    """An unexpected error while computing the configuration status surfaces as 500"""
    def _boom(*_args, **_kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(RiskClassManager, 'count_documents', _boom)

    assert rest_api.get(STATUS_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_status_http_error_is_reraised(rest_api, monkeypatch) -> None:
    """An HTTPException raised while computing the status propagates unchanged (not masked as 500)"""
    def _bad(*_args, **_kwargs):
        raise BadRequest()

    monkeypatch.setattr(
        'cmdb.interface.rest_api.routes.isms_routes.isms_config_routes.build_isms_config_status', _bad,
    )

    assert rest_api.get(STATUS_URL).status_code == HTTPStatus.BAD_REQUEST

# ------------------------------------------------- no right needed -------------------------------------------------- #

def _insert_user(database_manager: MongoDatabaseManager, database_name: str, user_id: int,
                 group_id: int) -> CmdbUser:
    """Stores an active user in ``group_id`` and answers the model the test client sends as"""
    user_name: str = f'isms-config-{user_id}'
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
    })

    return CmdbUser(public_id=user_id, user_name=user_name, active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A user whose group holds no right at all, and one holding a single ISMS report right"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [RIGHTLESS_GROUP_ID, REPORT_GROUP_ID]}})
        users.delete_many({'public_id': {'$in': [RIGHTLESS_USER_ID, REPORT_USER_ID]}})

    _purge()
    groups.insert_many([
        {'public_id': RIGHTLESS_GROUP_ID, 'name': 'isms-config-rightless', 'label': 'No rights', 'rights': []},
        {'public_id': REPORT_GROUP_ID, 'name': 'isms-config-reports', 'label': 'Reports',
         'rights': [REPORT_VIEW_RIGHT]},
    ])
    yield {
        'rightless': _insert_user(database_manager, database_name, RIGHTLESS_USER_ID, RIGHTLESS_GROUP_ID),
        'reports': _insert_user(database_manager, database_name, REPORT_USER_ID, REPORT_GROUP_ID),
    }
    _purge()


@pytest.mark.parametrize('who', ['rightless', 'reports'])
def test_status_needs_no_right(rest_api, users: dict[str, CmdbUser], who: str) -> None:
    """Every ISMS screen reads it, so every logged-in user of a licensed installation gets the flags"""
    response = rest_api.get(STATUS_URL, user=users[who])

    assert response.status_code == HTTPStatus.OK
    assert set(response.json) == STATUS_KEYS


def test_status_still_needs_a_login(rest_api) -> None:
    """No right is not no authentication"""
    response = rest_api.get(STATUS_URL, environ_overrides={'HTTP_AUTHORIZATION': ''})

    assert response.status_code == HTTPStatus.UNAUTHORIZED

# ----------------------------------------------- the matrix as stored ----------------------------------------------- #

@pytest.fixture(name='configured')
def fixture_configured(database_manager: MongoDatabaseManager, database_name: str, stored_matrix):
    """Every scale at its minimum on top of what is stored; answers a grid builder over the actual scales"""
    seeded: list[tuple[str, list[int]]] = [
        (IsmsRiskClass.COLLECTION, SEEDED_RISK_CLASS_IDS),
        (IsmsLikelihood.COLLECTION, SEEDED_LIKELIHOOD_IDS),
        (IsmsImpact.COLLECTION, SEEDED_IMPACT_IDS),
        (IsmsImpactCategory.COLLECTION, SEEDED_IMPACT_CATEGORY_IDS),
    ]

    for collection, public_ids in seeded:
        database_manager.get_collection(collection, database_name).insert_many(
            [{'public_id': public_id, 'name': f'config-status-{public_id}', 'calculation_basis': float(index + 1)}
             for index, public_id in enumerate(public_ids)])

    def _store_grid(drop_cells: int = 0, extra_cells: int = 0) -> None:
        """Stores a fully classed grid over the actual scales, minus or plus some cells"""
        impact_ids = [doc['public_id'] for doc in
                      database_manager.get_collection(IsmsImpact.COLLECTION, database_name).find()]
        likelihood_ids = [doc['public_id'] for doc in
                          database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name).find()]
        cells: list[dict[str, Any]] = [
            {'impact_id': impact_id, 'likelihood_id': likelihood_id, 'calculated_value': 1.0,
             'risk_class_id': CLASSED}
            for impact_id in impact_ids for likelihood_id in likelihood_ids
        ]
        cells = cells[:len(cells) - drop_cells] + cells[:extra_cells]
        stored_matrix.delete_many({'public_id': RISK_MATRIX_ID})
        stored_matrix.insert_one({'public_id': RISK_MATRIX_ID, 'risk_matrix': cells, 'matrix_unit': None})

    yield _store_grid

    for collection, public_ids in seeded:
        database_manager.get_collection(collection, database_name).delete_many({'public_id': {'$in': public_ids}})


def test_a_current_fully_classed_grid_is_ready(rest_api, configured) -> None:
    """One classed cell per (impact, likelihood) pair, every scale at its minimum: all five flags"""
    configured()

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK
    assert all(response.json[key] for key in STATUS_KEYS)


@pytest.mark.parametrize('drop_cells, extra_cells', [(1, 0), (0, 1)], ids=['a-cell-short', 'a-cell-too-many'])
def test_a_grid_that_does_not_match_the_scales_is_not_ready(rest_api, configured, drop_cells: int,
                                                            extra_cells: int) -> None:
    """Every stored cell classed, but the grid is stale - GET /isms/risk_matrix/1 would rebuild it first"""
    configured(drop_cells=drop_cells, extra_cells=extra_cells)

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.json['risk_matrix'] is False
    assert response.json['impacts'] and response.json['likelihoods']
