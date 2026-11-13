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
Integration tests for cmdb.database.updater.versions.updater_20261117 against a real MongoDB

Seeds ISMS assessments and an assignment whose dates hold the date picker's calendar-date object, runs the migration,
and asserts:

  - a calendar-date object becomes midnight UTC of its day, in every date field of both collections
  - the converted value is a BSON date a range filter finds
  - what the model would refuse is left as it was: a day that does not exist, a text part, an extra key, a wrapper
  - a second run changes nothing
"""
from datetime import datetime
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261117 import (
    Update20261117,
    build_calendar_date_filter,
    build_calendar_date_pipeline,
)
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #

RA_DATE: str = RiskAssessmentKey.RISK_ASSESSMENT_DATE.value
AUDIT_DATE: str = RiskAssessmentKey.AUDIT_DONE_DATE.value
PLANNED_DATE: str = 'planned_implementation_date'

CALENDAR_RA_ID: int = 9960
REFUSED_RA_ID: int = 9961
ALL_RA_IDS: list[int] = [CALENDAR_RA_ID, REFUSED_RA_ID]
CALENDAR_CMA_ID: int = 9970

NO_SUCH_DAY: dict[str, int] = {'year': 2026, 'month': 2, 'day': 30}
TEXT_PART: dict[str, Any] = {'year': '2026', 'month': 11, 'day': 27}
EXTRA_KEY: dict[str, int] = {'year': 2026, 'month': 11, 'day': 27, 'hour': 3}
WRAPPER: dict[str, str] = {'$date': 'not-a-timestamp'}


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[Any, Any]]:
    """The seeded assessments and assignment, removed again after"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({'public_id': {'$in': ALL_RA_IDS}})
        assignments.delete_many({'public_id': CALENDAR_CMA_ID})

    _purge()
    assessments.insert_many([
        {'public_id': CALENDAR_RA_ID, RA_DATE: {'year': 2026, 'month': 11, 'day': 27},
         PLANNED_DATE: {'day': 1, 'month': 12, 'year': 2026}, AUDIT_DATE: None},
        {'public_id': REFUSED_RA_ID, RA_DATE: NO_SUCH_DAY, PLANNED_DATE: TEXT_PART, AUDIT_DATE: EXTRA_KEY,
         'finished_implementation_date': WRAPPER},
    ])
    assignments.insert_one({'public_id': CALENDAR_CMA_ID, PLANNED_DATE: {'year': 2027, 'month': 1, 'day': 31}})

    yield assessments, assignments

    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20261117(database_manager, database_name).start_update()


def test_a_calendar_object_becomes_midnight_utc(database_manager: MongoDatabaseManager, database_name: str,
                                                collections: tuple[Any, Any]) -> None:
    """Every field, both collections; a null stays null"""
    assessments, assignments = collections

    _run(database_manager, database_name)

    stored = assessments.find_one({'public_id': CALENDAR_RA_ID})
    assert (stored[RA_DATE], stored[PLANNED_DATE], stored[AUDIT_DATE]) == (
        datetime(2026, 11, 27), datetime(2026, 12, 1), None)
    assert assignments.find_one({'public_id': CALENDAR_CMA_ID})[PLANNED_DATE] == datetime(2027, 1, 31)


def test_the_converted_date_is_found_by_a_range(database_manager: MongoDatabaseManager, database_name: str,
                                                collections: tuple[Any, Any]) -> None:
    """A sub-document would match nothing"""
    assessments, _ = collections

    _run(database_manager, database_name)

    assert assessments.count_documents({'public_id': CALENDAR_RA_ID,
                                        RA_DATE: {'$gte': datetime(2026, 11, 1), '$lt': datetime(2026, 12, 1)}}) == 1


def test_what_the_model_refuses_is_left_as_it_was(database_manager: MongoDatabaseManager, database_name: str,
                                                  collections: tuple[Any, Any]) -> None:
    """No roll-over into March, no guessed part"""
    assessments, _ = collections

    _run(database_manager, database_name)

    stored = assessments.find_one({'public_id': REFUSED_RA_ID}, {'_id': 0, 'public_id': 0})
    assert stored == {RA_DATE: NO_SUCH_DAY, PLANNED_DATE: TEXT_PART, AUDIT_DATE: EXTRA_KEY,
                      'finished_implementation_date': WRAPPER}


def test_a_second_run_changes_nothing(database_manager: MongoDatabaseManager, database_name: str,
                                      collections: tuple[Any, Any]) -> None:
    """The refused objects still match the filter, and are rewritten with themselves"""
    assessments, _ = collections
    _run(database_manager, database_name)

    for field in (RA_DATE, PLANNED_DATE, AUDIT_DATE):
        result = assessments.update_many({'public_id': {'$in': ALL_RA_IDS}, **build_calendar_date_filter(field)},
                                         build_calendar_date_pipeline(field))
        assert result.modified_count == 0
