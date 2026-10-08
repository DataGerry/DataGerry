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
Functional coverage of where a request's work is stored - there is no fallback database name any more

A CmdbUser used to default its ``database`` to ``'test'``. On premise every user carried it, and the OpenCelium
routes bound their token cache to it - a database named ``test``. Pinned here over the real app:

  - on premise a user created through ``POST /users/`` is stored without a database name
  - on premise an OpenCelium route caches its token in the configured database (``SettingsManager`` built with
    None), whatever the request user's document says
  - in hosted cloud mode a tenant user whose document names no database is refused, instead of being served out
    of a shared database

The OpenCelium HTTP side is stubbed: the connector's config, and the manager call that would reach OpenCelium
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.open_celium_managers.oc_invoker_manager import OcInvokerManager
from cmdb.manager.system_manager import settings_manager
from cmdb.open_celium.oc_api_connector import OcApiConnector
from cmdb.open_celium.oc_constants import OC_CONFIG_BASE_URL_KEY, OcConfigKey
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users/'
INVOKERS_URL: str = '/open_celium/invokers'
TENANT_PROBE_URL: str = '/types/?limit=1'

# public_id of the user behind the REST test client (full_access_user)
REQUEST_USER_ID: int = 1
CREATED_USER_ID: int = 9780
DATABASE_LESS_TENANT_USER_ID: int = 9781
STRAY_DATABASE: str = 'test'

STUB_OC_CONFIG: dict[str, Any] = {
    OcConfigKey.HOST: 'oc.invalid', OcConfigKey.PORT: 1, OcConfigKey.PROTOCOL: 'http',
    OcConfigKey.EMAIL: 'oc@x.io', OcConfigKey.USER: 'oc', OcConfigKey.PASSWORD: 'pw',
    OC_CONFIG_BASE_URL_KEY: 'http://oc.invalid:1',
}


def test_an_on_premise_user_is_stored_without_a_database_name(
    rest_api, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """POST /users/ stores the user without a database name (absent or null) - never the old 'test'"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    payload = {
        'public_id': CREATED_USER_ID, 'user_name': f'tenant-db-{CREATED_USER_ID}', 'active': True,
        'group_id': 1, 'password': 'initial-pass', 'authenticator': 'LocalAuthenticationProvider',
    }
    created_id: int | None = None

    try:
        response = rest_api.post(USERS_URL, json=payload)
        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['result_id']

        stored = users.find_one({'public_id': created_id})
        assert stored.get('database') is None
    finally:
        users.delete_many({'public_id': {'$in': [CREATED_USER_ID, created_id]}})


def test_an_on_premise_open_celium_route_caches_its_token_in_the_configured_database(
    rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The connector's SettingsManager is built with None - the configured database - not the user's field

    The request user's stored document names the old fallback, as every on-premise user written before carries it;
    it must not reach the token cache
    """
    bound: list[Any] = []
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    previous: dict[str, Any] = users.find_one({'public_id': REQUEST_USER_ID}, {'database': 1}) or {}
    users.update_one({'public_id': REQUEST_USER_ID}, {'$set': {'database': STRAY_DATABASE}})

    class _RecordingSettingsManager:
        """Records the database the token cache would be opened in."""

        def __init__(self, _dbm: Any, database: str | None = None) -> None:
            bound.append(database)

    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)
    monkeypatch.setattr(OcApiConnector, '_load_local_config', staticmethod(lambda: STUB_OC_CONFIG))
    monkeypatch.setattr(settings_manager, 'SettingsManager', _RecordingSettingsManager)
    monkeypatch.setattr(OcInvokerManager, 'get_all_invokers', lambda _self, *_args, **_kwargs: [])

    try:
        response = rest_api.get(INVOKERS_URL)
    finally:
        users.update_one({'public_id': REQUEST_USER_ID}, {'$set': {'database': previous.get('database')}})

    assert response.status_code == HTTPStatus.OK
    assert bound == [None]


def test_a_cloud_tenant_user_without_a_database_is_refused(
    rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """Its token names the tenant, but its own document names no database: refused, not served from elsewhere"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': DATABASE_LESS_TENANT_USER_ID})
    users.insert_one({
        'public_id': DATABASE_LESS_TENANT_USER_ID, 'user_name': 'no-database', 'email': 'no-database@x.io',
        'active': True, 'group_id': 1, 'database': None, 'registration_time': datetime.now(timezone.utc),
    })
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    stray_collections_before = set(database_manager.connector.client[STRAY_DATABASE].list_collection_names())

    try:
        response = rest_api.get(
            TENANT_PROBE_URL, environ_overrides=cloud_auth_header(rest_api, DATABASE_LESS_TENANT_USER_ID, database_name),
        )
    finally:
        users.delete_many({'public_id': DATABASE_LESS_TENANT_USER_ID})

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert set(database_manager.connector.client[STRAY_DATABASE].list_collection_names()) == stray_collections_before
