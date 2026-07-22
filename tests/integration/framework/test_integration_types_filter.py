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
Integration tests for filtering and pagination on ``TypesManager.iterate``

Real-MongoDB exercise of the criteria + skip/limit branches of the iterate pipeline.
Seeds a fixed set of CmdbType docs, then asserts that filters restrict the returned
set, that pagination splits a result set across pages while preserving the
unfiltered total, and that an empty match returns ``[]`` with ``total = 0``
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

NAME_FIELD: str = 'type-field'
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

ACTIVE_TYPE_IDS: list[int] = [9601, 9602, 9603, 9604, 9605]
INACTIVE_TYPE_IDS: list[int] = [9611]
ALL_SEEDED_IDS: list[int] = ACTIVE_TYPE_IDS + INACTIVE_TYPE_IDS

ACTIVE_FILTER: list[dict[str, Any]] = [{'$match': {'active': True, 'public_id': {'$in': ACTIVE_TYPE_IDS}}}]
SINGLE_ID_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': ACTIVE_TYPE_IDS[0]}}]
EMPTY_FILTER: list[dict[str, Any]] = [{'$match': {'public_id': 99999}}]

PAGE_SIZE: int = 2
SECOND_PAGE_SKIP: int = 2
EXPECTED_ACTIVE_COUNT: int = len(ACTIVE_TYPE_IDS)
EXPECTED_SECOND_PAGE_IDS: list[int] = ACTIVE_TYPE_IDS[SECOND_PAGE_SKIP:SECOND_PAGE_SKIP + PAGE_SIZE]


def _type_doc(public_id: int, active: bool) -> dict[str, Any]:
    """Builds a minimal CmdbType doc differentiated only by public_id and active state."""
    return {
        'public_id': public_id,
        'name': f'type-{public_id}',
        'label': f'Type {public_id}',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': active,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Inserts the seed types (active + inactive) and removes them after the module's tests run."""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    docs = [_type_doc(public_id, active=True) for public_id in ACTIVE_TYPE_IDS]
    docs.extend(_type_doc(public_id, active=False) for public_id in INACTIVE_TYPE_IDS)
    collection.insert_many(docs)
    yield
    collection.delete_many({'public_id': {'$in': ALL_SEEDED_IDS}})


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """Provides a TypesManager wired to the test database."""
    return TypesManager(database_manager)


class TestIterateFilter:
    """``TypesManager.iterate`` restricts results to docs matching the criteria filter."""

    def test_filters_by_active_state(self, types_manager: TypesManager) -> None:
        """A $match on active=True returns only the active seed types."""
        params = BuilderParameters(criteria=ACTIVE_FILTER, sort='public_id', order=1)

        result = types_manager.iterate(params)

        returned_ids = {one_type.public_id for one_type in result.results}
        assert returned_ids == set(ACTIVE_TYPE_IDS)
        assert result.total == EXPECTED_ACTIVE_COUNT

    def test_filters_by_public_id(self, types_manager: TypesManager) -> None:
        """A $match on public_id returns the single matching doc."""
        params = BuilderParameters(criteria=SINGLE_ID_FILTER, sort='public_id', order=1)

        result = types_manager.iterate(params)

        assert [one_type.public_id for one_type in result.results] == [ACTIVE_TYPE_IDS[0]]
        assert result.total == 1

    def test_empty_match_returns_no_results_and_total_zero(self, types_manager: TypesManager) -> None:
        """A filter that matches nothing returns an empty result list and total = 0."""
        params = BuilderParameters(criteria=EMPTY_FILTER, sort='public_id', order=1)

        result = types_manager.iterate(params)

        assert result.results == []
        assert result.total == 0


class TestIteratePagination:
    """``skip`` + ``limit`` page through the matching set while ``total`` reflects the unfiltered match count."""

    def test_skip_and_limit_yield_expected_page(self, types_manager: TypesManager) -> None:
        """Page two (skip=PAGE_SIZE, limit=PAGE_SIZE) returns the third and fourth active types in id order."""
        params = BuilderParameters(
            criteria=ACTIVE_FILTER,
            sort='public_id',
            order=1,
            skip=SECOND_PAGE_SKIP,
            limit=PAGE_SIZE,
        )

        result = types_manager.iterate(params)

        assert [one_type.public_id for one_type in result.results] == EXPECTED_SECOND_PAGE_IDS
        assert result.total == EXPECTED_ACTIVE_COUNT
