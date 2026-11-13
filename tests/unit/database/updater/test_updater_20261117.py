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
Unit tests for cmdb.database.updater.versions.updater_20261117

The migration converts the ISMS dates still stored as a calendar-date object. What MongoDB makes of the filter and the
pipeline is its integration test; this module owns the frozen literals against the models, the filter's parts, the
raw update call, the orchestration and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database.updater.versions import updater_20261117 as module
from cmdb.database.updater.versions.updater_20261117 import (
    DATE_FIELDS_BY_COLLECTION,
    Update20261117,
    build_calendar_date_filter,
    build_calendar_date_pipeline,
    convert_calendar_dates,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261117
DATABASE_NAME: str = 'cmdb-unit'
FIELD: str = 'risk_assessment_date'
CALENDAR_PARTS: int = 3


def _build_stubbed_updater(modified: int = 0) -> Any:
    """The updater with a stubbed database manager reporting the given modified count per update"""
    updater = Update20261117.__new__(Update20261117)
    updater.dbm = MagicMock()
    updater.dbm.update_many_raw.return_value = MagicMock(modified_count=modified)
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def test_the_frozen_literals_match_the_models() -> None:
    """Both ISMS collections and every date field their models declare today"""
    assert DATE_FIELDS_BY_COLLECTION == {
        IsmsRiskAssessment.COLLECTION: IsmsRiskAssessment.DATE_FIELDS,
        IsmsControlMeasureAssignment.COLLECTION: IsmsControlMeasureAssignment.DATE_FIELDS,
    }


def test_the_filter_selects_an_object_of_three_whole_numbers_in_range() -> None:
    """Every part typed and bounded; the key count checked only on an object"""
    criteria = build_calendar_date_filter(FIELD)

    assert criteria[FIELD] == {'$type': 'object'}
    assert criteria[f'{FIELD}.year'] == {'$type': ['int', 'long'], '$gte': 1, '$lte': 9999}
    assert criteria[f'{FIELD}.month'] == {'$type': ['int', 'long'], '$gte': 1, '$lte': 12}
    assert criteria[f'{FIELD}.day'] == {'$type': ['int', 'long'], '$gte': 1, '$lte': 31}
    assert criteria['$expr']['$cond']['then'] == {'$eq': [{'$size': {'$objectToArray': f'${FIELD}'}}, CALENDAR_PARTS]}
    assert criteria['$expr']['$cond']['else'] is False


def test_the_pipeline_keeps_the_object_when_the_day_rolls_over() -> None:
    """The built date only when it reads back as sent; else the field itself"""
    expression = build_calendar_date_pipeline(FIELD)[0]['$set'][FIELD]['$let']

    assert expression['vars']['built']['$dateFromParts']['timezone'] == 'UTC'
    assert expression['in']['$cond']['then'] == '$$built'
    assert expression['in']['$cond']['else'] == f'${FIELD}'


def test_convert_sends_a_raw_pipeline_update() -> None:
    """A pipeline update cannot be wrapped in an operator"""
    dbm = MagicMock()
    dbm.update_many_raw.return_value = MagicMock(modified_count=2)

    assert convert_calendar_dates(dbm, DATABASE_NAME, IsmsRiskAssessment.COLLECTION, FIELD) == 2
    dbm.update_many_raw.assert_called_once_with(IsmsRiskAssessment.COLLECTION, DATABASE_NAME,
                                                build_calendar_date_filter(FIELD), build_calendar_date_pipeline(FIELD))


def test_every_field_is_converted_before_the_version_moves() -> None:
    """Six passes, then the bump"""
    updater = _build_stubbed_updater(modified=1)

    updater.start_update()

    assert updater.dbm.update_many_raw.call_count == sum(len(fields) for fields in DATE_FIELDS_BY_COLLECTION.values())
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_run_converting_nothing_logs_nothing() -> None:
    """What a re-run looks like"""
    with patch.object(module, 'LOGGER') as logger:
        _build_stubbed_updater().start_update()

    logger.info.assert_not_called()


def test_a_failure_is_wrapped_and_keeps_the_version() -> None:
    """The exception itself is carried; the next start retries"""
    updater = _build_stubbed_updater()
    failure = RuntimeError('boom')
    updater.dbm.update_many_raw.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()


def test_the_metadata() -> None:
    """The date in its name and a description"""
    updater = Update20261117.__new__(Update20261117)

    assert updater.creation_date() == CREATION_DATE
    assert updater.description().strip()
