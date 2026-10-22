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
Unit tests for cmdb.interface.cloud_user_helper

The cloud user: the Service Portal check with its user-cache sync, the local-mode test users, the tenant database
helpers, the subscription admin and the portal's subscription validation. Every test drives a helper inside a
BaseCmdbApp ``test_request_context`` (``stub_cmdb_app``) with the managers, ``requests`` and ``os.getenv`` patched at
the module path - no Mongo, no service-portal HTTP. Also pinned: the module defines exactly its listed functions and
never imports ``route_utils``, which imports it
"""
# pylint: disable=protected-access  # these tests intentionally exercise module-private helpers
import ast
import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch, mock_open

import pytest

import cmdb.interface.cloud_user_helper as cuh
import cmdb.interface.route_utils as ru
from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.manager.manager_provider_model.manager_provider import MANAGER_CLASSES
from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.security import (
    InvalidCloudUserError,
    NoAccessTokenError,
    MissingApiKeyError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError, UsersManagerUpdateError
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.cloud_user_helper'

TYPED_EMAIL: str = ' User@Test.COM '
NORMALISED_EMAIL: str = 'user@test.com'


# Everything the module defines - what the login, verify_api_access, the /setup and the OpenCelium routes call, and
# the cache-sync steps behind the portal check
CLOUD_USER_FUNCTIONS: frozenset[str] = frozenset({
    'get_cached_user_manager', 'check_user_in_service_portal', '_load_local_test_user', '_sync_api_cached_user',
    '_cached_password_is_current', '_sync_frontend_cached_user', 'check_db_exists', 'init_db_routine',
    'set_admin_user', 'retrieve_user', 'validate_subscription_user',
})
# What route_utils.verify_api_access reads through route_utils - the one binding of these names there
VERIFY_API_ACCESS_READS: frozenset[str] = frozenset({'check_user_in_service_portal', 'set_admin_user', 'retrieve_user'})


def _portal_env(key: str) -> str:
    """Stand-in for os.getenv covering the service-portal env vars used by validate_subscription_user."""
    return 'token' if key == 'X-ACCESS-TOKEN' else 'http://sp'


class TestGetCachedUserManager:
    """
    The one place the cloud user-cache manager is built

    Eighteen call sites wrote `CachedUserManager(current_app.database_manager)` by hand. What the
    helper records is WHY it is not `ManagerProvider.get_manager`: the cache never lives in a tenant
    database, and the login path has no authenticated user to resolve one with.
    """

    def test_it_builds_the_manager_from_the_app_database_handle(self) -> None:
        """The process' own handle - there is no per-request or per-tenant choice to make here."""
        app = stub_cmdb_app()

        with app.test_request_context(), patch(f'{MODULE_PATH}.CachedUserManager') as manager_cls:
            built = cuh.get_cached_user_manager()

        manager_cls.assert_called_once_with(app.database_manager)
        assert built is manager_cls.return_value

    def test_it_takes_no_request_user(self) -> None:
        """
        It cannot: the login path calls this before anyone is authenticated

        That is the reason the cache manager is built directly instead of through ManagerProvider,
        whose cloud-mode path requires a request_user.
        """
        assert not inspect.signature(cuh.get_cached_user_manager).parameters

    def test_the_manager_type_registry_does_not_offer_it(self) -> None:
        """
        `ManagerType` deliberately carries no CACHED_USER entry any more

        It was registered and used by nobody: `CachedUserManager` ignores the database argument
        `ManagerProvider` would pass it, so resolving it there would look tenant-aware and not be.
        """
        assert not hasattr(ManagerType, 'CACHED_USER')
        assert cuh.CachedUserManager not in MANAGER_CLASSES.values()


# ============================================ check_user_in_service_portal ========================================== #

