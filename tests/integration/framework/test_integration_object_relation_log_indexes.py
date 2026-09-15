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
Integration tests for the CmdbObjectRelationLog indexes against a real MongoDB

The unit tests pin what the model *declares*; these pin that MongoDB accepts the declaration, that the
boot-time reconciliation creates it on an existing collection - which is how a deployment that predates
the declaration gets the new indexes - and, the part that is the whole point, that the query the object
view actually runs is served by an index instead of scanning an unbounded, append-only collection.

The query is the one the Angular relation-log list sends on every object view:
``{$or: [{object_relation_parent_id: <id>}, {object_relation_child_id: <id>}]}`` sorted by public_id.
Before this sweep the collection carried a single index on ``object_relation_id``, which nothing
queries at all
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction, ObjectRelationLogKey
# -------------------------------------------------------------------------------------------------------------------- #

PARENT_HISTORY_INDEX: str = 'object_relation_parent_history'
CHILD_HISTORY_INDEX: str = 'object_relation_child_history'
RELATION_INDEX: str = ObjectRelationLogKey.OBJECT_RELATION_ID.value

DECLARED_INDEX_NAMES: list[str] = [PARENT_HISTORY_INDEX, CHILD_HISTORY_INDEX, RELATION_INDEX]

INDEX_SCAN_STAGE: str = 'IXSCAN'
COLLECTION_SCAN_STAGE: str = 'COLLSCAN'

OBJECT_ID: int = 8100
OTHER_OBJECT_ID: int = 8200
LOG_IDS: list[int] = [8301, 8302, 8303]


