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
Unit tests for cmdb.manager.system_manager.cached_user_manager.CachedUserManager

DB-free: the manager is never constructed (its __init__ builds a DgServicePortalManager); each
method is invoked unbound on a MagicMock-typed ``self`` so the collaborators (self.dbm,
self.dg_sp_manager and sibling methods) are stubbed. Covers the pure subscription/OpenCelium
helpers, the credential validation, and the CRUD delegations incl. their guard/error branches
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.open_celium import CachedOcIdType
from cmdb.errors.open_celium import OcNoSubError, OcMasterPwNotSetError
# -------------------------------------------------------------------------------------------------------------------- #

EMAIL: str = 'user@acme.com'
DB_NAME: str = 'db_acme'


def _cached_user(**overrides: Any) -> dict[str, Any]:
    """Builds a minimal cached-user dict; overrides replace top-level keys."""
    user: dict[str, Any] = {
        'email': EMAIL,
        'password': 'secret',
        'subscriptions': [{'database': DB_NAME, 'api_key': 'k1', 'is_valid': True}],
    }
    user.update(overrides)
    return user


# -------------------------------------------------------------------------------------------------------------------- #
#                                               get_sub_by_db_name                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_sub_by_db_name_returns_matching_subscription() -> None:
    """The subscription whose database matches is returned."""
    target = {'database': DB_NAME}
    user = {'subscriptions': [{'database': 'other'}, target]}

    assert CachedUserManager.get_sub_by_db_name(MagicMock(), user, DB_NAME) is target


def test_get_sub_by_db_name_returns_none_when_no_match() -> None:
    """No subscription for the database yields None."""
    user = {'subscriptions': [{'database': 'other'}]}

    assert CachedUserManager.get_sub_by_db_name(MagicMock(), user, DB_NAME) is None


def test_get_sub_by_db_name_tolerates_missing_subscriptions() -> None:
    """A cached user without a 'subscriptions' key yields None instead of raising."""
    assert CachedUserManager.get_sub_by_db_name(MagicMock(), {}, DB_NAME) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_oc_ids                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_oc_ids_returns_none_when_subscription_missing() -> None:
    """No matching subscription → None."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = None

    assert CachedUserManager.get_oc_ids(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS) is None


def test_get_oc_ids_returns_none_when_no_opencelium_block() -> None:
    """A subscription without an 'opencelium' block → None."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = {'database': DB_NAME}

    assert CachedUserManager.get_oc_ids(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS) is None


def test_get_oc_ids_returns_empty_list_when_key_absent() -> None:
    """An opencelium block without the requested id list → empty list (not None)."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = {'opencelium': {'connections': ['1']}}

    assert CachedUserManager.get_oc_ids(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS) == []


def test_get_oc_ids_parses_ints_and_skips_bad_values() -> None:
    """String ids are coerced to int; unparseable entries are dropped."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = {'opencelium': {'schedules': ['1', 'x', '3']}}

    assert CachedUserManager.get_oc_ids(mock_self, {}, DB_NAME, CachedOcIdType.SCHEDULERS) == [1, 3]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   oc_id_exists                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_oc_id_exists_false_when_ids_none() -> None:
    """A missing subscription (get_oc_ids None) → False."""
    mock_self = MagicMock()
    mock_self.get_oc_ids.return_value = None

    assert CachedUserManager.oc_id_exists(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS, 5) is False


def test_oc_id_exists_reflects_membership() -> None:
    """The id is looked up in the resolved list."""
    mock_self = MagicMock()
    mock_self.get_oc_ids.return_value = [1, 2, 3]

    assert CachedUserManager.oc_id_exists(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS, 2) is True
    assert CachedUserManager.oc_id_exists(mock_self, {}, DB_NAME, CachedOcIdType.CONNECTORS, 9) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                          master-password helpers                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_master_pw_from_cached_raises_when_no_subscription() -> None:
    """No subscription for the database → OcNoSubError."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = None

    with pytest.raises(OcNoSubError):
        CachedUserManager.get_master_pw_from_cached(mock_self, _cached_user(), DB_NAME)


def test_get_master_pw_from_cached_clears_cache_and_raises_when_password_missing() -> None:
    """A subscription without a master password drops the cached user and raises OcMasterPwNotSetError."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = {'database': DB_NAME}

    with pytest.raises(OcMasterPwNotSetError):
        CachedUserManager.get_master_pw_from_cached(mock_self, _cached_user(), DB_NAME)

    mock_self.delete_cached_user.assert_called_once_with(EMAIL)


