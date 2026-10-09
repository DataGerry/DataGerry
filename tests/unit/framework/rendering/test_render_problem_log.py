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
Unit tests for cmdb.framework.rendering.render_problem_log.RenderProblemLog

Pure tests: a real logger captured through caplog, no managers and no database. Pins the two halves
the class keeps apart - the per-object record and the once-per-render log - and the object the record
defaults to
"""
import logging
from typing import Any

import pytest

from cmdb.framework.rendering.render_constants import RenderProblemCode, RenderProblemKey
from cmdb.framework.rendering.render_problem_log import RenderProblemLog
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER_NAME: str = 'tests.render_problem_log'

FIRST_OBJECT_ID: int = 41
SECOND_OBJECT_ID: int = 42

SECTION_NAME: str = 'main'
FIELD_NAME: str = 'hostname'
LINK_NAME: str = 'monitoring'
TYPE_ID: int = 7
OTHER_TYPE_ID: int = 8

MESSAGE: str = 'Field %s could not be merged'


def _problem_log() -> RenderProblemLog:
    """A log writing to the test logger."""
    return RenderProblemLog(logging.getLogger(LOGGER_NAME))


def _entry(code: RenderProblemCode = RenderProblemCode.FIELD_MERGE_FAILED, **where: str | None) -> dict[str, Any]:
    """The record entry a report with these arguments produces."""
    return {
        RenderProblemKey.CODE.value: code.value,
        RenderProblemKey.SECTION.value: where.get('section'),
        RenderProblemKey.FIELD.value: where.get('field'),
        RenderProblemKey.EXTERNAL_LINK.value: where.get('external_link'),
    }


def _report(problem_log: RenderProblemLog, **kwargs: Any) -> None:
    """Reports a merge failure of FIELD_NAME with the given keyword arguments."""
    problem_log.report(RenderProblemCode.FIELD_MERGE_FAILED, MESSAGE, FIELD_NAME, field=FIELD_NAME, **kwargs)


class TestRecord:
    """Where a report is recorded."""

    def test_a_report_is_recorded_for_the_object_being_rendered(self) -> None:
        """The default target is the object result() is rendering"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            _report(problem_log, section=SECTION_NAME)

        assert problem_log.problems_for(FIRST_OBJECT_ID) == [_entry(section=SECTION_NAME, field=FIELD_NAME)]

    def test_named_objects_are_recorded_instead_of_the_current_one(self) -> None:
        """A problem found before rendering starts names the objects it costs"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            _report(problem_log, object_ids=[SECOND_OBJECT_ID])

        assert problem_log.problems_for(FIRST_OBJECT_ID) == []
        assert problem_log.problems_for(SECOND_OBJECT_ID) == [_entry(field=FIELD_NAME)]

    def test_empty_object_ids_record_nothing_but_still_log(self, caplog) -> None:
        """A problem that costs the render nothing visible is logged, never flagged"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME), problem_log.rendering(FIRST_OBJECT_ID):
            _report(problem_log, object_ids=())

        assert not problem_log.problems_by_object
        assert FIELD_NAME in caplog.text

    def test_a_report_outside_a_render_is_only_logged(self, caplog) -> None:
        """No object being rendered and none named: nothing to flag"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _report(problem_log)

        assert not problem_log.problems_by_object
        assert FIELD_NAME in caplog.text

    def test_the_same_problem_is_recorded_once_per_object(self) -> None:
        """Reporting the same loss twice for one object leaves one entry"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            _report(problem_log)
            _report(problem_log)

        assert len(problem_log.problems_for(FIRST_OBJECT_ID)) == 1

    def test_every_object_that_hits_a_problem_records_it(self) -> None:
        """The record is per object, even where the log is deduplicated"""
        problem_log = _problem_log()

        for object_id in (FIRST_OBJECT_ID, SECOND_OBJECT_ID):
            with problem_log.rendering(object_id):
                _report(problem_log)

        assert problem_log.problems_for(FIRST_OBJECT_ID) == problem_log.problems_for(SECOND_OBJECT_ID) != []

    def test_an_entry_carries_the_external_link(self) -> None:
        """A link failure names the link, the one place it can be told apart"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            problem_log.report(RenderProblemCode.EXTERNAL_LINK_FAILED, MESSAGE, LINK_NAME, external_link=LINK_NAME)

        assert problem_log.problems_for(FIRST_OBJECT_ID) == [
            _entry(RenderProblemCode.EXTERNAL_LINK_FAILED, external_link=LINK_NAME)
        ]

    def test_an_entry_carries_no_exception_text(self) -> None:
        """Only the four location keys - the message and its arguments stay in the log"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            _report(problem_log)

        assert set(problem_log.problems_for(FIRST_OBJECT_ID)[0]) == {key.value for key in RenderProblemKey}


