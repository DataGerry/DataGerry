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
Unit tests for cmdb.database.updater.versions.updater_20260907

Covers the pieces in isolation with a stubbed database manager: the type-based selection that is the
whole of the migration's re-run safety, the pipeline shape (in particular the two arms that keep an
unreadable value from being nulled), the set of collections and fields it touches, and
start_update's orchestration + error wrapping.

The end-to-end behaviour against a real MongoDB - including the double run and the data it must not
destroy - is covered by tests/integration/database/test_integration_updater_20260907.py, and the
metadata contract by the shared parametrized test in test_version_updaters
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260907 import (
    DATE_FIELDS_BY_COLLECTION,
    Update20260907,
    build_date_conversion_pipeline,
    build_wrapped_date_filter,
    convert_wrapped_dates,
)
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.updater.versions.updater_20260907'
DB_NAME: str = 'testdb'
FIELD: str = 'risk_assessment_date'


def _dbm(modified: int = 0) -> MagicMock:
    """Builds a database-manager stub whose update_many reports the given modified count"""
    dbm = MagicMock()
    dbm.update_many.return_value = MagicMock(modified_count=modified)

    return dbm


class TestScope:
    """What the migration touches, taken from the models rather than repeated here."""

    def test_covers_both_isms_collections_that_store_dates(self) -> None:
        """Both models declare date fields, so both collections hold wrapped values to convert."""
        assert set(DATE_FIELDS_BY_COLLECTION) == {
            IsmsRiskAssessment.COLLECTION,
            IsmsControlMeasureAssignment.COLLECTION,
        }

    def test_takes_the_fields_from_the_models(self) -> None:
        """
        A model gaining a date field must not be able to leave this migration behind.

        Reading DATE_FIELDS instead of listing the six names is what makes that impossible.
        """
        assert DATE_FIELDS_BY_COLLECTION[IsmsRiskAssessment.COLLECTION] is IsmsRiskAssessment.DATE_FIELDS
        assert DATE_FIELDS_BY_COLLECTION[IsmsControlMeasureAssignment.COLLECTION] is (
            IsmsControlMeasureAssignment.DATE_FIELDS
        )


class TestSelection:
    """Selecting by BSON type is the whole of the re-run safety."""

    def test_selects_only_a_field_still_holding_a_sub_document(self) -> None:
        """
        A converted field is a date and no longer matches, which is what makes a re-run a no-op.

        Matching on the inner '$date' key instead would have kept matching after the conversion.
        """
        assert build_wrapped_date_filter(FIELD) == {FIELD: {'$type': 'object'}}


class TestPipeline:
    """The update pipeline, whose two fallback arms are why the conversion cannot lose data."""

    def test_reads_the_wrapper_key_through_get_field(self) -> None:
        """
        The inner key starts with a '$' and cannot be written as a field path.

        '$risk_assessment_date.$date' is not a legal path, so $getField with a $literal is the only
        way to reach the value.
        """
        stage = build_date_conversion_pipeline(FIELD)[0]['$set'][FIELD]

        assert stage['$convert']['input'] == {
            '$getField': {'field': {'$literal': '$date'}, 'input': f'${FIELD}'},
        }

    def test_converts_to_a_date(self) -> None:
        """$convert reads both an epoch number and a timestamp string."""
        stage = build_date_conversion_pipeline(FIELD)[0]['$set'][FIELD]

        assert stage['$convert']['to'] == 'date'

    def test_keeps_the_original_value_on_error_and_on_null(self) -> None:
        """
        The two arms that make the migration non-destructive.

        A sub-document that is not a wrapper, or a wrapper whose payload cannot be read, is left
        exactly as it was - nulling it would destroy the only evidence of what was stored.
        """
        stage = build_date_conversion_pipeline(FIELD)[0]['$set'][FIELD]

        assert stage['$convert']['onError'] == f'${FIELD}'
        assert stage['$convert']['onNull'] == f'${FIELD}'


class TestConvertWrappedDates:
    """The single-field conversion call."""

    def test_sends_the_pipeline_as_a_plain_update(self) -> None:
        """
        A pipeline update must not be wrapped in a '$set' operator.

        update_many wraps its update by default, which would make the pipeline an invalid update
        document.
        """
        dbm = _dbm()

        convert_wrapped_dates(dbm, DB_NAME, IsmsRiskAssessment.COLLECTION, FIELD)

        dbm.update_many.assert_called_once_with(
            IsmsRiskAssessment.COLLECTION,
            DB_NAME,
            build_wrapped_date_filter(FIELD),
            build_date_conversion_pipeline(FIELD),
            plain=True,
        )

    def test_reports_how_many_documents_were_rewritten(self) -> None:
        """The count is what start_update logs, so an operator can see the migration did something."""
        assert convert_wrapped_dates(_dbm(modified=3), DB_NAME, IsmsRiskAssessment.COLLECTION, FIELD) == 3


class TestStartUpdate:
    """The orchestration: every field of both collections, then the version bump."""

    def test_converts_every_declared_field_before_bumping_the_version(self) -> None:
        """
        One pass per field, and the version is bumped only after all of them.

        An interrupted run therefore keeps its version, so the next start resumes with the fields it
        had not reached.
        """
        update = MagicMock()
        expected_calls = sum(len(fields) for fields in DATE_FIELDS_BY_COLLECTION.values())

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=1) as mock_convert:
            Update20260907.start_update(update)

        assert mock_convert.call_count == expected_calls
        update.increase_updater_version.assert_called_once_with(update.creation_date.return_value)

    def test_logs_nothing_for_a_collection_that_needs_no_conversion(self) -> None:
        """A database already migrated runs silently, which is what a re-run looks like."""
        update = MagicMock()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=0):
            with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
                Update20260907.start_update(update)

        mock_logger.info.assert_not_called()

    def test_wraps_a_failure_in_an_updater_exception(self) -> None:
        """
        The version is not bumped when a conversion fails, so the next start retries.

        UpdaterException is what the DatabaseUpdater reports on, rather than a raw pymongo error.
        """
        update = MagicMock()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', side_effect=RuntimeError('boom')):
            with pytest.raises(UpdaterException):
                Update20260907.start_update(update)

        update.increase_updater_version.assert_not_called()