class TestCheckUserInServicePortal:
    """``check_user_in_service_portal`` validates users locally or via the portal + cache."""

    def test_local_mode_delegates_to_local_loader(self) -> None:
        """In local mode the local test-user loader is used, and its plaintext password comes back as its HMAC"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value={'email': 'x', 'password': 'p'}) as loader, \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            security_manager.return_value.generate_hmac.side_effect = lambda plain: f'hmac({plain})'
            with stub_cmdb_app(local_mode=True).test_request_context():
                assert cuh.check_user_in_service_portal('x', 'p') == {'email': 'x', 'password': 'hmac(p)'}
        loader.assert_called_once_with('x', 'p')

    def test_local_mode_refusal_stays_none(self) -> None:
        """Nothing to hash when the fixture refuses"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value=None), \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            with stub_cmdb_app(local_mode=True).test_request_context():
                assert cuh.check_user_in_service_portal('x', 'p') is None
        security_manager.return_value.generate_hmac.assert_not_called()

    def test_the_email_is_normalised_before_the_local_loader(self) -> None:
        """Stripped and lower-cased, whatever the caller submitted"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value=None) as loader:
            with stub_cmdb_app(local_mode=True).test_request_context():
                cuh.check_user_in_service_portal(TYPED_EMAIL, 'p')
        loader.assert_called_once_with(NORMALISED_EMAIL, 'p')

    def test_the_cache_and_the_portal_see_the_normalised_email(self) -> None:
        """One address is one cache entry - the unique cache index compares case-sensitively"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value={}) as portal:
            with stub_cmdb_app(local_mode=False).test_request_context():
                cuh.check_user_in_service_portal(TYPED_EMAIL, 'p', 'key', api_key_required=True)
        cached_mgr.cached_user_exists.assert_called_once_with(NORMALISED_EMAIL)
        portal.assert_called_once_with(NORMALISED_EMAIL, 'p', 'key', True)

    def test_api_key_required_without_key_returns_none(self) -> None:
        """When an API key is required but absent, None is returned early."""
        with patch(f'{MODULE_PATH}.CachedUserManager'), patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app(local_mode=False).test_request_context():
                assert cuh.check_user_in_service_portal('x', 'p', None, api_key_required=True) is None

    def test_cache_hit_returns_cached_user(self) -> None:
        """A validated cached user is returned without hitting the portal."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = True
        cached_mgr.get_validated_user_data.return_value = {'email': 'x', 'cached': True}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user') as portal:
            with stub_cmdb_app(local_mode=False).test_request_context():
                assert cuh.check_user_in_service_portal('x', 'p') == {'email': 'x', 'cached': True}
        portal.assert_not_called()

    def test_cache_hit_invalid_falls_through_to_portal(self) -> None:
        """A cached-but-invalid user falls through to portal validation."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = True
        cached_mgr.get_validated_user_data.return_value = None
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': []}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user) as portal, \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user'):
            with stub_cmdb_app(local_mode=False).test_request_context():
                cuh.check_user_in_service_portal('x', 'p')
        portal.assert_called_once()

    def test_empty_portal_result_skips_sync(self) -> None:
        """When the portal returns no user, no cache sync happens and the falsy value is returned."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=None), \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user') as sync_fe:
            with stub_cmdb_app(local_mode=False).test_request_context():
                assert cuh.check_user_in_service_portal('x', 'p') is None
        sync_fe.assert_not_called()

    def test_cache_miss_validates_and_syncs_frontend(self) -> None:
        """A cache miss validates against the portal and syncs the frontend cache."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': []}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user), \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user') as sync_fe:
            with stub_cmdb_app(local_mode=False).test_request_context():
                result = cuh.check_user_in_service_portal('x', 'p')
        assert result['password'] == 'hmac'
        sync_fe.assert_called_once()

    def test_cache_miss_with_api_key_syncs_api(self) -> None:
        """A cache miss on an API login syncs the API cache instead."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user), \
             patch(f'{MODULE_PATH}._sync_api_cached_user') as sync_api:
            with stub_cmdb_app(local_mode=False).test_request_context():
                cuh.check_user_in_service_portal('x', 'p', 'the-key', api_key_required=True)
        sync_api.assert_called_once()

    def test_known_error_is_reraised(self) -> None:
        """A recognised portal error propagates unchanged - the same object, not made its own cause"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        refusal = InvalidCloudUserError('no')
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', side_effect=refusal):
            with stub_cmdb_app(local_mode=False).test_request_context():
                with pytest.raises(InvalidCloudUserError) as exc_info:
                    cuh.check_user_in_service_portal('x', 'p')

        assert exc_info.value is refusal
        assert exc_info.value.__cause__ is not refusal

    @pytest.mark.parametrize('failure', [
        RuntimeError('boom'),
        DatabaseConnectionError('cache down'),
        ValueError("No symmetric AES key provided via the 'DG_SYMMETRIC_KEY' environment variable"),
    ], ids=['bug', 'cache-read', 'missing-key'])
    def test_any_other_error_propagates_as_itself(self, failure: Exception) -> None:
        """Not wrapped in a bare Exception, so the caller's own arms (cloud_login's DatabaseConnectionError) match it"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.side_effect = failure
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app(local_mode=False).test_request_context():
                with pytest.raises(type(failure)) as exc_info:
                    cuh.check_user_in_service_portal('x', 'p')

        assert exc_info.value is failure


# ================================================ _load_local_test_user ============================================= #

class TestLoadLocalTestUser:
    """``_load_local_test_user`` matches credentials against the local JSON fixture."""

    def test_matching_user_returned(self) -> None:
        """A known email with the right password returns the user."""
        users = {'x@test.com': {'password': 'secret', 'user_name': 'x'}}
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value=users):
            assert cuh._load_local_test_user('x@test.com', 'secret') == users['x@test.com']

    def test_wrong_password_returns_none(self) -> None:
        """A known email with the wrong password returns None."""
        users = {'x@test.com': {'password': 'secret'}}
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value=users):
            assert cuh._load_local_test_user('x@test.com', 'wrong') is None

    def test_unknown_user_returns_none(self) -> None:
        """An unknown email returns None."""
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value={}):
            assert cuh._load_local_test_user('nobody@test.com', 'x') is None

    def test_file_error_returns_none(self) -> None:
        """A failure reading the fixture returns None."""
        with patch('builtins.open', side_effect=OSError('missing')):
            assert cuh._load_local_test_user('x@test.com', 'x') is None


# ================================================ _sync_api_cached_user ============================================= #

class TestSyncApiCachedUser:
    """``_sync_api_cached_user`` maintains the cache for an external-API login."""

    @staticmethod
    def _security_mgr() -> MagicMock:
        """A SecurityManager stub whose generate_hmac maps any password to a fixed digest."""
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hashed-pw'
        return security_mgr

    def test_existing_valid_user_stamps_api_key(self) -> None:
        """A cached user whose password is the current HMAC just gets the api_key stamped."""
        cached_mgr = MagicMock()
        # Stored password already equals generate_hmac(...) -> entry is current
        cached_mgr.get_cached_user.return_value = {'password': 'hashed-pw', 'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        cuh._sync_api_cached_user(
            cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=True
        )
        cached_mgr.update_cached_user_api_key.assert_called_once_with('x', 'db', 'the-key')
        cached_mgr.delete_cached_user.assert_not_called()
        cached_mgr.insert_cached_user.assert_not_called()

    def test_existing_stale_password_user_is_healed(self) -> None:
        """Self-heal: a cached entry with a stale (e.g. legacy plaintext) password is dropped and rebuilt.

        The old bug stored the password in plaintext, so the cache never validated and every request hit
        the portal. Such an entry must now be deleted and recreated with a correctly hashed password.
        """
        cached_mgr = MagicMock()
        # Stored plaintext password != generate_hmac(...) -> entry is stale
        cached_mgr.get_cached_user.return_value = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            cuh._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=True
            )
        cached_mgr.delete_cached_user.assert_called_once_with('x')
        cached_mgr.update_cached_user_api_key.assert_not_called()
        cached = cached_mgr.insert_cached_user.call_args.args[0]
        assert cached['password'] == 'hashed-pw'
        assert cached['subscriptions'][0]['api_key'] == 'the-key'

    def test_uncached_user_without_db_does_nothing(self) -> None:
        """An uncached user whose database does not exist is not created."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=False):
            cuh._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_not_called()

    def test_uncached_user_with_db_inserts_full_data(self) -> None:
        """An uncached user with an existing db is cached from the full subscription list."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'plain', 'subscriptions': [{'database': 'db'}, {'database': 'other'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            cuh._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_called_once_with(full)
        assert full['subscriptions'][0]['api_key'] == 'the-key'

    def test_uncached_user_password_is_hashed_before_caching(self) -> None:
        """Regression: the cached password is the HMAC, not the plaintext the portal returns.

        The plaintext bug meant the cache never validated (the check hashes the login password), so
        every API request fell back to the service portal despite the user being 'cached'.
        """
        cached_mgr = MagicMock()
        security_mgr = self._security_mgr()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            cuh._sync_api_cached_user(
                cached_mgr, security_mgr, 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        security_mgr.generate_hmac.assert_called_once_with('Init1234!')
        cached = cached_mgr.insert_cached_user.call_args.args[0]
        assert cached['password'] == 'hashed-pw'

    def test_uncached_user_empty_full_refetch_does_not_insert(self) -> None:
        """When the full-subscription re-fetch returns nothing, no cache entry is created."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=None):
            cuh._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_not_called()

    def test_uncached_user_with_db_no_matching_subscription(self) -> None:
        """A full list with no subscription matching the target db still caches (no api_key stamped)."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'plain', 'subscriptions': [{'database': 'other'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            cuh._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_called_once_with(full)
        assert 'api_key' not in full['subscriptions'][0]


# ============================================ _cached_password_is_current =========================================== #

class TestCachedPasswordIsCurrent:
    """``_cached_password_is_current`` compares the stored password to the HMAC of the login password."""

    @staticmethod
    def _security_mgr() -> MagicMock:
        """A SecurityManager stub whose generate_hmac maps any password to a fixed digest."""
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hashed-pw'
        return security_mgr

    def test_matching_hash_is_current(self) -> None:
        """A stored password equal to the HMAC of the login password is current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'password': 'hashed-pw'}
        assert cuh._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is True

    def test_plaintext_password_is_not_current(self) -> None:
        """A stored plaintext password (legacy entry) is not current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'password': 'Init1234!'}
        assert cuh._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is False

    def test_absent_cached_user_is_not_current(self) -> None:
        """A missing cached entry is not current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = None
        assert cuh._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is False


# =============================================== _sync_frontend_cached_user ========================================= #

class TestSyncFrontendCachedUser:
    """``_sync_frontend_cached_user`` maintains the cache for a frontend login."""

    def test_new_user_inserted(self) -> None:
        """An uncached user is inserted as-is."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': []}
        cuh._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=False)
        cached_mgr.insert_cached_user.assert_called_once_with(user_data)

    def test_missing_cached_user_returns_early(self) -> None:
        """A user flagged cached but absent from the store is not updated."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = None
        cuh._sync_frontend_cached_user(cached_mgr, 'x', {'subscriptions': []}, user_exists_in_cache=True)
        cached_mgr.update_cached_user.assert_not_called()

    def test_existing_user_restores_api_key(self) -> None:
        """A refreshed cached user keeps its previously stored api_key per database."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'subscriptions': [{'database': 'db', 'api_key': 'old-key'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        cuh._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=True)
        assert user_data['subscriptions'][0]['api_key'] == 'old-key'
        cached_mgr.update_cached_user.assert_called_once_with('x', user_data)

    def test_existing_user_without_prior_api_key(self) -> None:
        """A refreshed user whose db had no cached api_key is updated with no key stamped."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        cuh._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=True)
        assert 'api_key' not in user_data['subscriptions'][0]
        cached_mgr.update_cached_user.assert_called_once_with('x', user_data)


