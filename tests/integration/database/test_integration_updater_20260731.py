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
Integration tests for cmdb.database.updater.versions.updater_20260731 against a real MongoDB

Seeds three reports - one predating both keys, one predating only 'mds_mode', one already complete -
runs the migration and asserts the defaults are written where the key was absent, an existing value is
never overwritten, the persisted updater version is bumped, and a second run changes nothing
(idempotent). Also asserts the migrated documents hydrate through CmdbReport.from_data, which is what
the report list does for every row.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.database.updater.versions.updater_20260731 import (
    Update20260731,
    DEFAULT_MDS_MODE,
    DEFAULT_PREDEFINED,
    MDS_MODE_KEY,
    PREDEFINED_KEY,
)
# -------------------------------------------------------------------------------------------------------------------- #

LEGACY_REPORT_ID: int = 9670
PARTIAL_REPORT_ID: int = 9671
COMPLETE_REPORT_ID: int = 9672
REPORT_IDS: list[int] = [LEGACY_REPORT_ID, PARTIAL_REPORT_ID, COMPLETE_REPORT_ID]

TYPE_ID: int = 9675
CATEGORY_ID: int = 9676

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'


def _report_doc(public_id: int, **extra: Any) -> dict[str, Any]:
    """Builds a report document carrying only the always-required keys, plus the given extras."""
    document: dict[str, Any] = {
        'public_id': public_id,
        'report_category_id': CATEGORY_ID,
        'name': f'report-{public_id}',
        'type_id': TYPE_ID,
        'selected_fields': ['field-a'],
        'conditions': {'condition': 'and', 'rules': []},
        'report_query': {'data': '{}'},
    }
    document.update(extra)

    return document


@pytest.fixture(name='reports')
def fixture_reports(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the three reports + preserves the updater setting, restoring everything afterwards."""
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    reports.delete_many({'public_id': {'$in': REPORT_IDS}})
    reports.insert_many([
        # Predates both keys - what a report created before the MDS modes existed looks like
        _report_doc(LEGACY_REPORT_ID),
        _report_doc(PARTIAL_REPORT_ID, predefined=True),
        _report_doc(COMPLETE_REPORT_ID, mds_mode=MdsMode.COLUMNS.value, predefined=True),
    ])

    yield reports

    reports.delete_many({'public_id': {'$in': REPORT_IDS}})
    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


def _stored(reports, public_id: int) -> dict[str, Any]:
    """Returns the stored report document."""
    return reports.find_one({'public_id': public_id})


class TestUpdater20260731:
    """The migration backfills the two optional report keys without touching existing values."""

    def test_absent_keys_are_backfilled_with_the_defaults(
        self, reports, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The report predating both keys gets both defaults."""
        Update20260731(database_manager, database_name).start_update()

        stored = _stored(reports, LEGACY_REPORT_ID)

        assert stored[MDS_MODE_KEY] == DEFAULT_MDS_MODE
        assert stored[PREDEFINED_KEY] is DEFAULT_PREDEFINED

    def test_existing_values_are_never_overwritten(
        self, reports, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A report already carrying a value keeps it - only the missing key is written."""
        Update20260731(database_manager, database_name).start_update()

        partial = _stored(reports, PARTIAL_REPORT_ID)
        complete = _stored(reports, COMPLETE_REPORT_ID)

        assert partial[MDS_MODE_KEY] == DEFAULT_MDS_MODE
        assert partial[PREDEFINED_KEY] is True
        assert complete[MDS_MODE_KEY] == MdsMode.COLUMNS.value
        assert complete[PREDEFINED_KEY] is True

    def test_migrated_reports_hydrate_through_the_model(
        self, reports, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After the migration every seeded document hydrates - the shape the report list needs."""
        Update20260731(database_manager, database_name).start_update()

        for public_id in REPORT_IDS:
            report = CmdbReport.from_data(_stored(reports, public_id))

            assert report.public_id == public_id
            assert report.mds_mode

    def test_version_is_bumped(
        self, reports, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The updater records its own version, so it does not run again."""
        Update20260731(database_manager, database_name).start_update()

        settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

        assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == 20260731

    def test_a_second_run_changes_nothing(
        self, reports, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Re-running the migration over already-migrated documents is a no-op."""
        Update20260731(database_manager, database_name).start_update()
        after_first: list[dict[str, Any]] = [_stored(reports, public_id) for public_id in REPORT_IDS]

        Update20260731(database_manager, database_name).start_update()

        assert [_stored(reports, public_id) for public_id in REPORT_IDS] == after_first
