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
Functional tests for GET /license/subscription, over HTTP

In the hosted cloud the route forwards the subscription license the Service Portal holds, for the tenant user's
email and database, unchanged. The portal client is replaced by a stub; the app runs in hosted cloud mode with a
tenant user in the admin group. Pinned: the 200 answer as sent, the 502 / 503 failure answers, that the HEAD request
carries no body, that the route is a 404 on premise and in local cloud development, and that GET /license/current is
a 404 in the hosted cloud.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from cmdb.database import MongoDatabaseManager
from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.cmdb_license import subscription_license_helper
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    CURRENT_LICENSE_ROUTE,
    HOSTED_CLOUD_ONLY_MESSAGE,
    SERVICE_PORTAL_UNREACHABLE_MESSAGE,
    SUBSCRIPTION_LICENSE_ROUTE,
    SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE,
)

from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

SUBSCRIPTION_URL: str = f'/license{SUBSCRIPTION_LICENSE_ROUTE}'
CURRENT_URL: str = f'/license{CURRENT_LICENSE_ROUTE}'
USER_ID: int = 9861
EMAIL: str = 'license-cloud@acme.com'
RESULT_KEY: str = 'result'
MESSAGE_KEY: str = 'message'
PORTAL_LICENSE: dict[str, Any] = {
    'subId': 'SUB-2026-0042', 'licenseId': 'LIC-7f3a9c21', 'type': 'business',
    'features': ['rest_api', 'ipam', 'isms'], 'startDate': 1767225600000, 'endDate': 4102444800000, 'trial': True,
}


@pytest.fixture(name='tenant_user', autouse=True)
def fixture_tenant_user(database_manager: MongoDatabaseManager, database_name: str):
    """A tenant user of the test database in the admin group; removed again"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'license-cloud-user', 'email': EMAIL, 'active': True,
        'group_id': ADMIN_GROUP_ID, 'registration_time': datetime.now(timezone.utc), 'database': database_name,
        'config_items_limit': None,
    })
    yield
    users.delete_many({'public_id': USER_ID})


@pytest.fixture(name='portal')
def fixture_portal(rest_api, monkeypatch, database_manager: MongoDatabaseManager) -> MagicMock:
    """Hosted cloud, and a portal stub answering the subscription license"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal_class = MagicMock(name='DgServicePortalManager')
    monkeypatch.setattr(subscription_license_helper, 'DgServicePortalManager', portal_class)
    return portal_class.return_value


def _get(rest_api, database_name: str, method: str = 'get', url: str = SUBSCRIPTION_URL) -> Any:
    """GET (or HEAD) a license route as the tenant user"""
    return getattr(rest_api, method)(url, environ_overrides=cloud_auth_header(rest_api, USER_ID, database_name))


def test_the_subscription_license_as_the_portal_sent_it(rest_api, portal, database_name: str) -> None:
    """Asked for the tenant's email and database; trial and the portal's databaseName included, nothing added"""
    answer: dict[str, Any] = {**PORTAL_LICENSE, 'databaseName': database_name}
    portal.get_subscription_license.return_value = answer

    response = _get(rest_api, database_name)

    assert response.status_code == HTTPStatus.OK
    portal.get_subscription_license.assert_called_once_with(EMAIL, database_name)
    assert response.get_json()[RESULT_KEY] == answer


def test_an_answer_off_the_old_schema_is_forwarded(rest_api, portal, database_name: str) -> None:
    """Nothing is checked"""
    answer: dict[str, Any] = {'features': 'ipam', 'trial': False, 'databaseName': 'db_someone_else'}
    portal.get_subscription_license.return_value = answer

    response = _get(rest_api, database_name)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()[RESULT_KEY] == answer


def test_head_answers_without_a_body(rest_api, portal, database_name: str) -> None:
    """Like every GET/HEAD route"""
    portal.get_subscription_license.return_value = PORTAL_LICENSE

    response = _get(rest_api, database_name, method='head')

    assert response.status_code == HTTPStatus.OK
    assert response.get_data() == b''


def test_an_error_answer_is_a_502(rest_api, portal, database_name: str) -> None:
    """With its readable message"""
    portal.get_subscription_license.side_effect = DgServicePortalGetError('status 500')

    response = _get(rest_api, database_name)

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert response.get_json()[MESSAGE_KEY] == SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE


def test_an_unreachable_portal_is_a_503(rest_api, portal, database_name: str) -> None:
    """With its readable message"""
    portal.get_subscription_license.side_effect = requests.ConnectionError('down')

    response = _get(rest_api, database_name)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.get_json()[MESSAGE_KEY] == SERVICE_PORTAL_UNREACHABLE_MESSAGE


def test_the_current_license_is_hidden_in_the_hosted_cloud(rest_api, portal, database_name: str) -> None:
    """The cloud's license is the subscription route; the portal is not asked"""
    response = _get(rest_api, database_name, url=CURRENT_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND
    portal.get_subscription_license.assert_not_called()


def test_hidden_on_premise(rest_api) -> None:
    """There is no Service Portal on premise"""
    response = rest_api.get(SUBSCRIPTION_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.get_json()[MESSAGE_KEY] == HOSTED_CLOUD_ONLY_MESSAGE


def test_hidden_in_local_cloud_development(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local cloud development has no portal either"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    response = rest_api.get(SUBSCRIPTION_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND
