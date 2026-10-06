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
Unit tests for the cloud user cache's namespace: CmdbCachedUser and its key enums

CmdbCachedUser is a namespace, not a model - the document is the Service Portal's answer, read and written as a dict by
CachedUserManager. What the class supplies is pinned here: the collection, the two indexes the cache database is built
with, and the date field the generic insert turns into a real date. That it builds nothing is pinned too
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_constants import DG_CACHE_DB
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import (
    CACHE_TTL_SECONDS,
    CachedOcIdListKey,
    CachedSubscriptionKey,
    CachedUserKey,
    CmdbCachedUser,
)
from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_TIME_TEXT: str = '2026-10-06T10:00:00+00:00'


def _index(name: str) -> dict:
    """The declared index of that name"""
    return next(index for index in CmdbCachedUser.INDEX_KEYS if index['name'] == name)


def test_the_collection_is_the_cache_collection() -> None:
    """Every read and write of the manager names it"""
    assert CmdbCachedUser.COLLECTION == 'cache.users'


def test_exactly_two_indexes_are_declared() -> None:
    """The unique email index and the TTL index - nothing else is built on the cache"""
    assert sorted(index['name'] for index in CmdbCachedUser.INDEX_KEYS) == sorted(
        [CachedUserKey.EMAIL.value, CachedUserKey.CREATION_TIME.value]
    )


def test_email_is_unique() -> None:
    """One entry per user: the cache is keyed by email"""
    email_index = _index(CachedUserKey.EMAIL.value)

    assert email_index['unique'] is True
    assert email_index['keys'] == [(CachedUserKey.EMAIL.value, CmdbDAO.DAO_ASCENDING)]


def test_creation_time_is_the_ttl_index() -> None:
    """MongoDB removes an entry an hour after it was written"""
    assert _index(CachedUserKey.CREATION_TIME.value)['expireAfterSeconds'] == CACHE_TTL_SECONDS


def test_creation_time_is_the_date_field() -> None:
    """The generic insert turns it into a real date - the TTL index only works on one"""
    assert CmdbCachedUser.DATE_FIELDS == (CachedUserKey.CREATION_TIME,)


@pytest.mark.parametrize('member', ['SCHEMA', '__init__'])
def test_it_declares_no_model_surface(member: str) -> None:
    """No schema and no constructor of its own: the document is the portal's"""
    assert member not in vars(CmdbCachedUser)


@pytest.mark.parametrize('method', ['from_data', 'to_json'])
def test_building_or_serialising_one_is_refused(method: str) -> None:
    """The CmdbDAO base raises for a model that declares neither - the right answer for a namespace"""
    assert method not in vars(CmdbCachedUser)

    with pytest.raises(NotImplementedError):
        getattr(CmdbCachedUser, method)({} if method == 'from_data' else MagicMock())


def test_there_is_no_active_key() -> None:
    """No write path ever stored one; the portal does not send it"""
    assert 'ACTIVE' not in CachedUserKey.__members__


def test_the_subscription_keys_are_the_portal_spellings() -> None:
    """masterPassword is camel-cased by the portal; the rest are snake-cased"""
    assert {key.value for key in CachedSubscriptionKey} == {
        'database', 'api_level', 'config_item_limit', 'api_key', 'is_valid', 'opencelium', 'masterPassword',
    }


def test_the_scheduler_list_is_spelled_schedules() -> None:
    """The portal's spelling, not the enum's 'schedulers'"""
    assert {key.value for key in CachedOcIdListKey} == {'connectors', 'connections', 'schedules'}


def test_the_manager_turns_a_string_creation_time_into_a_date() -> None:
    """The one live use of the namespace on a write: DATE_FIELDS through GenericManager.insert_item"""
    manager = CachedUserManager.__new__(CachedUserManager)
    manager.model = CmdbCachedUser
    manager.insert = MagicMock(return_value=1)
    manager.exceptions = {}
    document: dict = {CachedUserKey.EMAIL.value: 'a@x.io', CachedUserKey.CREATION_TIME.value: CREATION_TIME_TEXT}

    manager.insert_item(document)

    stored: dict = manager.insert.call_args.args[0]
    assert isinstance(stored[CachedUserKey.CREATION_TIME.value], datetime)


def test_the_cache_lives_in_the_cache_database() -> None:
    """Whatever database a caller names - the manager binds DG_CACHE_DB"""
    assert CachedUserManager(MagicMock(), 'tenant_db').db_name == DG_CACHE_DB
