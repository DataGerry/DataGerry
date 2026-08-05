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
Integration tests for filtering and pagination on ``ObjectsManager.iterate``

Real-MongoDB exercise of the criteria + skip/limit branches of the iterate pipeline.
Seeds a fixed set of CmdbObject docs under two type_ids, then asserts that filters
restrict the returned set, that pagination splits a result set across pages while
preserving the unfiltered total, and that an empty match returns ``[]`` with
``total = 0``
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

PRIMARY_TYPE_ID: int = 9301
OTHER_TYPE_ID: int = 9302

PRIMARY_OBJECT_IDS: list[int] = [9311, 9312, 9313, 9314, 9315]
OTHER_OBJECT_IDS: list[int] = [9321]
ALL_SEEDED_IDS: list[int] = PRIMARY_OBJECT_IDS + OTHER_OBJECT_IDS

PRIMARY_TYPE_FILTER: list[dict[str, Any]] = [{'$match': {'type_id': PRIMARY_TYPE_ID}}]
EMPTY_FILTER: list[dict[str, Any]] = [{'$match': {'type_id': 99999}}]
SINGLE_ID_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': PRIMARY_OBJECT_IDS[0]}}]

PAGE_SIZE: int = 2
SECOND_PAGE_SKIP: int = 2
EXPECTED_PRIMARY_COUNT: int = len(PRIMARY_OBJECT_IDS)
EXPECTED_SECOND_PAGE_IDS: list[int] = PRIMARY_OBJECT_IDS[SECOND_PAGE_SKIP:SECOND_PAGE_SKIP + PAGE_SIZE]


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc carrying just the required keys + an empty fields list."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_objects_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Inserts the seed objects across two type_ids and removes them after the module's tests run."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    docs = [_object_doc(public_id, PRIMARY_TYPE_ID) for public_id in PRIMARY_OBJECT_IDS]
    docs.extend(_object_doc(public_id, OTHER_TYPE_ID) for public_id in OTHER_OBJECT_IDS)
    collection.insert_many(docs)
    yield
    collection.delete_many({'public_id': {'$in': ALL_SEEDED_IDS}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


class TestIterateFilter:
    """``ObjectsManager.iterate`` restricts results to docs matching the criteria filter."""

    def test_filters_by_type_id(self, objects_manager: ObjectsManager) -> None:
        """A $match on type_id returns only docs of that type; other-type seed rows are excluded."""
        params = BuilderParameters(criteria=PRIMARY_TYPE_FILTER, sort='public_id', order=1)

        result = objects_manager.iterate(params)

        returned_ids = {doc.public_id for doc in result.results}
        assert returned_ids == set(PRIMARY_OBJECT_IDS)
        assert result.total == EXPECTED_PRIMARY_COUNT

    def test_filters_by_public_id(self, objects_manager: ObjectsManager) -> None:
        """A $match on public_id returns the single matching doc."""
        params = BuilderParameters(criteria=SINGLE_ID_FILTER, sort='public_id', order=1)

        result = objects_manager.iterate(params)

        assert [doc.public_id for doc in result.results] == [PRIMARY_OBJECT_IDS[0]]
        assert result.total == 1

    def test_empty_match_returns_no_results_and_total_zero(self, objects_manager: ObjectsManager) -> None:
        """A filter that matches nothing returns an empty result list and total = 0."""
        params = BuilderParameters(criteria=EMPTY_FILTER, sort='public_id', order=1)

        result = objects_manager.iterate(params)

        assert result.results == []
        assert result.total == 0


class TestIteratePagination:
    """``skip`` + ``limit`` page through the matching set while ``total`` reflects the unfiltered match count."""

    def test_skip_and_limit_yield_expected_page(self, objects_manager: ObjectsManager) -> None:
        """Page two (skip=PAGE_SIZE, limit=PAGE_SIZE) returns the third and fourth primary docs in id order."""
        params = BuilderParameters(
            criteria=PRIMARY_TYPE_FILTER,
            sort='public_id',
            order=1,
            skip=SECOND_PAGE_SKIP,
            limit=PAGE_SIZE,
        )

        result = objects_manager.iterate(params)

        assert [doc.public_id for doc in result.results] == EXPECTED_SECOND_PAGE_IDS
        assert result.total == EXPECTED_PRIMARY_COUNT
