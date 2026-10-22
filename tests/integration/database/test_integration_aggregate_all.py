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
Integration tests of MongoDatabaseManager.aggregate_all against a real MongoDB

Everything runs in a scratch database of its own, dropped afterwards. The aggregation is read to its end inside the
database layer: a result spanning several batches comes back whole, a pipeline ending in $merge answers an empty list
once its write has run (the updaters rely on that before they bump their version), and a stage the server refuses is
a DocumentAggregationError
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentAggregationError
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-aggregate-all'
SOURCE_COLLECTION: str = 'test.aggregateSource'
TARGET_COLLECTION: str = 'test.aggregateTarget'
STORED_IDS: list[int] = list(range(1, 8))
# Smaller than the number of stored documents, so the read needs several getMore batches
BATCH_SIZE: int = 2
MERGED_FIELD: str = 'merged'


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A scratch database holding one document per STORED_IDS entry, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    database_manager.connector.client.drop_database(name)
    database_manager.get_collection(SOURCE_COLLECTION, name).insert_many(
        [{'public_id': public_id} for public_id in STORED_IDS]
    )

    yield name

    database_manager.connector.client.drop_database(name)


def _ids(rows: list[dict[str, Any]]) -> list[int]:
    """The public_ids of the rows, in their order"""
    return [row['public_id'] for row in rows]


def test_a_result_spanning_several_batches_comes_back_whole(database_manager, seeded) -> None:
    """Every batch is read here - the caller gets a list, never a cursor"""
    rows = database_manager.aggregate_all(
        SOURCE_COLLECTION,
        seeded,
        [{'$sort': {'public_id': 1}}, {'$project': {'_id': 0, 'public_id': 1}}],
        batchSize=BATCH_SIZE,
    )

    assert isinstance(rows, list)
    assert _ids(rows) == STORED_IDS


def test_a_merge_pipeline_has_written_when_it_answers(database_manager, seeded) -> None:
    """A $merge answers no rows; once aggregate_all returns, the target holds every merged document"""
    rows = database_manager.aggregate_all(
        SOURCE_COLLECTION,
        seeded,
        [
            {'$project': {'_id': 0, 'public_id': 1, MERGED_FIELD: {'$literal': True}}},
            {'$merge': {'into': TARGET_COLLECTION, 'on': '_id', 'whenMatched': 'merge', 'whenNotMatched': 'insert'}},
        ],
    )

    assert not rows
    merged = list(database_manager.get_collection(TARGET_COLLECTION, seeded).find(
        {MERGED_FIELD: True}, {'_id': 0, 'public_id': 1}, sort=[('public_id', 1)],
    ))
    assert _ids(merged) == STORED_IDS


def test_a_refused_stage_is_an_aggregation_error(database_manager, seeded) -> None:
    """The server refusing the pipeline is the aggregation's typed error, not a raw driver one"""
    with pytest.raises(DocumentAggregationError):
        database_manager.aggregate_all(SOURCE_COLLECTION, seeded, [{'$notAStage': {}}])
