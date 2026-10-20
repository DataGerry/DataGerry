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
Integration tests for cmdb.database.updater.versions.updater_20260907 against a real MongoDB

Reproduces a pre-migration database - ISMS assessments and assignments whose date fields hold the
``{'$date': ...}`` wrapper sub-document - and asserts that the conversion lands, that the converted
values are real dates MongoDB can compare, that a second run changes nothing, and that the values it
cannot read are left alone rather than nulled.

Both halves need a real server. ``$getField`` / ``$convert`` are evaluated by MongoDB, so a stubbed
manager can only prove the pipeline's shape; and the point of the migration is what MongoDB can then
DO with the value - sort it, range-filter it - which is only observable against a real collection.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260907 import Update20260907
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #

# 2020-09-13 12:26:40 UTC in the two shapes the wrapper occurs with
STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)
LATER_MILLIS: int = 1700000000000
LATER: datetime = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

# One assessment per pre-migration shape, plus one already-migrated to prove a re-run is harmless
WRAPPED_RA_ID: int = 9940
STRING_WRAPPED_RA_ID: int = 9941
MIGRATED_RA_ID: int = 9942
UNREADABLE_RA_ID: int = 9943
ALL_RA_IDS: list[int] = [WRAPPED_RA_ID, STRING_WRAPPED_RA_ID, MIGRATED_RA_ID, UNREADABLE_RA_ID]

WRAPPED_CMA_ID: int = 9950
ALL_CMA_IDS: list[int] = [WRAPPED_CMA_ID]