# ============================================= small database/user helpers ========================================== #

class TestSmallHelpers:
    """The thin DB/user helpers around the managers."""

    def test_check_db_exists_delegates(self) -> None:
        """check_db_exists forwards to the database manager."""
        app = stub_cmdb_app()
        app.database_manager.check_database_exists.return_value = True
        with app.test_request_context():
            assert cuh.check_db_exists('db') is True
        app.database_manager.check_database_exists.assert_called_once_with('db')

    def test_init_db_routine_validates_and_sets_version(self) -> None:
        """init_db_routine validates collections and sets the newest update version."""
        validator = MagicMock()
        updater = MagicMock()
        updater.get_highest_update_version.return_value = 99
        with patch(f'{MODULE_PATH}.CollectionValidator', return_value=validator), \
             patch(f'{MODULE_PATH}.DatabaseUpdater', return_value=updater):
            with stub_cmdb_app().test_request_context():
                cuh.init_db_routine('db')
        validator.validate_collections.assert_called_once()
        updater.set_update_version.assert_called_once_with(99)

    def test_retrieve_user_returns_user(self) -> None:
        """retrieve_user returns the user found by email."""
        users_manager = MagicMock()
        user = SimpleNamespace(public_id=1)
        users_manager.get_user_by.return_value = user
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with stub_cmdb_app().test_request_context():
                assert cuh.retrieve_user({'email': 'x'}, 'db') is user

    def test_retrieve_user_lets_a_failed_read_through(self) -> None:
        """A read that fails is the server's fault, not "no such user" - the callers answer 500"""
        users_manager = MagicMock()
        users_manager.get_user_by.side_effect = UsersManagerGetError('nope')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(UsersManagerGetError):
                    cuh.retrieve_user({'email': 'x'}, 'db')

    def test_retrieve_user_answers_none_for_no_such_user(self) -> None:
        """Absence stays None"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with stub_cmdb_app().test_request_context():
                assert cuh.retrieve_user({'email': 'x'}, 'db') is None


# =================================================== set_admin_user ================================================= #

class TestSetAdminUser:
    """``set_admin_user`` creates or updates the admin user for a subscription's database."""

    SUBSCRIPTION: dict[str, Any] = {'database': 'db', 'api_level': 1, 'config_item_limit': 10}
    USER_DATA: dict[str, Any] = {'email': 'a@test.com', 'user_name': 'admin', 'password': 'pw'}

    def test_creates_when_absent(self) -> None:
        """A missing admin user is created."""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)
        users_manager.insert_user.assert_called_once()

    # Every value distinct, so a key read from the wrong side (user vs subscription) or swapped shows
    DISTINCT_SUBSCRIPTION: dict[str, Any] = {'database': 'tenant-db', 'api_level': 3, 'config_item_limit': 70}
    DISTINCT_USER_DATA: dict[str, Any] = {'email': 'owner@test.com', 'user_name': 'owner-name', 'password': 'digest'}
    NEXT_PUBLIC_ID: int = 41

    def test_a_created_user_carries_each_value_from_its_own_key(self) -> None:
        """Every field of the new admin comes from the portal key it belongs to; the group is the admin group"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = self.NEXT_PUBLIC_ID
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager) as manager_class:
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.DISTINCT_USER_DATA, self.DISTINCT_SUBSCRIPTION)

        created = users_manager.insert_user.call_args.args[0]
        assert manager_class.call_args.args[1] == self.DISTINCT_SUBSCRIPTION['database']
        assert (created.public_id, created.user_name, created.email, created.password) == (
            self.NEXT_PUBLIC_ID, self.DISTINCT_USER_DATA['user_name'], self.DISTINCT_USER_DATA['email'],
            self.DISTINCT_USER_DATA['password'],
        )
        assert (created.database, created.api_level, created.config_items_limit) == (
            self.DISTINCT_SUBSCRIPTION['database'], self.DISTINCT_SUBSCRIPTION['api_level'],
            self.DISTINCT_SUBSCRIPTION['config_item_limit'],
        )
        assert created.group_id == ADMIN_GROUP_ID
        assert created.active is True
        assert created.registration_time is not None

    def test_an_updated_user_takes_each_subscription_value_from_its_own_key(self) -> None:
        """database, api_level and config_items_limit each from their own subscription key"""
        users_manager = MagicMock()
        existing = MagicMock()
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.DISTINCT_USER_DATA, self.DISTINCT_SUBSCRIPTION)

        assert (existing.database, existing.api_level, existing.config_items_limit) == (
            self.DISTINCT_SUBSCRIPTION['database'], self.DISTINCT_SUBSCRIPTION['api_level'],
            self.DISTINCT_SUBSCRIPTION['config_item_limit'],
        )
        users_manager.get_user_by.assert_called_once_with({'email': self.DISTINCT_USER_DATA['email']})

    def test_updates_when_present(self) -> None:
        """An existing admin user is updated with the subscription's fields."""
        users_manager = MagicMock()
        existing = MagicMock()
        existing.get_public_id.return_value = 1
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)
        users_manager.update_user.assert_called_once()
        assert existing.database == 'db'

    def test_a_created_user_stores_the_digest_it_is_handed(self) -> None:
        """The portal check already HMACed the password; hashing it again stored a digest nothing could match"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

        assert users_manager.insert_user.call_args.args[0].password == self.USER_DATA['password']
        security_manager.return_value.generate_hmac.assert_not_called()

    def test_an_update_leaves_the_stored_password_alone(self) -> None:
        """Only the subscription's three fields are refreshed"""
        users_manager = MagicMock()
        existing = MagicMock(password='stored-digest')
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

        assert existing.password == 'stored-digest'

    # The portal's numbers as strings: both branches have to convert them to int
    STRING_SUBSCRIPTION: dict[str, Any] = {'database': 'db', 'api_level': '1', 'config_item_limit': '10'}

    def test_the_update_path_stores_integers_for_string_numbers(self) -> None:
        """An updated user carries int api_level / config_items_limit, so the limit check can compare"""
        users_manager = MagicMock()
        existing = MagicMock()
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.STRING_SUBSCRIPTION)

        assert existing.config_items_limit == self.SUBSCRIPTION['config_item_limit']
        assert existing.api_level == self.SUBSCRIPTION['api_level']
        assert isinstance(existing.config_items_limit, int)

    def test_the_create_path_stores_integers_for_string_numbers(self) -> None:
        """The created user gets the same types the update path writes"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(self.USER_DATA, self.STRING_SUBSCRIPTION)

        created = users_manager.insert_user.call_args.args[0]
        assert created.config_items_limit == self.SUBSCRIPTION['config_item_limit']
        assert created.api_level == self.SUBSCRIPTION['api_level']

    def test_a_non_numeric_limit_is_refused_before_any_write(self) -> None:
        """The conversion runs before either branch, so a bad value writes nothing and names the failure"""
        users_manager = MagicMock()
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(UsersManagerInsertError):
                    cuh.set_admin_user(self.USER_DATA, {**self.SUBSCRIPTION, 'config_item_limit': 'lots'})

        users_manager.insert_user.assert_not_called()
        users_manager.update_user.assert_not_called()

    def _run(self, users_manager: MagicMock, subscription: dict[str, Any] | None = None,
             user_data: dict[str, Any] | None = None) -> None:
        """Runs set_admin_user against `users_manager`"""
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                cuh.set_admin_user(user_data or self.USER_DATA, subscription or self.SUBSCRIPTION)

    def test_a_failed_read_is_not_absence_and_creates_nothing(self) -> None:
        """Reading the failure as "no such user" stored a second admin with the same email"""
        users_manager = MagicMock()
        users_manager.get_user_by.side_effect = UsersManagerGetError('nope')

        with pytest.raises(UsersManagerGetError):
            self._run(users_manager)

        users_manager.insert_user.assert_not_called()
        users_manager.update_user.assert_not_called()

    @pytest.mark.parametrize('outage', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked')],
                             ids=['network', 'lock'])
    @pytest.mark.parametrize('step', ['get_user_by', 'insert_user'], ids=['read', 'write'])
    def test_an_outage_passes_through_as_itself(self, outage: Exception, step: str) -> None:
        """Not hidden behind the insert error - the app answers 503 / 423"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        getattr(users_manager, step).side_effect = outage

        with pytest.raises(type(outage)):
            self._run(users_manager)

    @pytest.mark.parametrize('subscription', [
        {'database': 'db', 'api_level': 'high', 'config_item_limit': 10},
        {'database': 'db', 'api_level': 1, 'config_item_limit': None},
        {'database': 'db', 'api_level': 1},
    ], ids=['level-not-a-number', 'limit-none', 'limit-missing'])
    def test_an_unusable_subscription_is_the_insert_error(self, subscription: dict[str, Any]) -> None:
        """Before anything is read or written"""
        users_manager = MagicMock()

        with pytest.raises(UsersManagerInsertError):
            self._run(users_manager, subscription=subscription)

        users_manager.get_user_by.assert_not_called()

    def test_portal_data_without_a_user_name_is_the_insert_error(self) -> None:
        """The created user needs one"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1

        with pytest.raises(UsersManagerInsertError):
            self._run(users_manager, user_data={'email': 'a@test.com', 'password': 'pw'})

    def test_a_failed_update_is_the_insert_error(self) -> None:
        """Both halves of the write answer the same"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = MagicMock()
        users_manager.update_user.side_effect = UsersManagerUpdateError('down')

        with pytest.raises(UsersManagerInsertError):
            self._run(users_manager)

    def test_a_bug_is_not_wrapped(self) -> None:
        """A programming error reaches the app as itself"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            self._run(users_manager)

    def test_insert_get_error_reraised(self) -> None:
        """A UsersManagerGetError raised while writing propagates as UsersManagerGetError."""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        users_manager.insert_user.side_effect = UsersManagerGetError('boom')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(UsersManagerGetError):
                    cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

    def test_insert_failure_raises_insert_error(self) -> None:
        """A counter that cannot be read is the insert error"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.side_effect = BaseManagerGetError('boom')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(UsersManagerInsertError):
                    cuh.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)


