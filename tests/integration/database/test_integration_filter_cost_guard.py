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
Integration tests for the client filter guard's cost rules, against a real MongoDB

What the unit tests cannot show: a filter the guard accepts is one MongoDB runs - the frontend's largest object
search included - and the most a guard-accepted filter can make of one document still finishes far inside the
query's time budget, on documents far larger than the measured attacks used
"""
import time
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.interface.request_limits_constants import MILLISECONDS_PER_SECOND
from cmdb.interface.rest_api.responses.response_parameters.pipeline_guard import assert_client_filter_is_allowed
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    MAX_ARRAY_BUILDING_OPERATORS,
)
from tests.utils.filter_cost_payloads import FIFTY_FIELDS, FRONTEND_OBJECTS_BY_TYPE_SEARCH
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_COLLECTION: str = 'test.filter_cost_guard'
DOCUMENT_COUNT: int = 3
# A hundred times the fifty entries the attacks were measured on
FIELD_COUNT: int = 5000
# The worst accepted filter has to finish within this share of the budget - a guard that let a document's cost
# run away would not come close
BUDGET_SHARE: float = 0.2


def _worst_accepted_filter() -> list[dict[str, Any]]:
    """Every array-building operator the cap allows, each doubling the fields; the last one maps the result"""
    doublings: list[dict[str, Any]] = [
        {'$addFields': {'fields': {'$concatArrays': [FIFTY_FIELDS, FIFTY_FIELDS]}}}
        for _ in range(MAX_ARRAY_BUILDING_OPERATORS - 1)
    ]

    return [
        *doublings,
        {'$addFields': {'burn': {'$map': {'input': FIFTY_FIELDS, 'in': {'$toString': '$$this.value'}}}}},
    ]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds DOCUMENT_COUNT documents with FIELD_COUNT field entries each, dropped afterwards."""
    collection = database_manager.get_collection(SCRATCH_COLLECTION, database_name)
    collection.drop()
    collection.insert_many([
        {'public_id': public_id, 'type_id': 7,
         'fields': [{'name': f'field-{index}', 'value': index} for index in range(FIELD_COUNT)]}
        for public_id in range(DOCUMENT_COUNT)
    ])
    yield collection
    collection.drop()


class TestWhatTheGuardAcceptsRuns:
    """Accepted by the guard and run by the server, under the production budget."""

    def test_the_frontends_largest_object_search_runs(self, scratch) -> None:
        """Every operator it uses is one MongoDB 7.0 runs - the allow-list holds no dead entry it depends on"""
        assert_client_filter_is_allowed(FRONTEND_OBJECTS_BY_TYPE_SEARCH)

        results = list(scratch.aggregate(FRONTEND_OBJECTS_BY_TYPE_SEARCH, maxTimeMS=QUERY_TIME_LIMIT_MS))

        assert isinstance(results, list)

    def test_the_worst_accepted_filter_stays_far_inside_the_budget(self, scratch) -> None:
        """
        The caps grow an array at most 2**(cap - 1) times, then one pass over it

        Measured, the attacks the guard now refuses ran 104 s on three 50-entry documents; this is the most the
        guard still accepts, on three 5000-entry documents
        """
        pipeline: list[dict[str, Any]] = _worst_accepted_filter()
        assert_client_filter_is_allowed(pipeline)

        started: float = time.monotonic()
        results = list(scratch.aggregate([*pipeline, {'$project': {'size': {'$size': '$burn'}}}],
                                         maxTimeMS=QUERY_TIME_LIMIT_MS))
        elapsed: float = time.monotonic() - started

        grown_size: int = FIELD_COUNT * 2 ** (MAX_ARRAY_BUILDING_OPERATORS - 1)

        assert [result['size'] for result in results] == [grown_size] * DOCUMENT_COUNT
        assert elapsed < QUERY_TIME_LIMIT_MS / MILLISECONDS_PER_SECOND * BUDGET_SHARE
