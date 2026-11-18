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
Integration tests for the cloud user-cache sync when a concurrent request caches the same user first

``check_user_in_service_portal`` reads "not cached" before its Service Portal calls and writes the entry after them.
A second request with the same credentials can write the entry in between; the write is an upsert keyed on the email,
so the later request refreshes that entry instead of failing on the unique email index (a 500 on the x-api-key
channel). The portal is stubbed and the concurrent request's write is made from inside the stub - the one point where
the two requests interleave - against the real collection with its declared indexes
"""
import copy
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import cmdb.interface.cloud_user_helper as cuh
from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CachedSubscriptionKey, CachedUserKey, CmdbCachedUser

from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

EMAIL: str = 'itest_race@acme.com'
PASSWORD: str = 'secret'
API_KEY: str = 'race-api-key'
OTHER_API_KEY: str = 'concurrent-api-key'
TENANT_DB: str = 'itest_race_tenant'
API_LEVEL: int = 3
# The API path asks the portal twice - the login check, then the full subscription list it caches
FULL_LIST_CALL: int = 2
FIRST_CALL: int = 1


def _hmac(plain: str) -> str:
    """The stand-in password digest - the cache stores and compares digests only"""
    return f'hmac({plain})'


class _StubSecurityManager:
    """A SecurityManager whose HMAC is ``_hmac`` - the real one needs the tenant's key material"""

    def __init__(self, *_args: Any) -> None:
        """Takes the database manager the real one is built with"""

    @staticmethod
    def generate_hmac(plain: str) -> str:
        """Digests a password"""
        return _hmac(plain)


def _portal_answer() -> dict[str, Any]:
    """What the portal answers for the user: one valid subscription, the plaintext password"""
    return {
        CachedUserKey.EMAIL.value: EMAIL,
        CachedUserKey.PASSWORD.value: PASSWORD,
        CachedUserKey.API_LEVEL.value: API_LEVEL,
        CachedUserKey.SUBSCRIPTIONS.value: [{
            CachedSubscriptionKey.DATABASE.value: TENANT_DB,
            CachedSubscriptionKey.API_LEVEL.value: API_LEVEL,
            CachedSubscriptionKey.IS_VALID.value: True,
        }],
    }


def _concurrent_entry() -> dict[str, Any]:
    """The entry the concurrent request caches - the same user, already digested, stamped with its own api key"""
    entry: dict[str, Any] = _portal_answer()
    entry[CachedUserKey.PASSWORD.value] = _hmac(PASSWORD)
    entry[CachedUserKey.SUBSCRIPTIONS.value][0][CachedSubscriptionKey.API_KEY.value] = OTHER_API_KEY

    return entry


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


def _portal_caching_concurrently_on(call: int, manager: CachedUserManager) -> Callable[..., dict[str, Any]]:
    """A portal stub that lets the concurrent request cache the user just before answering its ``call``-th call"""
    calls: list[int] = []

    def _answer(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(call)

        if len(calls) == call:
            manager.insert_cached_user(copy.deepcopy(_concurrent_entry()))

        return _portal_answer()

    return _answer


def _check(manager: CachedUserManager, database_manager: MongoDatabaseManager,
           portal: Callable[..., dict[str, Any]], api_key: str | None) -> dict[str, Any] | None:
    """Runs the portal check in hosted cloud mode - with an api key the x-api-key channel, without one the login"""
    with patch.object(cuh, 'get_cached_user_manager', return_value=manager), \
         patch.object(cuh, 'SecurityManager', _StubSecurityManager), \
         patch.object(cuh, 'check_db_exists', return_value=True), \
         patch.object(cuh, 'validate_subscription_user', side_effect=portal):
        with stub_cmdb_app(cloud_mode=True, database_manager=database_manager).test_request_context():
            return cuh.check_user_in_service_portal(EMAIL, PASSWORD, api_key, api_key_required=api_key is not None)


def test_the_api_channel_refreshes_an_entry_a_concurrent_request_cached(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, cache_collection: Any) -> None:
    """The user is served and keeps one entry, stamped with this request's api key"""
    portal = _portal_caching_concurrently_on(FULL_LIST_CALL, cached_user_manager)

    assert _check(cached_user_manager, database_manager, portal, API_KEY) is not None

    entries: list[dict[str, Any]] = list(cache_collection.find({CachedUserKey.EMAIL.value: EMAIL}))
    assert len(entries) == 1
    assert entries[0][CachedUserKey.PASSWORD.value] == _hmac(PASSWORD)
    assert entries[0][CachedUserKey.SUBSCRIPTIONS.value][0][CachedSubscriptionKey.API_KEY.value] == API_KEY


def test_the_login_refreshes_an_entry_a_concurrent_request_cached(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, cache_collection: Any) -> None:
    """The user is served and keeps one entry, holding the fresh portal data"""
    portal = _portal_caching_concurrently_on(FIRST_CALL, cached_user_manager)

    assert _check(cached_user_manager, database_manager, portal, None) is not None

    entries: list[dict[str, Any]] = list(cache_collection.find({CachedUserKey.EMAIL.value: EMAIL}))
    assert len(entries) == 1
    assert entries[0][CachedUserKey.PASSWORD.value] == _hmac(PASSWORD)
    assert CachedSubscriptionKey.API_KEY.value not in entries[0][CachedUserKey.SUBSCRIPTIONS.value][0]


def test_the_next_api_request_is_served_from_the_cache(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, cache_collection: Any) -> None:
    """The refreshed entry validates: the follow-up request asks the portal nothing"""
    del cache_collection  # the fixture only has to have run
    _check(cached_user_manager, database_manager,
           _portal_caching_concurrently_on(FULL_LIST_CALL, cached_user_manager), API_KEY)

    portal: MagicMock = MagicMock(return_value=_portal_answer())
    assert _check(cached_user_manager, database_manager, portal, API_KEY) is not None

    portal.assert_not_called()
