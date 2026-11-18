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
The cloud API-key channel (HTTP Basic + `x-api-key`) when a concurrent request caches the same user first - through
the real REST app in hosted-cloud mode

The user cache is the real collection with its declared indexes; the Service Portal and the tenant-user helpers are
replaced. The concurrent request's cache write happens from inside the portal stub, between this request's "not
cached" read and its own write. That request is served - before, its insert lost on the unique email index and the
caller got a 500 with valid credentials
"""
import base64
import copy
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface import route_utils as ru
from cmdb.manager.security_manager import SYMMETRIC_KEY_ENV_VAR
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CachedSubscriptionKey, CachedUserKey, CmdbCachedUser

from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

PROBE_URL: str = '/types/'
ROUTE_UTILS: str = 'cmdb.interface.route_utils'
CLOUD_USER_HELPER: str = 'cmdb.interface.cloud_user_helper'
EMAIL: str = 'ftest_race@acme.com'
PASSWORD: str = 'secret'
API_KEY: str = 'race-api-key'
OTHER_API_KEY: str = 'concurrent-api-key'
API_LEVEL: int = 3
# The tenant's AES key in hosted cloud mode - the password HMAC is keyed with it
CLOUD_AES_KEY: bytes = bytes(range(32))
# The API path asks the portal twice - the login check, then the full subscription list it caches
FULL_LIST_CALL: int = 2
API_KEY_ENVIRON: dict[str, str] = {
    'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode('ascii')).decode('ascii'),
    'HTTP_X_API_KEY': API_KEY,
}


@pytest.fixture(autouse=True)
def _hosted(rest_api, monkeypatch, database_manager) -> None:
    """Hosted cloud mode for every test, with the AES key the password HMAC needs there"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setenv(SYMMETRIC_KEY_ENV_VAR, base64.b64encode(CLOUD_AES_KEY).decode('ascii'))


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager(database_manager: MongoDatabaseManager, database_name: str) -> CachedUserManager:
    """A CachedUserManager on the test database's cache collection"""
    manager: CachedUserManager = CachedUserManager(database_manager)
    manager.db_name = database_name

    return manager


@pytest.fixture(name='cache_collection')
def fixture_cache_collection(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The cache collection with its declared indexes (the suite never builds them), emptied of the test user"""
    collection: Any = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
    collection.delete_many({CachedUserKey.EMAIL.value: EMAIL})
    collection.create_indexes(CmdbCachedUser.get_index_keys())

    yield collection

    collection.delete_many({CachedUserKey.EMAIL.value: EMAIL})

    for index in CmdbCachedUser.get_index_keys():
        collection.drop_index(index.document['name'])


def _portal_answer(database_name: str) -> dict[str, Any]:
    """What the portal answers for the user: one valid subscription on the test tenant, the plaintext password"""
    return {
        CachedUserKey.EMAIL.value: EMAIL,
        CachedUserKey.PASSWORD.value: PASSWORD,
        CachedUserKey.API_LEVEL.value: API_LEVEL,
        CachedUserKey.SUBSCRIPTIONS.value: [{
            CachedSubscriptionKey.DATABASE.value: database_name,
            CachedSubscriptionKey.API_LEVEL.value: API_LEVEL,
            CachedSubscriptionKey.IS_VALID.value: True,
        }],
    }


def test_a_request_racing_a_concurrent_cache_write_is_served(
        rest_api, database_name: str, cached_user_manager: CachedUserManager, cache_collection: Any) -> None:
    """200, and the user keeps one cache entry - stamped with this request's api key"""
    calls: list[int] = []

    def _portal(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(FULL_LIST_CALL)

        if len(calls) == FULL_LIST_CALL:
            concurrent: dict[str, Any] = _portal_answer(database_name)
            concurrent[CachedUserKey.SUBSCRIPTIONS.value][0][CachedSubscriptionKey.API_KEY.value] = OTHER_API_KEY
            cached_user_manager.insert_cached_user(concurrent)

        return copy.deepcopy(_portal_answer(database_name))

    tenant_user: Any = ru.CmdbUser(public_id=1, user_name='admin', active=True, group_ids=[1], database=database_name)

    with patch(f'{CLOUD_USER_HELPER}.get_cached_user_manager', return_value=cached_user_manager), \
         patch(f'{CLOUD_USER_HELPER}.validate_subscription_user', side_effect=_portal), \
         patch(f'{CLOUD_USER_HELPER}.check_db_exists', return_value=True), \
         patch(f'{ROUTE_UTILS}.set_admin_user'), \
         patch(f'{ROUTE_UTILS}.retrieve_user', return_value=tenant_user):
        response: Any = rest_api.get(PROBE_URL, environ_overrides=API_KEY_ENVIRON)

    assert response.status_code == HTTPStatus.OK

    entries: list[dict[str, Any]] = list(cache_collection.find({CachedUserKey.EMAIL.value: EMAIL}))
    assert len(entries) == 1
    assert entries[0][CachedUserKey.SUBSCRIPTIONS.value][0][CachedSubscriptionKey.API_KEY.value] == API_KEY
