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
Integration tests for the blueprint licence gate against the real authentication and licence store

A fresh app with one gated blueprint, its route under the real `insert_request_user`: the token is
decoded with the real key material, the user read from MongoDB and the licence resolved through the
real LicenseService over the (cleared) active-license store. What only these pieces together show:
the gate's hook records the feature, the decorator enforces it once the caller is known - so a caller
whose token does not validate gets the 401, and a real user on an unlicensed installation the 403
"""
from http import HTTPStatus

import pytest
from flask import Blueprint

from cmdb.database import MongoDatabaseManager
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.route_utils import insert_request_user
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import gate_blueprint
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.security.token.generator import TokenGenerator
# -------------------------------------------------------------------------------------------------------------------- #

GATED_ROUTE: str = '/gated'
VIEW_RESULT: str = 'view-ran'
ISMS_REFUSAL: str = 'The ISMS feature requires a valid license!'


@pytest.fixture(name='client')
def fixture_client(database_manager: MongoDatabaseManager, database_name: str):
    """An on-premise app whose one route is gated behind ISMS, with the active-license store cleared."""
    licences = database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name)
    licences.delete_many({})

    app = BaseCmdbApp(__name__, database_manager=database_manager)
    app.cloud_mode = False
    app.local_mode = False

    blueprint = Blueprint('integration_gated_bp', __name__)

    @blueprint.route(GATED_ROUTE)
    @insert_request_user
    def _view(request_user: CmdbUser) -> str:
        return f'{VIEW_RESULT}:{request_user.public_id}'

    gate_blueprint(blueprint, LicenseFeature.ISMS)
    app.register_blueprint(blueprint)

    yield app.test_client()

    licences.delete_many({})


def _bearer(database_manager: MongoDatabaseManager, user: CmdbUser) -> dict[str, str]:
    """An Authorization header with a real token for the user."""
    token: str = TokenGenerator(database_manager).generate_token(
        payload={'user': {'public_id': user.public_id}}).decode('UTF-8')

    return {'Authorization': f'Bearer {token}'}


def test_an_invalid_token_is_the_401(client) -> None:
    """The token fails to validate: the caller is refused as unauthenticated, not as unlicensed"""
    response = client.get(GATED_ROUTE, headers={'Authorization': 'Bearer not-a-token'})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_real_user_on_an_unlicensed_installation_is_the_403(client, database_manager, full_access_user) -> None:
    """Authenticated from the store, refused by the real licence lookup"""
    response = client.get(GATED_ROUTE, headers=_bearer(database_manager, full_access_user))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert ISMS_REFUSAL in response.get_data(as_text=True)


def test_a_real_user_on_a_licensed_installation_reaches_the_view(client, database_manager, full_access_user,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Licensed: the view runs with the resolved user"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)

    response = client.get(GATED_ROUTE, headers=_bearer(database_manager, full_access_user))

    assert response.status_code == HTTPStatus.OK
    assert response.get_data(as_text=True) == f'{VIEW_RESULT}:{full_access_user.public_id}'
