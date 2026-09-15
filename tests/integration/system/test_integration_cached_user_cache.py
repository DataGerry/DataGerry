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

The manager is built with __new__ (its __init__ constructs a DgServicePortalManager, which needs an
app context) and pointed at the test database instead of the shared dg_caches one
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CachedUserKey, CmdbCachedUser
# -------------------------------------------------------------------------------------------------------------------- #

EMAILS: list[str] = ['itest_a@acme.com', 'itest_b@acme.com', 'itest_c@acme.com']


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager(database_manager: MongoDatabaseManager, database_name: str) -> CachedUserManager:
    """Provides a CachedUserManager reading and writing the cache collection of the test database."""
    manager: CachedUserManager = CachedUserManager.__new__(CachedUserManager)
    manager.dbm = database_manager
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

        assert cached_user_manager.delete_multiple_cached_users(EMAILS[:2]) is True
        assert _remaining(database_manager, database_name) == [EMAILS[2]]


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
