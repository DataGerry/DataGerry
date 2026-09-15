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
Unit tests for cmdb.models.isms_model.isms_control_measure_assignment

Covers the two dates - the half of this model that changed when the ISMS date fields became real BSON
dates - and the three error arms the routes map to their responses. The assignment shares its date
rules with IsmsRiskAssessment (same shapes in, same refusal on an unreadable value), so the two
models are pinned the same way; see test_isms_risk_assessment for the reasoning behind each rule

Pure tests: no Mongo, no Flask
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.class_schema.isms_model.isms_control_measure_assignment_schema import (
    get_isms_control_measure_assignment_schema,
)
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.errors.models.isms_control_measure_assignment import (
    IsmsControlMeasureAssignmentInitError,
    IsmsControlMeasureAssignmentInitFromDataError,
    IsmsControlMeasureAssignmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CMA_ID: int = 55
CONTROL_MEASURE_ID: int = 12
RISK_ASSESSMENT_ID: int = 42

STAMP_MILLIS: int = 1600000000000
STAMP: datetime = datetime(2020, 9, 13, 12, 26, 40, tzinfo=timezone.utc)


def _assignment_data(**overrides: Any) -> dict[str, Any]:
    """Builds a complete IsmsControlMeasureAssignment document, overridable per test"""
    data: dict[str, Any] = {
        'public_id': CMA_ID,
        'control_measure_id': CONTROL_MEASURE_ID,
        'risk_assessment_id': RISK_ASSESSMENT_ID,
        'planned_implementation_date': {'$date': STAMP_MILLIS},
        'implementation_status': 3,
        'finished_implementation_date': None,
        'priority': 1,
        'responsible_for_implementation_id_ref_type': 'PERSON',
        'responsible_for_implementation_id': 9,
    }
    data.update(overrides)

    return data


class TestDateFields:
    """The two dates follow the same rules as the assessment's four."""

    def test_declares_both_date_fields(self) -> None:
        """DATE_FIELDS is what GenericManager normalises on the raw-dict write paths."""
        assert IsmsControlMeasureAssignment.DATE_FIELDS == (
            'planned_implementation_date', 'finished_implementation_date',
        )

    def test_the_declared_dates_are_the_schema_s_date_typed_fields(self) -> None:
        """
        A date field the schema allows but DATE_FIELDS omits would be stored as a wrapper again.

        Read from a freshly built schema, because building a Cerberus Validator rewrites the
        'anyof_type' shorthand into its expanded form in the dict it was handed - so the class
        attribute's shape depends on whether the REST app has been built in this process.
        """
        schema_date_keys = {
            key for key, rules in get_isms_control_measure_assignment_schema().items()
            if 'datetime' in rules.get('anyof_type', [])
        }

        assert schema_date_keys == set(IsmsControlMeasureAssignment.DATE_FIELDS)

    def test_reads_the_wrapper_the_frontend_sends(self) -> None:
        """A payload carries a date as {'$date': <epoch millis>}."""
        assignment = IsmsControlMeasureAssignment.from_data(_assignment_data())

        assert assignment.planned_implementation_date == STAMP

    def test_reads_a_stored_date_unchanged(self) -> None:
        """A document read back out of MongoDB already carries a real date."""
        assignment = IsmsControlMeasureAssignment.from_data(
            _assignment_data(planned_implementation_date=STAMP)
        )

        assert assignment.planned_implementation_date is STAMP

    def test_reads_an_emptied_date_as_none(self) -> None:
        """Both dates are optional: an emptied widget means 'no date'."""
        assignment = IsmsControlMeasureAssignment.from_data(
            _assignment_data(finished_implementation_date='')
        )

        assert assignment.finished_implementation_date is None

    def test_refuses_an_unreadable_date_instead_of_guessing_one(self) -> None:
        """Fuzzy parsing turned a note into a date assembled from today's values."""
        with pytest.raises(IsmsControlMeasureAssignmentInitFromDataError) as err:
            IsmsControlMeasureAssignment.from_data(
                _assignment_data(finished_implementation_date='when the budget arrives')
            )

        assert 'finished_implementation_date' in str(err.value)


class TestRoundTrip:
    """from_data and to_json are inverses over the stored document."""

    def test_round_trips_a_document_losslessly(self) -> None:
        """The read routes answer with to_json(from_data(document))."""
        data = _assignment_data(planned_implementation_date=STAMP)

        assert IsmsControlMeasureAssignment.to_json(
            IsmsControlMeasureAssignment.from_data(dict(data))
        ) == data


class TestErrorHandling:
    """Each of the three entry points reports its own failure type."""

    def test_a_failing_init_raises_the_init_error(self) -> None:
        """CmdbDAO casts the public_id, so a missing one fails inside __init__."""
        data = _assignment_data()
        data['public_id'] = None

        with pytest.raises(IsmsControlMeasureAssignmentInitError):
            IsmsControlMeasureAssignment(**data)

    def test_from_data_wraps_a_failing_init(self) -> None:
        """A document without a public_id cannot become an assignment."""
        data = _assignment_data()
        del data['public_id']

        with pytest.raises(IsmsControlMeasureAssignmentInitFromDataError):
            IsmsControlMeasureAssignment.from_data(data)

    def test_to_json_wraps_a_failing_conversion(self) -> None:
        """Handed something that is not an assignment, it reports a conversion failure."""
        class _NotAnAssignment:
            """Carries none of the attributes to_json reads."""

        with pytest.raises(IsmsControlMeasureAssignmentToJsonError):
            IsmsControlMeasureAssignment.to_json(_NotAnAssignment())
