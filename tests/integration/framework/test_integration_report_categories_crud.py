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
Integration tests for the CmdbReportCategory CRUD surface of ReportCategoriesManager

Pins the manager-layer behaviour against a real MongoDB: insert / get / update / delete round-trip
through the bound collection, iterate_items honours BuilderParameters, and the cross-collection
count_from_other_collection (used by the delete-in-use guard) counts referencing reports.
ReportCategoriesManager is a thin GenericManager subclass, so this exercises the generic CRUD wiring
for the report-category collection.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.report_categories_manager import ReportCategoriesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.reports_model.cmdb_report import CmdbReport
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID_FOR_INSERT: int = 9711
CATEGORY_ID_FOR_GET: int = 9712
CATEGORY_ID_FOR_UPDATE: int = 9713
CATEGORY_ID_FOR_DELETE: int = 9714
CATEGORY_ID_FOR_ITERATE_A: int = 9715
CATEGORY_ID_FOR_ITERATE_B: int = 9716
CATEGORY_ID_REFERENCED: int = 9717
CATEGORY_ID_UNREFERENCED: int = 9718
MISSING_CATEGORY_ID: int = 9799

REPORT_ID_USING_CATEGORY: int = 9751

ORIGINAL_NAME: str = 'Integration Category'
UPDATED_NAME: str = 'Integration Category (updated)'

SEED_CATEGORY_IDS: list[int] = [
    CATEGORY_ID_FOR_INSERT,
    CATEGORY_ID_FOR_GET,
    CATEGORY_ID_FOR_UPDATE,
    CATEGORY_ID_FOR_DELETE,
    CATEGORY_ID_FOR_ITERATE_A,
    CATEGORY_ID_FOR_ITERATE_B,
    CATEGORY_ID_REFERENCED,
    CATEGORY_ID_UNREFERENCED,
]


def _category_data(public_id: int, name: str = ORIGINAL_NAME, predefined: bool = False) -> dict[str, Any]:
    """Builds a minimal CmdbReportCategory document acceptable to insert_item."""
    return {'public_id': public_id, 'name': name, 'predefined': predefined}


def _categories(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report-category collection bound to the test database."""
    return database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)


def _reports(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report collection bound to the test database."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _categories(database_manager, database_name).delete_many({'public_id': {'$in': SEED_CATEGORY_IDS}})
    _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_USING_CATEGORY})


@pytest.fixture(name='report_categories_manager')
def fixture_report_categories_manager(database_manager: MongoDatabaseManager) -> ReportCategoriesManager:
    """Provides a ReportCategoriesManager wired to the test database."""
    return ReportCategoriesManager(database_manager)


def _delete_category(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one category doc directly via the collection, used for per-test cleanup."""
    _categories(database_manager, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertReportCategory:
    """``insert_item`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_INSERT))

            assert returned_id == CATEGORY_ID_FOR_INSERT
            stored = _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_INSERT})
            assert stored is not None
            assert stored['name'] == ORIGINAL_NAME
        finally:
            _delete_category(database_manager, database_name, CATEGORY_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetReportCategory:
    """``get_item`` resolves present ids and returns None for missing ones."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single category before each test in this class and removes it after."""
        report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_GET))
        yield
        _delete_category(database_manager, database_name, CATEGORY_ID_FOR_GET)

    def test_returns_dict_for_existing_id(self, report_categories_manager: ReportCategoriesManager) -> None:
        """A present id resolves into a dict carrying the seeded public_id."""
        result = report_categories_manager.get_item(CATEGORY_ID_FOR_GET, as_dict=True)

        assert result is not None
        assert result['public_id'] == CATEGORY_ID_FOR_GET

    def test_returns_none_for_missing_id(self, report_categories_manager: ReportCategoriesManager) -> None:
        """A missing id returns None."""
        assert report_categories_manager.get_item(MISSING_CATEGORY_ID, as_dict=True) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateReportCategory:
    """``update_item`` writes the new payload over the existing doc."""

    def test_persists_new_name(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing category replaces the stored name."""
        try:
            report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_UPDATE))

            report_categories_manager.update_item(
                CATEGORY_ID_FOR_UPDATE, _category_data(CATEGORY_ID_FOR_UPDATE, UPDATED_NAME)
            )

            stored = report_categories_manager.get_item(CATEGORY_ID_FOR_UPDATE, as_dict=True)
            assert stored is not None
            assert stored['name'] == UPDATED_NAME
        finally:
            _delete_category(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteReportCategory:
    """``delete_item`` removes the document and reports the acknowledgement."""

    def test_removes_doc(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing category removes it and returns True."""
        report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_DELETE))

        assert report_categories_manager.delete_item(CATEGORY_ID_FOR_DELETE) is True
        assert _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_DELETE}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ITERATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterateReportCategories:
    """``iterate_items`` returns the matching categories with a total count."""

    def test_iterate_returns_seeded_rows(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A filter on public_id returns exactly the matching seeded categories."""
        try:
            report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_ITERATE_A, 'Iter A'))
            report_categories_manager.insert_item(_category_data(CATEGORY_ID_FOR_ITERATE_B, 'Iter B'))

            builder_params = BuilderParameters(
                criteria={'public_id': {'$in': [CATEGORY_ID_FOR_ITERATE_A, CATEGORY_ID_FOR_ITERATE_B]}}
            )
            result = report_categories_manager.iterate_items(builder_params)

            assert result.total == 2
            assert {category.get_public_id() for category in result.results} == {
                CATEGORY_ID_FOR_ITERATE_A, CATEGORY_ID_FOR_ITERATE_B,
            }
        finally:
            _delete_category(database_manager, database_name, CATEGORY_ID_FOR_ITERATE_A)
            _delete_category(database_manager, database_name, CATEGORY_ID_FOR_ITERATE_B)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_from_other_collection                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCountReferencingReports:
    """``count_from_other_collection`` counts referencing reports (the delete-in-use guard)."""

    def test_counts_reports_referencing_the_category(
        self,
        report_categories_manager: ReportCategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A category referenced by a report counts 1; an unreferenced one counts 0."""
        try:
            _reports(database_manager, database_name).insert_one(
                {'public_id': REPORT_ID_USING_CATEGORY, 'report_category_id': CATEGORY_ID_REFERENCED}
            )

            referenced = report_categories_manager.count_from_other_collection(
                CmdbReport.COLLECTION, {'report_category_id': CATEGORY_ID_REFERENCED}
            )
            unreferenced = report_categories_manager.count_from_other_collection(
                CmdbReport.COLLECTION, {'report_category_id': CATEGORY_ID_UNREFERENCED}
            )

            assert referenced == 1
            assert unreferenced == 0
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_USING_CATEGORY})
