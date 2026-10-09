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
Integration tests for the delete surface of CachedUserManager (against a real MongoDB)

The methods behind the /setup/cache routes - delete_cached_user, delete_multiple_cached_users and
clear_cache - are exercised on real documents, because their filters are the thing under test:
clear_cache used to pass its empty filter under a `criteria` keyword into delete_many(**requirements),
which turned the keyword itself into the queried FIELD, so the call matched nothing and the cache was
never emptied. Only a real delete shows that

update_cached_user is here for a different reason: its upsert has to satisfy the collection's real
indexes, which the test suite never builds (nothing runs CollectionValidator), so the index-aware test
creates them itself

The manager is built with its real constructor - it holds no Service Portal client - and pointed at the test
database instead of the shared dg_caches one

The cache-miss seeding (``oc_subscription_helper.read_or_seed_cached_user``) and the OpenCelium id check built on it
run against the same real collection with a stubbed portal: a miss is seeded once, and the next read is the cache's
"""
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CachedUserKey, CmdbCachedUser
from cmdb.open_celium import CachedOcIdType
from cmdb.interface.rest_api.routes.open_celium_routes.oc_subscription_helper import (
    oc_id_in_subscription,
    read_or_seed_cached_user,
)
# -------------------------------------------------------------------------------------------------------------------- #

EMAILS: list[str] = ['itest_a@acme.com', 'itest_b@acme.com', 'itest_c@acme.com']


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager(database_manager: MongoDatabaseManager, database_name: str) -> CachedUserManager:
    """Provides a CachedUserManager reading and writing the cache collection of the test database."""
    manager: CachedUserManager = CachedUserManager(database_manager)
    manager.db_name = database_name

    return manager


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the seeded cache entries before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)\
                        .delete_many({'email': {'$in': EMAILS}})

    _purge()
    yield
    _purge()


def _seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes one cache entry per test email."""
    entries: list[dict[str, Any]] = [{'email': email, 'password': 'secret'} for email in EMAILS]

    database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name).insert_many(entries)


def _remaining(database_manager: MongoDatabaseManager, database_name: str) -> list[str]:
    """Returns the emails still held by the cache collection."""
    stored = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name).find({}, {'email': 1})

    return [entry['email'] for entry in stored]