def _logs(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the object-relation log collection bound to the test database."""
    return database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)


def _log_doc(public_id: int, parent_id: int, child_id: int) -> dict[str, Any]:
    """Builds one audit entry for direct insertion"""
    return {
        ObjectRelationLogKey.PUBLIC_ID.value: public_id,
        ObjectRelationLogKey.OBJECT_RELATION_ID.value: 1,
        ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: parent_id,
        ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: child_id,
        ObjectRelationLogKey.CREATION_TIME.value: datetime.now(timezone.utc),
        ObjectRelationLogKey.ACTION.value: LogInteraction.CREATE.value,
        ObjectRelationLogKey.AUTHOR_ID.value: 1,
        ObjectRelationLogKey.AUTHOR_NAME.value: 'admin',
        ObjectRelationLogKey.CHANGES.value: {},
    }


@pytest.fixture(name='reconciled_indexes', autouse=True)
def fixture_reconciled_indexes(database_manager: MongoDatabaseManager, database_name: str):
    """
    Runs the boot-time index reconciliation for the log collection, then drops what it created

    The test suite never runs CollectionValidator, so a declared index does not exist in a test
    database unless a test builds it - which is exactly the gap that let the previous index set go
    unnoticed.
    """
    logs = _logs(database_manager, database_name)
    logs.delete_many({ObjectRelationLogKey.PUBLIC_ID.value: {'$in': LOG_IDS}})
    logs.insert_many([
        _log_doc(LOG_IDS[0], OBJECT_ID, OTHER_OBJECT_ID),
        _log_doc(LOG_IDS[1], OTHER_OBJECT_ID, OBJECT_ID),
        _log_doc(LOG_IDS[2], OTHER_OBJECT_ID, OTHER_OBJECT_ID),
    ])

    validator = CollectionValidator(database_name, database_manager)
    validator.ensure_indexes(
        CmdbObjectRelationLog.COLLECTION, database_name, CmdbObjectRelationLog.get_index_keys(),
    )

    yield

    logs.delete_many({ObjectRelationLogKey.PUBLIC_ID.value: {'$in': LOG_IDS}})

    for index_name in DECLARED_INDEX_NAMES:
        logs.drop_index(index_name)


def _index_names_of_plan(plan: dict[str, Any]) -> set[str]:
    """
    Collects every index name an explain plan scans

    The stage nesting differs between server versions, so the plan is searched rather than indexed
    into.

    Args:
        plan (dict[str, Any]): The winning plan of an explain result

    Returns:
        set[str]: The names of the indexes the plan scans (empty for a collection scan)
    """
    stages: list[dict[str, Any]] = [plan]
    index_names: set[str] = set()

    while stages:
        stage: dict[str, Any] = stages.pop()

        if stage.get('stage') == INDEX_SCAN_STAGE:
            index_names.add(stage.get('indexName'))

        for value in stage.values():
            if isinstance(value, dict):
                stages.append(value)
            elif isinstance(value, list):
                stages.extend(entry for entry in value if isinstance(entry, dict))

    return index_names


def test_reconciliation_creates_the_declared_indexes(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """Every declared index exists on the collection after the reconciliation pass."""
    existing: dict[str, Any] = database_manager.get_index_info(
        CmdbObjectRelationLog.COLLECTION, database_name,
    )

    assert set(DECLARED_INDEX_NAMES) <= set(existing)


def test_reconciliation_is_additive_and_re_runnable(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    A second pass over an already-indexed collection changes nothing

    Which is also why the two new indexes reach an existing deployment on the next start, and why
    removing one would need a migration rather than a declaration change.
    """
    before: dict[str, Any] = database_manager.get_index_info(
        CmdbObjectRelationLog.COLLECTION, database_name,
    )

    CollectionValidator(database_name, database_manager).ensure_indexes(
        CmdbObjectRelationLog.COLLECTION, database_name, CmdbObjectRelationLog.get_index_keys(),
    )

    assert set(database_manager.get_index_info(
        CmdbObjectRelationLog.COLLECTION, database_name,
    )) == set(before)


@pytest.mark.parametrize('criteria, expected_index', [
    ({ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: OBJECT_ID}, PARENT_HISTORY_INDEX),
    ({ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: OBJECT_ID}, CHILD_HISTORY_INDEX),
])
def test_each_side_of_the_history_query_is_index_served(
    database_manager: MongoDatabaseManager,
    database_name: str,
    criteria: dict[str, Any],
    expected_index: str,
) -> None:
    """Each half of the object view's '$or' plans as an index scan, not a collection scan."""
    plan = _logs(database_manager, database_name).find(criteria).sort(
        ObjectRelationLogKey.PUBLIC_ID.value, 1,
    ).explain()

    assert expected_index in _index_names_of_plan(plan['queryPlanner']['winningPlan'])


def test_the_object_view_query_is_index_served_on_both_sides(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The whole query the frontend sends, matched against both indexes rather than scanned

    This is the query that ran on every object view; with the previous index set the plan had no
    choice but a collection scan of an append-only collection that only ever grows.
    """
    criteria: dict[str, Any] = {
        '$or': [
            {ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: OBJECT_ID},
            {ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: OBJECT_ID},
        ],
    }

    plan = _logs(database_manager, database_name).find(criteria).sort(
        ObjectRelationLogKey.PUBLIC_ID.value, 1,
    ).explain()
    scanned: set[str] = _index_names_of_plan(plan['queryPlanner']['winningPlan'])

    assert {PARENT_HISTORY_INDEX, CHILD_HISTORY_INDEX} <= scanned


def test_the_history_query_returns_both_sides(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The index change must not change the answer

    An object's history is every entry where it is either endpoint - here two of the three seeded
    entries, and not the one between two other objects.
    """
    criteria: dict[str, Any] = {
        ObjectRelationLogKey.PUBLIC_ID.value: {'$in': LOG_IDS},
        '$or': [
            {ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: OBJECT_ID},
            {ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: OBJECT_ID},
        ],
    }

    found = list(_logs(database_manager, database_name).find(
        criteria, {ObjectRelationLogKey.PUBLIC_ID.value: 1},
    ).sort(ObjectRelationLogKey.PUBLIC_ID.value, 1))

    assert [row[ObjectRelationLogKey.PUBLIC_ID.value] for row in found] == [LOG_IDS[0], LOG_IDS[1]]