# =============================================== validate_subscription_user ========================================= #

class TestValidateSubscriptionUser:
    """``validate_subscription_user`` posts credentials to the DataGerry service portal."""

    def test_missing_api_key_raises(self) -> None:
        """A required-but-absent API key raises MissingApiKeyError."""
        with stub_cmdb_app().test_request_context():
            with pytest.raises(MissingApiKeyError):
                cuh.validate_subscription_user('x', 'p', None, api_key_required=True)

    def test_missing_access_token_raises(self) -> None:
        """A missing X-ACCESS-TOKEN env var raises NoAccessTokenError."""
        with patch(f'{MODULE_PATH}.os.getenv', return_value=None):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(NoAccessTokenError):
                    cuh.validate_subscription_user('x', 'p')

    def test_success_returns_json(self) -> None:
        """A 200 response returns the parsed JSON body."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'email': 'x'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with stub_cmdb_app().test_request_context():
                assert cuh.validate_subscription_user('x', 'p') == {'email': 'x'}

    def test_api_key_uses_subscription_endpoint(self) -> None:
        """When an API key is supplied the subscription endpoint is targeted."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'email': 'x'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response) as post:
            with stub_cmdb_app().test_request_context():
                cuh.validate_subscription_user('x', 'p', 'the-key')
        assert post.call_args.args[0] == 'http://sp/datagerry/auth/subscription'

    def test_non_200_raises_invalid_cloud_user(self) -> None:
        """A non-200 response raises InvalidCloudUserError with the portal message."""
        response = MagicMock()
        response.status_code = 401
        response.json.return_value = {'message': 'nope'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(InvalidCloudUserError):
                    cuh.validate_subscription_user('x', 'p')

    def test_non_200_non_json_falls_back_to_text(self) -> None:
        """A non-JSON error body falls back to the raw text."""
        response = MagicMock()
        response.status_code = 500
        response.json.side_effect = ValueError('not json')
        response.text = 'server error'
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(InvalidCloudUserError):
                    cuh.validate_subscription_user('x', 'p')

    def test_timeout_raises_request_timeout(self) -> None:
        """A request timeout raises RequestTimeoutError, carrying the timeout itself."""
        failure = cuh.requests.exceptions.Timeout('slow')

        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=failure):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(RequestTimeoutError) as caught:
                    cuh.validate_subscription_user('x', 'p')

        assert caught.value.args[0] is failure

    def test_request_exception_raises_request_error(self) -> None:
        """A generic request exception raises RequestError, carrying the exception itself."""
        failure = cuh.requests.exceptions.RequestException('down')

        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=failure):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(RequestError) as caught:
                    cuh.validate_subscription_user('x', 'p')

        assert caught.value.args[0] is failure


# ================================================= the module's place =============================================== #

class TestTheModulesPlace:
    """What lives here, and the one direction the import runs"""

    def test_the_module_defines_exactly_its_listed_functions(self) -> None:
        """Nothing a caller imports went missing, nothing new appeared unnoticed"""
        defined: set[str] = {
            name for name, member in vars(cuh).items()
            if inspect.isfunction(member) and member.__module__ == cuh.__name__
        }

        assert defined == CLOUD_USER_FUNCTIONS

    def test_it_never_imports_route_utils(self) -> None:
        """route_utils imports this module for verify_api_access, so the reverse would be a cycle"""
        tree = ast.parse(inspect.getsource(cuh))
        imported: set[str] = {
            node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

        assert not any('route_utils' in module for module in imported)

    def test_route_utils_holds_only_what_verify_api_access_reads(self) -> None:
        """
        No re-export: of this module's functions, route_utils binds exactly the three verify_api_access calls -
        a test patching one of them there patches what that decorator reads
        """
        bound: set[str] = {name for name in CLOUD_USER_FUNCTIONS if getattr(ru, name, None) is getattr(cuh, name)}

        assert bound == VERIFY_API_ACCESS_READS