def test_get_master_pw_from_cached_returns_password() -> None:
    """The master password of the matching subscription is returned."""
    mock_self = MagicMock()
    mock_self.get_sub_by_db_name.return_value = {'masterPassword': 'topsecret'}

    assert CachedUserManager.get_master_pw_from_cached(mock_self, _cached_user(), DB_NAME) == 'topsecret'


def test_check_cached_master_password_compares_against_cached() -> None:
    """The cached master password is compared against the supplied one."""
    mock_self = MagicMock()
    mock_self.get_master_pw_from_cached.return_value = 'topsecret'

    assert CachedUserManager.check_cached_master_password(mock_self, _cached_user(), DB_NAME, 'topsecret') is True
    assert CachedUserManager.check_cached_master_password(mock_self, _cached_user(), DB_NAME, 'wrong') is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_validated_user_data                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_validated_user_data_requires_api_key_when_flagged() -> None:
    """api_key_required with no api_key short-circuits to None without a cache lookup."""
    mock_self = MagicMock()

    assert CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'secret', None, api_key_required=True) is None
    mock_self.get_cached_user.assert_not_called()


def test_get_validated_user_data_none_when_user_unknown() -> None:
    """An unknown cached user yields None."""
    mock_self = MagicMock()
    mock_self.get_cached_user.return_value = None

    assert CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'secret', None) is None


def test_get_validated_user_data_none_on_password_mismatch() -> None:
    """A wrong password yields None."""
    mock_self = MagicMock()
    mock_self.get_cached_user.return_value = _cached_user()

    assert CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'WRONG', None) is None


def test_get_validated_user_data_strips_api_keys_on_success() -> None:
    """A valid password returns the user with every subscription api_key removed."""
    mock_self = MagicMock()
    mock_self.get_cached_user.return_value = _cached_user()

    result = CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'secret', None)

    assert result is not None
    assert all('api_key' not in sub for sub in result['subscriptions'])


def test_get_validated_user_data_keeps_only_matching_valid_subscription() -> None:
    """With an api key required, only the single valid subscription matching it is kept (key stripped)."""
    mock_self = MagicMock()
    mock_self.get_cached_user.return_value = _cached_user(subscriptions=[
        {'database': DB_NAME, 'api_key': 'good', 'is_valid': True},
        {'database': 'other', 'api_key': 'nope', 'is_valid': True},
    ])

    result = CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'secret', 'good', api_key_required=True)

    assert result is not None
    assert len(result['subscriptions']) == 1
    assert result['subscriptions'][0]['database'] == DB_NAME
    assert 'api_key' not in result['subscriptions'][0]


def test_get_validated_user_data_none_when_api_key_has_no_valid_subscription() -> None:
    """An api key that matches no valid subscription yields None."""
    mock_self = MagicMock()
    mock_self.get_cached_user.return_value = _cached_user(subscriptions=[
        {'database': DB_NAME, 'api_key': 'good', 'is_valid': False},
    ])

    result = CachedUserManager.get_validated_user_data(mock_self, EMAIL, 'secret', 'good', api_key_required=True)

    assert result is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              CRUD delegations                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cached_user_exists_reflects_lookup() -> None:
    """cached_user_exists is True when the projection lookup returns a document."""
    mock_self = MagicMock()
    mock_self.dbm.find_one_by.return_value = {'public_id': 1}
    assert CachedUserManager.cached_user_exists(mock_self, EMAIL) is True

    mock_self.dbm.find_one_by.return_value = None
    assert CachedUserManager.cached_user_exists(mock_self, EMAIL) is False


def test_get_cached_user_returns_cache_hit_without_portal_call() -> None:
    """A cache hit is returned directly and the DG Service Portal is not consulted."""
    mock_self = MagicMock()
    doc = _cached_user()
    mock_self.dbm.find_one_by.return_value = doc

    assert CachedUserManager.get_cached_user(mock_self, EMAIL) is doc
    mock_self.dg_sp_manager.get_dg_sp_user_data.assert_not_called()


def test_get_cached_user_seeds_from_portal_on_miss() -> None:
    """On a cache miss the portal data is inserted and the stored document is re-read and returned."""
    mock_self = MagicMock()
    stored = _cached_user()
    mock_self.dbm.find_one_by.side_effect = [None, stored]
    mock_self.dg_sp_manager.get_dg_sp_user_data.return_value = {'email': EMAIL}

    result = CachedUserManager.get_cached_user(mock_self, EMAIL)

    assert result is stored
    mock_self.insert_cached_user.assert_called_once_with({'email': EMAIL})


def test_get_cached_user_returns_none_when_portal_has_no_user() -> None:
    """A miss in both the cache and the portal yields None (no insert)."""
    mock_self = MagicMock()
    mock_self.dbm.find_one_by.return_value = None
    mock_self.dg_sp_manager.get_dg_sp_user_data.return_value = None

    assert CachedUserManager.get_cached_user(mock_self, EMAIL) is None
    mock_self.insert_cached_user.assert_not_called()


def test_insert_cached_user_stamps_creation_time_and_returns_id() -> None:
    """insert_cached_user sets a creation_time and returns the new public_id."""
    mock_self = MagicMock()
    mock_self.insert_item.return_value = 7
    data: dict[str, Any] = {'email': EMAIL}

    result = CachedUserManager.insert_cached_user(mock_self, data)

    assert result == 7
    assert 'creation_time' in data
    mock_self.insert_item.assert_called_once_with(data)


def test_update_cached_user_upserts_with_fresh_creation_time() -> None:
    """update_cached_user refreshes creation_time and upserts by email."""
    mock_self = MagicMock()
    sentinel = MagicMock(name='update_result')
    mock_self.dbm.update.return_value = sentinel
    data: dict[str, Any] = {'password': 'p'}

    result = CachedUserManager.update_cached_user(mock_self, EMAIL, data)

    assert result is sentinel
    assert 'creation_time' in data
    assert mock_self.dbm.update.call_args.kwargs['upsert'] is True


def test_update_cached_user_api_key_requires_api_key() -> None:
    """A missing api key is rejected with ValueError."""
    with pytest.raises(ValueError):
        CachedUserManager.update_cached_user_api_key(MagicMock(), EMAIL, DB_NAME, '')


def test_update_cached_user_api_key_requires_subscription_database() -> None:
    """A missing subscription database is rejected with ValueError."""
    with pytest.raises(ValueError):
        CachedUserManager.update_cached_user_api_key(MagicMock(), EMAIL, '', 'key')


def test_update_cached_user_api_key_raises_when_user_missing() -> None:
    """An unknown cached user is rejected with ValueError."""
    mock_self = MagicMock()
    mock_self.dbm.find_one_by.return_value = None

    with pytest.raises(ValueError):
        CachedUserManager.update_cached_user_api_key(mock_self, EMAIL, DB_NAME, 'key')


def test_update_cached_user_api_key_raises_when_subscription_missing() -> None:
    """A user without the target subscription is rejected with ValueError."""
    mock_self = MagicMock()
    mock_self.dbm.find_one_by.return_value = _cached_user(subscriptions=[{'database': 'other'}])

    with pytest.raises(ValueError):
        CachedUserManager.update_cached_user_api_key(mock_self, EMAIL, DB_NAME, 'key')


def test_update_cached_user_api_key_sets_key_and_persists() -> None:
    """The matching subscription's api_key is set and the user is persisted without upsert."""
    mock_self = MagicMock()
    mock_self.dbm.find_one_by.return_value = _cached_user(
        subscriptions=[{'database': DB_NAME, 'api_key': 'old'}]
    )

    CachedUserManager.update_cached_user_api_key(mock_self, EMAIL, DB_NAME, 'newkey')

    persisted = mock_self.dbm.update.call_args.kwargs['data']
    assert persisted['subscriptions'][0]['api_key'] == 'newkey'
    assert mock_self.dbm.update.call_args.kwargs['upsert'] is False


def test_delete_cached_user_reflects_deleted_count() -> None:
    """delete_cached_user is True only when a document was removed."""
    mock_self = MagicMock()
    mock_self.dbm.delete.return_value = MagicMock(deleted_count=1)
    assert CachedUserManager.delete_cached_user(mock_self, EMAIL) is True

    mock_self.dbm.delete.return_value = MagicMock(deleted_count=0)
    assert CachedUserManager.delete_cached_user(mock_self, EMAIL) is False


def test_delete_multiple_cached_users_reflects_deleted_count() -> None:
    """delete_multiple_cached_users is True when at least one document was removed."""
    mock_self = MagicMock()
    mock_self.dbm.delete_many.return_value = MagicMock(deleted_count=2)
    assert CachedUserManager.delete_multiple_cached_users(mock_self, [EMAIL, 'x@y']) is True

    mock_self.dbm.delete_many.return_value = MagicMock(deleted_count=0)
    assert CachedUserManager.delete_multiple_cached_users(mock_self, [EMAIL]) is False


def test_clear_cache_returns_deleted_count() -> None:
    """clear_cache returns the number of removed cached users."""
    mock_self = MagicMock()
    mock_self.dbm.delete_many.return_value = MagicMock(deleted_count=5)

    assert CachedUserManager.clear_cache(mock_self) == 5