class TestRecordDirectly:
    """record(), which hands a nested render's problems up."""

    def test_record_adds_to_the_current_object(self) -> None:
        """Without an object id the current object receives the entries"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            problem_log.record([_entry(field=FIELD_NAME)])

        assert problem_log.problems_for(FIRST_OBJECT_ID) == [_entry(field=FIELD_NAME)]

    def test_record_without_an_object_does_nothing(self) -> None:
        """Outside a render there is no object to hand the entries to"""
        problem_log = _problem_log()

        problem_log.record([_entry(field=FIELD_NAME)])

        assert not problem_log.problems_by_object

    def test_record_stores_copies(self) -> None:
        """Changing the handed-in entry afterwards does not change the record"""
        problem_log = _problem_log()
        entry: dict[str, Any] = _entry(field=FIELD_NAME)

        problem_log.record([entry], FIRST_OBJECT_ID)
        entry[RenderProblemKey.FIELD.value] = SECTION_NAME

        assert problem_log.problems_for(FIRST_OBJECT_ID) == [_entry(field=FIELD_NAME)]

    def test_problems_for_answers_copies(self) -> None:
        """A caller mutating the answer cannot reach the record"""
        problem_log = _problem_log()
        problem_log.record([_entry(field=FIELD_NAME)], FIRST_OBJECT_ID)

        problem_log.problems_for(FIRST_OBJECT_ID)[0][RenderProblemKey.FIELD.value] = SECTION_NAME

        assert problem_log.problems_for(FIRST_OBJECT_ID) == [_entry(field=FIELD_NAME)]


class TestLog:
    """What reaches the log, and how often."""

    def test_the_same_problem_is_logged_once(self, caplog) -> None:
        """A hundred objects through one broken definition are one line"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            for object_id in (FIRST_OBJECT_ID, SECOND_OBJECT_ID):
                with problem_log.rendering(object_id):
                    _report(problem_log, log_key=(TYPE_ID,))

        assert len(caplog.records) == 1

    def test_a_different_log_key_is_logged_again(self, caplog) -> None:
        """The same field name on two types is two problems"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _report(problem_log, log_key=(TYPE_ID,))
            _report(problem_log, log_key=(OTHER_TYPE_ID,))

        assert len(caplog.records) == 2

    def test_a_warning_carries_no_traceback(self, caplog) -> None:
        """A configuration problem is read from its message"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _report(problem_log)

        assert caplog.records[0].levelno == logging.WARNING
        assert not caplog.records[0].exc_info

    def test_an_error_carries_the_traceback(self, caplog) -> None:
        """A failure of the database or the code is read from its stack"""
        problem_log = _problem_log()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            try:
                raise RuntimeError(FIELD_NAME)
            except RuntimeError:
                _report(problem_log, log_level=logging.ERROR)

        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].exc_info is not None


class TestRendering:
    """The current-object mark."""

    def test_the_mark_is_set_inside_the_block(self) -> None:
        """Inside the block, the object is current"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            assert problem_log.current_object_id == FIRST_OBJECT_ID

    def test_the_mark_is_cleared_after_the_block(self) -> None:
        """After the block, no object is current"""
        problem_log = _problem_log()

        with problem_log.rendering(FIRST_OBJECT_ID):
            pass

        assert problem_log.current_object_id is None

    def test_the_mark_is_cleared_when_the_block_raises(self) -> None:
        """A render that fails does not leave its object current for the next one"""
        problem_log = _problem_log()

        with pytest.raises(RuntimeError), problem_log.rendering(FIRST_OBJECT_ID):
            raise RuntimeError(FIELD_NAME)

        assert problem_log.current_object_id is None
