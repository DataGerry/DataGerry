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
Integration tests for filtering and pagination on ``UsersManager.iterate``

Real-MongoDB exercise of the criteria + skip/limit branches of the iterate pipeline.
Seeds a fixed set of CmdbUser docs, then asserts that filters restrict the returned
set and that pagination splits a result set across pages while preserving the
unfiltered total
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_GROUP_ID: int = 1

SEED_USER_IDS: list[int] = [9901, 9902, 9903, 9904, 9905]
SEED_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': {'$in': SEED_USER_IDS}}}]
SINGLE_ID_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': SEED_USER_IDS[0]}}]
EMPTY_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': 99999}}]

PAGE_SIZE: int = 2
SECOND_PAGE_SKIP: int = 2
EXPECTED_SEED_COUNT: int = len(SEED_USER_IDS)
EXPECTED_SECOND_PAGE_IDS: list[int] = SEED_USER_IDS[SECOND_PAGE_SKIP:SECOND_PAGE_SKIP + PAGE_SIZE]


def _user_doc(public_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbUser doc differentiated only by public_id."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'active': True,
        'group_id': DEFAULT_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
        'password': 'hashed-stub',
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_users_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Inserts the seed users and removes them after the module's tests run."""
    collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    collection.insert_many([_user_doc(public_id) for public_id in SEED_USER_IDS])
    yield
    collection.delete_many({'public_id': {'$in': SEED_USER_IDS}})


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager) -> UsersManager:
    """Provides a UsersManager wired to the test database."""
    return UsersManager(database_manager)


class TestIterateFilter:
    """``UsersManager.iterate`` restricts results to docs matching the criteria filter."""

    def test_filters_by_public_id_set(self, users_manager: UsersManager) -> None:
        """A $match on a public_id $in-list returns exactly those users (admin row excluded)."""
        params = BuilderParameters(criteria=SEED_FILTER, sort='public_id', order=1)

        result = users_manager.iterate(params)

        returned_ids = {user.public_id for user in result.results}
        assert returned_ids == set(SEED_USER_IDS)
        assert result.total == EXPECTED_SEED_COUNT

    def test_filters_by_single_public_id(self, users_manager: UsersManager) -> None:
        """A $match on a single public_id returns the matching user."""
        params = BuilderParameters(criteria=SINGLE_ID_FILTER, sort='public_id', order=1)

        result = users_manager.iterate(params)

        assert [user.public_id for user in result.results] == [SEED_USER_IDS[0]]
        assert result.total == 1

    def test_empty_match_returns_no_results_and_total_zero(self, users_manager: UsersManager) -> None:
        """A filter that matches nothing returns an empty result list and total = 0."""
        params = BuilderParameters(criteria=EMPTY_FILTER, sort='public_id', order=1)

        result = users_manager.iterate(params)

        assert result.results == []
        assert result.total == 0


class TestIteratePagination:
    """``skip`` + ``limit`` page through the matching set while ``total`` reflects the unfiltered match count."""

    def test_skip_and_limit_yield_expected_page(self, users_manager: UsersManager) -> None:
        """Page two (skip=PAGE_SIZE, limit=PAGE_SIZE) returns the third and fourth seed users in id order."""
        params = BuilderParameters(
            criteria=SEED_FILTER,
            sort='public_id',
            order=1,
            skip=SECOND_PAGE_SKIP,
            limit=PAGE_SIZE,
        )

        result = users_manager.iterate(params)

        assert [user.public_id for user in result.results] == EXPECTED_SECOND_PAGE_IDS
        assert result.total == EXPECTED_SEED_COUNT