@pytest.fixture(name='pre_migration_db', autouse=True)
def fixture_pre_migration_db(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds assessments / assignments in their pre-migration shape, cleaning up after"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({'public_id': {'$in': ALL_RA_IDS}})
        assignments.delete_many({'public_id': {'$in': ALL_CMA_IDS}})

    _purge()

    assessments.insert_many([
        {
            'public_id': WRAPPED_RA_ID,
            RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {'$date': STAMP_MILLIS},
            RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: {'$date': LATER_MILLIS},
            RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value: None,
            RiskAssessmentKey.AUDIT_DONE_DATE.value: None,
        },
        {
            'public_id': STRING_WRAPPED_RA_ID,
            RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {'$date': '2020-09-13T12:26:40Z'},
        },
        {
            'public_id': MIGRATED_RA_ID,
            RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: STAMP,
        },
        {
            'public_id': UNREADABLE_RA_ID,
            RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {'$date': 'not-a-timestamp'},
            RiskAssessmentKey.AUDIT_DONE_DATE.value: {'legacy_shape': True},
        },
    ])
    assignments.insert_one({
        'public_id': WRAPPED_CMA_ID,
        'planned_implementation_date': {'$date': STAMP_MILLIS},
        'finished_implementation_date': {'$date': LATER_MILLIS},
    })

    yield

    _purge()


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260907(database_manager, database_name).start_update()


def _assessment(
    database_manager: MongoDatabaseManager, database_name: str, public_id: int
) -> dict[str, Any]:
    """Reads one seeded assessment back"""
    return database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


def _assignment(
    database_manager: MongoDatabaseManager, database_name: str, public_id: int
) -> dict[str, Any]:
    """Reads one seeded assignment back"""
    return database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


class TestTheConversion:
    """Turning the wrapper sub-documents into real dates."""

    def test_converts_an_epoch_millis_wrapper(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The shape the frontend sends, and therefore the shape almost every stored date has."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, WRAPPED_RA_ID)

        assert stored[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value] == STAMP.replace(tzinfo=None)

    def test_converts_a_string_wrapper(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """$convert reads a timestamp string as readily as a number."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, STRING_WRAPPED_RA_ID)

        assert stored[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value] == STAMP.replace(tzinfo=None)

    def test_converts_every_declared_field_not_just_the_first(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Each of the four fields gets its own pass, so a later one cannot be forgotten."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, WRAPPED_RA_ID)

        assert stored[RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value] == LATER.replace(tzinfo=None)

    def test_converts_the_assignment_collection_too(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Both ISMS collections store dates, and both were storing them as wrappers."""
        _run_migration(database_manager, database_name)

        stored = _assignment(database_manager, database_name, WRAPPED_CMA_ID)

        assert stored['planned_implementation_date'] == STAMP.replace(tzinfo=None)
        assert stored['finished_implementation_date'] == LATER.replace(tzinfo=None)

    def test_leaves_a_null_date_null(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An optional date that was never filled in is not a wrapper and must stay absent of value."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, WRAPPED_RA_ID)

        assert stored[RiskAssessmentKey.AUDIT_DONE_DATE.value] is None


class TestWhatMongoDBCanNowDo:
    """The reason the migration exists: a real date is queryable, a sub-document is not."""

    def test_the_converted_field_is_a_bson_date(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Asked of the server itself, so this is MongoDB's own view of the value, not pymongo's."""
        _run_migration(database_manager, database_name)

        matched = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .count_documents({
                'public_id': WRAPPED_RA_ID,
                RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {'$type': 'date'},
            })

        assert matched == 1

    def test_a_range_filter_finds_the_converted_document(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        Before the migration this query matched nothing at all.

        Comparing a sub-document against a date is not an error in MongoDB - it simply never matches,
        so a date-range filter on these fields silently returned an empty result.
        """
        _run_migration(database_manager, database_name)

        matched = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .count_documents({
                'public_id': WRAPPED_RA_ID,
                RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: {
                    '$gte': datetime(2020, 1, 1),
                    '$lt': datetime(2021, 1, 1),
                },
            })

        assert matched == 1

    def test_sorting_orders_the_converted_documents_by_time(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A ?sort=risk_assessment_date on the list route now means what it says."""
        _run_migration(database_manager, database_name)

        ordered = list(database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
                       .find({'public_id': {'$in': [WRAPPED_RA_ID, MIGRATED_RA_ID]}})
                       .sort(RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value, 1))

        assert [document['public_id'] for document in ordered] == [MIGRATED_RA_ID, WRAPPED_RA_ID]


class TestNonDestructiveness:
    """What the migration must not do."""

    def test_leaves_an_unreadable_wrapper_untouched(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        Nulling it would destroy the only evidence of what was actually stored.

        The value stays as it is, and because it is still a sub-document a later run picks it up again
        should the conversion ever learn to read it.
        """
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, UNREADABLE_RA_ID)

        assert stored[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value] == {'$date': 'not-a-timestamp'}

    def test_leaves_a_sub_document_that_is_not_a_wrapper_untouched(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The selection is by type, so an unrelated sub-document is matched - and then kept as it is."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, UNREADABLE_RA_ID)

        assert stored[RiskAssessmentKey.AUDIT_DONE_DATE.value] == {'legacy_shape': True}

    def test_leaves_an_already_migrated_document_untouched(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A database migrated by an earlier partial run is not converted twice."""
        _run_migration(database_manager, database_name)

        stored = _assessment(database_manager, database_name, MIGRATED_RA_ID)

        assert stored[RiskAssessmentKey.RISK_ASSESSMENT_DATE.value] == STAMP.replace(tzinfo=None)

    def test_a_second_run_changes_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        The re-run test every migration owes.

        A migration runs once per database, but an interrupted or re-triggered start must not
        double-convert - and a date converted twice would be read as an epoch value in milliseconds
        all over again.
        """
        _run_migration(database_manager, database_name)
        after_first = [_assessment(database_manager, database_name, ra_id) for ra_id in ALL_RA_IDS]

        _run_migration(database_manager, database_name)
        after_second = [_assessment(database_manager, database_name, ra_id) for ra_id in ALL_RA_IDS]

        assert after_second == after_first
