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
Integration tests for the CmdbReport indexes against a real MongoDB

The unit tests pin what CmdbReport *declares*; these pin that the declaration is something MongoDB
actually accepts and that the boot-time reconciliation creates it on an existing collection - which is
how a deployment that predates the declaration gets the indexes. Also pins that the guard queries
these indexes exist for (the category-delete count on ``report_category_id`` and the report count of a
CmdbType on ``type_id``) are served by an index instead of scanning the collection.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.models.reports_model.cmdb_report import CmdbReport
# -------------------------------------------------------------------------------------------------------------------- #

REPORT_CATEGORY_ID_INDEX: str = 'report_category_id'
TYPE_ID_INDEX: str = 'type_id'

DECLARED_INDEX_NAMES: list[str] = [REPORT_CATEGORY_ID_INDEX, TYPE_ID_INDEX]

INDEX_SCAN_STAGE: str = 'IXSCAN'


def _reports(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report collection bound to the test database."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name)


@pytest.fixture(name='reconciled_indexes', autouse=True)
def fixture_reconciled_indexes(database_manager: MongoDatabaseManager, database_name: str):
    """Runs the boot-time index reconciliation for framework.reports, then drops what it created."""
    validator = CollectionValidator(database_name, database_manager)
    validator.ensure_indexes(CmdbReport.COLLECTION, database_name, CmdbReport.get_index_keys())

    yield

    for index_name in DECLARED_INDEX_NAMES:
        _reports(database_manager, database_name).drop_index(index_name)


def test_reconciliation_creates_the_declared_indexes(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """Every declared index exists on the collection after the reconciliation pass."""
    existing: dict[str, Any] = database_manager.get_index_info(CmdbReport.COLLECTION, database_name)

    assert set(DECLARED_INDEX_NAMES) <= set(existing)


def test_reconciliation_is_additive_and_re_runnable(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """A second pass over an already-indexed collection changes nothing (it only adds what is missing)."""
    before: dict[str, Any] = database_manager.get_index_info(CmdbReport.COLLECTION, database_name)

    CollectionValidator(database_name, database_manager).ensure_indexes(
        CmdbReport.COLLECTION, database_name, CmdbReport.get_index_keys()
    )

    assert set(database_manager.get_index_info(CmdbReport.COLLECTION, database_name)) == set(before)


@pytest.mark.parametrize('criteria,expected_index', [
    ({'report_category_id': 1}, REPORT_CATEGORY_ID_INDEX),
    ({'type_id': 1}, TYPE_ID_INDEX),
])
def test_the_guard_counts_are_index_served(
    database_manager: MongoDatabaseManager,
    database_name: str,
    criteria: dict[str, Any],
    expected_index: str,
) -> None:
    """The delete guard / type count queries plan as an index scan, not a collection scan."""
    plan = _reports(database_manager, database_name).find(criteria).explain()
    winning_plan: dict[str, Any] = plan['queryPlanner']['winningPlan']

    # The stage nesting differs between server versions, so the plan is searched for the index scan
    stages: list[dict[str, Any]] = [winning_plan]
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

    assert expected_index in index_names
