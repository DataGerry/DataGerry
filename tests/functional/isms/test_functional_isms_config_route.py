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

GET /isms/config/status answers with the per-section configuration flags. The RiskMatrix is a
singleton (public_id 1); the route self-heals - if the matrix document is missing it is recreated
with the empty default instead of the route failing
"""
from http import HTTPStatus

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.models.isms_model import IsmsRiskMatrix
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

STATUS_URL: str = '/isms/config/status'
RISK_MATRIX_ID: int = 1
STATUS_KEYS: set[str] = {'risk_classes', 'likelihoods', 'impacts', 'impact_categories', 'risk_matrix'}


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


def test_status_recreates_missing_risk_matrix(
    rest_api,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """With the singleton RiskMatrix deleted the status route recreates it instead of failing"""
    database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name).delete_many(
        {'public_id': RISK_MATRIX_ID}
    )
    assert _risk_matrix_doc(database_manager, database_name) is None

    response = rest_api.get(STATUS_URL)

    assert response.status_code == HTTPStatus.OK

    recreated = _risk_matrix_doc(database_manager, database_name)
    assert recreated is not None
    assert recreated['risk_matrix'] == []
    assert recreated['matrix_unit'] is None


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