class TestDeleteCachedUser:
    """delete_cached_user removes exactly one entry."""

    def test_removes_only_the_named_user(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The addressed email is gone, the others stay."""
        _seed(database_manager, database_name)

        assert cached_user_manager.delete_cached_user(EMAILS[0]) is True
        assert sorted(_remaining(database_manager, database_name)) == sorted(EMAILS[1:])

    def test_unknown_email_is_false(self, cached_user_manager: CachedUserManager) -> None:
        """Deleting an uncached email deletes nothing and answers False."""
        assert cached_user_manager.delete_cached_user('itest_unknown@acme.com') is False


class TestDeleteMultipleCachedUsers:
    """delete_multiple_cached_users removes a whole list in one operation."""

    def test_removes_every_listed_user(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Both listed emails are gone, the third stays."""
        _seed(database_manager, database_name)

        assert cached_user_manager.delete_multiple_cached_users(EMAILS[:2]) == 2
        assert _remaining(database_manager, database_name) == [EMAILS[2]]

    def test_the_count_leaves_out_what_was_not_cached(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A listed email nothing is cached under is not counted"""
        _seed(database_manager, database_name)

        assert cached_user_manager.delete_multiple_cached_users([EMAILS[0], 'itest_unknown@acme.com']) == 1
        assert sorted(_remaining(database_manager, database_name)) == sorted(EMAILS[1:])


class TestClearCache:
    """clear_cache empties the whole collection."""

    def test_removes_every_entry(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        Every cached user is deleted and the count is reported (regression)

        With the previous delete_many(criteria={}) call the filter was {'criteria': {}}, so this
        returned 0 and left the cache fully populated
        """
        _seed(database_manager, database_name)

        assert cached_user_manager.clear_cache() == len(EMAILS)
        assert _remaining(database_manager, database_name) == []

    def test_on_an_empty_collection_reports_zero(self, cached_user_manager: CachedUserManager) -> None:
        """Clearing an already empty cache removes nothing."""
        assert cached_user_manager.clear_cache() == 0


@pytest.fixture(name='with_indexes')
def fixture_with_indexes(database_manager: MongoDatabaseManager, database_name: str):
    """Builds the collection's declared indexes (unique email, unique public_id, TTL) and drops them again."""
    collection = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
    collection.create_indexes(CmdbCachedUser.get_index_keys())

    yield

    for index in CmdbCachedUser.get_index_keys():
        collection.drop_index(index.document['name'])


class TestUpdateCachedUser:
    """update_cached_user upserts an entry without violating the collection's unique indexes."""

    def test_two_inserting_upserts_both_succeed(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
        with_indexes: None,
    ) -> None:
        """
        Each upserted entry gets its own public_id (regression)

        Before the fix the upsert stored no public_id at all, so the first insert was indexed under a
        null public_id and the second was refused with a duplicate-key error - a 500 in a login flow
        """
        del with_indexes  # the fixture only has to have run

        for email in EMAILS[:2]:
            cached_user_manager.update_cached_user(email, {'password': 'secret'})

        stored = list(
            database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
                            .find({CachedUserKey.EMAIL.value: {'$in': EMAILS[:2]}})
        )

        assert sorted(entry[CachedUserKey.EMAIL.value] for entry in stored) == sorted(EMAILS[:2])
        public_ids = [entry[CachedUserKey.PUBLIC_ID.value] for entry in stored]
        assert len(set(public_ids)) == 2

    def test_refresh_keeps_the_public_id_and_updates_the_data(
        self,
        cached_user_manager: CachedUserManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
        with_indexes: None,
    ) -> None:
        """A second upsert for the same email updates in place rather than inserting."""
        del with_indexes

        cached_user_manager.update_cached_user(EMAILS[0], {'password': 'first'})
        collection = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
        first_id = collection.find_one({CachedUserKey.EMAIL.value: EMAILS[0]})[CachedUserKey.PUBLIC_ID.value]

        cached_user_manager.update_cached_user(EMAILS[0], {'password': 'second'})

        entries = list(collection.find({CachedUserKey.EMAIL.value: EMAILS[0]}))
        assert len(entries) == 1
        assert entries[0][CachedUserKey.PUBLIC_ID.value] == first_id
        assert entries[0][CachedUserKey.PASSWORD.value] == 'second'


# -------------------------------------------------------------------------------------------------------------------- #
#                                         SEEDING A CACHE MISS FROM THE PORTAL                                         #
# -------------------------------------------------------------------------------------------------------------------- #
TENANT_DB: str = 'itest_tenant'
LISTED_SCHEDULER_ID: int = 41
UNLISTED_SCHEDULER_ID: int = 42


def _portal_user(email: str) -> dict[str, Any]:
    """What the portal's user lookup answers: one subscription listing one scheduler id (as a string)"""
    return {
        'email': email,
        'password': 'hashed',
        'subscriptions': [
            {'database': TENANT_DB, 'opencelium': {'schedules': [str(LISTED_SCHEDULER_ID)]}},
        ],
    }


def test_a_miss_is_seeded_once_and_then_served_from_the_cache(cached_user_manager: CachedUserManager) -> None:
    """The first read asks the portal and stores its answer; the second read never reaches the portal"""
    portal = MagicMock()
    portal.get_dg_sp_user_data.return_value = _portal_user(EMAILS[0])

    first = read_or_seed_cached_user(cached_user_manager, portal, EMAILS[0])
    second = read_or_seed_cached_user(cached_user_manager, portal, EMAILS[0])

    assert first[CachedUserKey.EMAIL.value] == EMAILS[0]
    assert CachedUserKey.CREATION_TIME.value in first
    assert second == first
    portal.get_dg_sp_user_data.assert_called_once_with(EMAILS[0])


def test_a_user_the_portal_does_not_know_leaves_the_cache_empty(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Nothing is stored for an empty portal answer"""
    portal = MagicMock()
    portal.get_dg_sp_user_data.return_value = None

    assert read_or_seed_cached_user(cached_user_manager, portal, EMAILS[1]) is None
    assert database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)\
        .count_documents({'email': EMAILS[1]}) == 0


@pytest.mark.parametrize(('scheduler_id', 'expected'), [(LISTED_SCHEDULER_ID, True), (UNLISTED_SCHEDULER_ID, False)])
def test_the_id_check_reads_the_seeded_subscription(
        cached_user_manager: CachedUserManager, scheduler_id: int, expected: bool) -> None:
    """The id list of the user's tenant database decides; the portal's per-kind check is never asked"""
    portal = MagicMock()
    portal.get_dg_sp_user_data.return_value = _portal_user(EMAILS[2])
    request_user = MagicMock(email=EMAILS[2], database=TENANT_DB)

    assert oc_id_in_subscription(
        request_user, CachedOcIdType.SCHEDULERS, scheduler_id, cached_user_manager, portal,
    ) is expected
    portal.check_scheduler_in_sub.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                 THE NAMESPACE'S CONTRACT, AGAINST THE REAL COLLECTION                                #
# -------------------------------------------------------------------------------------------------------------------- #
def _portal_answer(email: str) -> dict[str, Any]:
    """A cached user as the portal answers a login - no 'active' key, a string creation_time"""
    return {
        CachedUserKey.EMAIL.value: email,
        CachedUserKey.USER_NAME.value: email,
        CachedUserKey.PASSWORD.value: 'hmac',
        CachedUserKey.API_LEVEL.value: 1,
        CachedUserKey.SUBSCRIPTIONS.value: [{'database': 'tenant_db', 'api_level': 1, 'config_item_limit': 10}],
    }


def test_a_portal_answer_is_stored_with_a_real_creation_time(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """insert_cached_user stamps creation_time; DATE_FIELDS keeps it a BSON date, which the TTL index needs"""
    cached_user_manager.insert_cached_user(_portal_answer(EMAILS[0]))

    stored = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name).find_one({'email': EMAILS[0]})
    assert isinstance(stored[CachedUserKey.CREATION_TIME.value], datetime)
    assert stored[CachedUserKey.API_LEVEL.value] == 1
    assert 'active' not in stored


@pytest.mark.usefixtures('with_indexes')
def test_the_unique_email_index_refuses_a_second_entry(
        cached_user_manager: CachedUserManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One entry per user - the declared index, built by the fixture because the suite never runs CollectionValidator"""
    collection = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
    cached_user_manager.insert_cached_user(_portal_answer(EMAILS[1]))

    with pytest.raises(Exception):
        cached_user_manager.insert_cached_user(_portal_answer(EMAILS[1]))

    assert collection.count_documents({'email': EMAILS[1]}) == 1

