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
Integration tests for the CmdbReport CRUD surface of ReportsManager

Pins the manager-layer behaviour against a real MongoDB instance: insert / get / update / delete
round-trip through the bound collection, iterate_items honours BuilderParameters and returns the
model-bound results, and count_documents counts reports of a CmdbType. ReportsManager is a thin
GenericManager subclass, so this exercises the generic CRUD wiring for the report collection.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.reports_manager import ReportsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.reports_model.cmdb_report import CmdbReport
# -------------------------------------------------------------------------------------------------------------------- #

REPORT_ID_FOR_INSERT: int = 9901
REPORT_ID_FOR_GET: int = 9902
REPORT_ID_FOR_UPDATE: int = 9903
REPORT_ID_FOR_DELETE: int = 9904
REPORT_ID_FOR_ITERATE_A: int = 9905
REPORT_ID_FOR_ITERATE_B: int = 9906
MISSING_REPORT_ID: int = 9999

REPORT_TYPE_ID: int = 8800
OTHER_TYPE_ID: int = 8801

ORIGINAL_NAME: str = 'Integration Report'
UPDATED_NAME: str = 'Integration Report (updated)'

SEED_REPORT_IDS: list[int] = [
    REPORT_ID_FOR_INSERT,
    REPORT_ID_FOR_GET,
    REPORT_ID_FOR_UPDATE,
    REPORT_ID_FOR_DELETE,
    REPORT_ID_FOR_ITERATE_A,
    REPORT_ID_FOR_ITERATE_B,
]


def _report_data(public_id: int, name: str = ORIGINAL_NAME, type_id: int = REPORT_TYPE_ID) -> dict[str, Any]:
    """Builds a minimal valid CmdbReport document acceptable to ReportsManager.insert_item."""
    return {
        'public_id': public_id,
        'report_category_id': 1,
        'name': name,
        'type_id': type_id,
        'selected_fields': ['field-a'],
        'conditions': {'condition': 'and', 'rules': []},
        'report_query': {'data': '{}'},
        'predefined': False,
        'mds_mode': 'ROWS',
    }


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report collection bound to the test database."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded_reports(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed CmdbReport docs after the module's tests have run."""
    yield
    _collection(database_manager, database_name).delete_many({'public_id': {'$in': SEED_REPORT_IDS}})


@pytest.fixture(name='reports_manager')
def fixture_reports_manager(database_manager: MongoDatabaseManager) -> ReportsManager:
    """Provides a ReportsManager wired to the test database."""
    return ReportsManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertReport:
    """``insert_item`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self, reports_manager: ReportsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = reports_manager.insert_item(_report_data(REPORT_ID_FOR_INSERT))

            assert returned_id == REPORT_ID_FOR_INSERT
            stored = _collection(database_manager, database_name).find_one({'public_id': REPORT_ID_FOR_INSERT})
            assert stored is not None
            assert stored['name'] == ORIGINAL_NAME
        finally:
            _collection(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_INSERT})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetReport:
    """``get_item`` returns the report dict, or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one report directly via the DB before each test and removes it after."""
        _collection(database_manager, database_name).insert_one(_report_data(REPORT_ID_FOR_GET))
        yield
        _collection(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_GET})

    def test_returns_dict_for_existing_id(self, reports_manager: ReportsManager) -> None:
        """A get for a seeded report returns its document as a dict."""
        report = reports_manager.get_item(REPORT_ID_FOR_GET, as_dict=True)

        assert report['public_id'] == REPORT_ID_FOR_GET
        assert report['name'] == ORIGINAL_NAME

    def test_returns_none_for_missing_id(self, reports_manager: ReportsManager) -> None:
        """A get for a missing id returns None."""
        assert reports_manager.get_item(MISSING_REPORT_ID, as_dict=True) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateReport:
    """``update_item`` writes the new payload over the existing report."""

    def test_persists_new_name(
        self, reports_manager: ReportsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After update_item, a re-read reflects the new name."""
        _collection(database_manager, database_name).insert_one(_report_data(REPORT_ID_FOR_UPDATE))
        try:
            reports_manager.update_item(REPORT_ID_FOR_UPDATE, _report_data(REPORT_ID_FOR_UPDATE, name=UPDATED_NAME))

            updated = reports_manager.get_item(REPORT_ID_FOR_UPDATE, as_dict=True)
            assert updated['name'] == UPDATED_NAME
        finally:
            _collection(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_UPDATE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteReport:
    """``delete_item`` removes the report document."""

    def test_removes_doc(
        self, reports_manager: ReportsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After delete_item the report is gone from the collection."""
        _collection(database_manager, database_name).insert_one(_report_data(REPORT_ID_FOR_DELETE))

        reports_manager.delete_item(REPORT_ID_FOR_DELETE)

        assert _collection(database_manager, database_name).find_one({'public_id': REPORT_ID_FOR_DELETE}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ITERATE / COUNT                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterateAndCountReports:
    """``iterate_items`` honours the criteria filter; ``count_documents`` counts by type."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two reports of REPORT_TYPE_ID and one of OTHER_TYPE_ID, then removes them."""
        collection = _collection(database_manager, database_name)
        collection.insert_many([
            _report_data(REPORT_ID_FOR_ITERATE_A),
            _report_data(REPORT_ID_FOR_ITERATE_B),
            _report_data(MISSING_REPORT_ID, type_id=OTHER_TYPE_ID),
        ])
        yield
        collection.delete_many({'public_id': {'$in': [REPORT_ID_FOR_ITERATE_A, REPORT_ID_FOR_ITERATE_B,
                                                      MISSING_REPORT_ID]}})

    def test_iterate_returns_filtered_reports(self, reports_manager: ReportsManager) -> None:
        """A $match on type_id returns only the reports of that type, model-bound."""
        params = BuilderParameters(criteria=[{'$match': {'type_id': REPORT_TYPE_ID}}], sort='public_id', order=1)

        result = reports_manager.iterate_items(params)

        returned_ids = {report.public_id for report in result.results}
        assert {REPORT_ID_FOR_ITERATE_A, REPORT_ID_FOR_ITERATE_B} <= returned_ids
        assert MISSING_REPORT_ID not in returned_ids

    def test_count_documents_counts_reports_of_type(self, reports_manager: ReportsManager) -> None:
        """count_documents counts the reports referencing the given type_id."""
        assert reports_manager.count_documents({'type_id': OTHER_TYPE_ID}) == 1
