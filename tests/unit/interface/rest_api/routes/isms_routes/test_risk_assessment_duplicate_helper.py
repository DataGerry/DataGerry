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
Unit tests for cmdb.interface.rest_api.routes.isms_routes.risk_assessment_duplicate_helper

  - the target ids: each a distinct whole number from 1 to the largest 8-byte integer, in the order sent; every
    invalid token and every repeated id named in one 400
  - the source: 404 when its id is not stored, the manager's get error passed on
  - the source's assignments: read once, a failed read its own 400
  - the copies: re-pointed at the duplicate, without the source's ids, the originals untouched

Pure tests: an app context for ``abort``, the manager a stub - no Mongo
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerGetError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG,
    DUPLICATE_SOURCE_NOT_FOUND_MSG,
    DUPLICATE_TARGETS_INVALID_REASON,
    DUPLICATE_TARGETS_REASON_SEPARATOR,
    DUPLICATE_TARGETS_REFUSED_MSG,
    DUPLICATE_TARGETS_REPEATED_REASON,
    MAX_DUPLICATE_TARGET_ID,
    MIN_DUPLICATE_TARGET_ID,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_duplicate_helper import (
    abort_if_duplicate_source_missing,
    copied_assignments,
    parse_duplicate_target_ids,
    read_source_assignments,
)
# -------------------------------------------------------------------------------------------------------------------- #

SOURCE_ID: int = 31
DUPLICATE_ID: int = 32
FIRST_ASSIGNMENT_ID: int = 41
SECOND_ASSIGNMENT_ID: int = 42
FIRST_MEASURE_ID: int = 51
SECOND_MEASURE_ID: int = 52
SUPERSCRIPT_TWO: str = '²'
ARABIC_INDIC_THREE: str = '٣'
LARGEST_8_BYTE_INTEGER: int = 2 ** 63 - 1

PUBLIC_ID_KEY: str = ControlMeasureAssignmentKey.PUBLIC_ID.value
RISK_ASSESSMENT_KEY: str = ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value
CONTROL_MEASURE_KEY: str = ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value


@pytest.fixture(name='flask_context', autouse=True)
def fixture_flask_context():
    """abort() needs an application context"""
    with Flask(__name__).app_context():
        yield


def _refusal(function: Any, *args: Any) -> HTTPException:
    """The HTTPException a helper aborts with"""
    with pytest.raises(HTTPException) as caught:
        function(*args)

    return caught.value


def _invalid(tokens: list[str]) -> str:
    """The reason naming the invalid tokens"""
    return DUPLICATE_TARGETS_INVALID_REASON.format(
        minimum=MIN_DUPLICATE_TARGET_ID, maximum=MAX_DUPLICATE_TARGET_ID, tokens=tokens,
    )


def _refused(*reasons: str) -> str:
    """The whole 400 message"""
    return DUPLICATE_TARGETS_REFUSED_MSG.format(reasons=DUPLICATE_TARGETS_REASON_SEPARATOR.join(reasons))


def _assignment(public_id: int, measure_id: int) -> dict[str, Any]:
    """A stored assignment of the source"""
    return {PUBLIC_ID_KEY: public_id, RISK_ASSESSMENT_KEY: SOURCE_ID, CONTROL_MEASURE_KEY: measure_id}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     TARGET IDS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestParseDuplicateTargetIds:
    """The <ids> path segment"""

    def test_ids_in_the_order_sent(self) -> None:
        """Not sorted"""
        assert parse_duplicate_target_ids('5,3,4') == [5, 3, 4]

    def test_one_id(self) -> None:
        """No separator at all"""
        assert parse_duplicate_target_ids('7') == [7]

    def test_whitespace_around_a_token_is_ignored(self) -> None:
        """'1, 2' as an encoded space reaches the route"""
        assert parse_duplicate_target_ids(' 1 , 2 ') == [1, 2]

    def test_the_bounds_are_accepted(self) -> None:
        """1 and the largest 8-byte integer"""
        assert parse_duplicate_target_ids(f'{MIN_DUPLICATE_TARGET_ID},{MAX_DUPLICATE_TARGET_ID}') == [
            MIN_DUPLICATE_TARGET_ID, MAX_DUPLICATE_TARGET_ID,
        ]

    def test_the_largest_id_is_the_largest_8_byte_integer(self) -> None:
        """What MongoDB can store"""
        assert MAX_DUPLICATE_TARGET_ID == LARGEST_8_BYTE_INTEGER

    @pytest.mark.parametrize('token', [
        'abc', '-2', '0', '+3', '1.5', '', SUPERSCRIPT_TWO, ARABIC_INDIC_THREE, str(MAX_DUPLICATE_TARGET_ID + 1),
    ])
    def test_an_invalid_token_is_refused(self, token: str) -> None:
        """Words, signs, zero, decimals, empty, non-ASCII digits, too large - each a 400 naming it"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, f'1,{token}')

        assert (refusal.code, refusal.description) == (HTTPStatus.BAD_REQUEST, _refused(_invalid([token])))

    def test_every_invalid_token_is_named_once_in_order(self) -> None:
        """Not only the first"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, '1,abc,-2')

        assert refusal.description == _refused(_invalid(['abc', '-2']))

    def test_a_repeated_id_is_refused(self) -> None:
        """It would store two duplicates on one target"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, '5,6,5')

        assert (refusal.code, refusal.description) == (
            HTTPStatus.BAD_REQUEST, _refused(DUPLICATE_TARGETS_REPEATED_REASON.format(ids=[5])))

    def test_a_repeat_spelled_differently_is_still_a_repeat(self) -> None:
        """'05' and '5' are one target"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, '5,05')

        assert refusal.description == _refused(DUPLICATE_TARGETS_REPEATED_REASON.format(ids=[5]))

    def test_invalid_tokens_and_repeats_are_named_in_one_refusal(self) -> None:
        """Both reasons, invalid first"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, '4,x,4')

        assert refusal.description == _refused(
            _invalid(['x']), DUPLICATE_TARGETS_REPEATED_REASON.format(ids=[4]),
        )

    def test_only_separators_is_refused(self) -> None:
        """Every token empty: nothing to duplicate onto"""
        refusal: HTTPException = _refusal(parse_duplicate_target_ids, ',')

        assert refusal.description == _refused(_invalid(['', '']))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       SOURCE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAbortIfDuplicateSourceMissing:
    """The body's public_id has to name a stored RiskAssessment"""

    def test_a_stored_source_passes(self) -> None:
        """One existence read of the id"""
        manager = MagicMock(spec=RiskAssessmentManager)
        manager.find_existing_public_ids.return_value = {SOURCE_ID}

        abort_if_duplicate_source_missing(manager, SOURCE_ID)

        manager.find_existing_public_ids.assert_called_once_with([SOURCE_ID])

    def test_a_missing_source_is_a_404(self) -> None:
        """Naming the id"""
        manager = MagicMock(spec=RiskAssessmentManager)
        manager.find_existing_public_ids.return_value = set()

        refusal: HTTPException = _refusal(abort_if_duplicate_source_missing, manager, SOURCE_ID)

        assert (refusal.code, refusal.description) == (
            HTTPStatus.NOT_FOUND, DUPLICATE_SOURCE_NOT_FOUND_MSG.format(public_id=SOURCE_ID))

    def test_a_failed_read_is_passed_on(self) -> None:
        """The route's table answers it"""
        manager = MagicMock(spec=RiskAssessmentManager)
        manager.find_existing_public_ids.side_effect = RiskAssessmentManagerGetError('down')

        with pytest.raises(RiskAssessmentManagerGetError):
            abort_if_duplicate_source_missing(manager, SOURCE_ID)


class TestReadSourceAssignments:
    """The source's ControlMeasureAssignments, read once"""

    def test_the_assignments_of_the_source(self) -> None:
        """Read from the assignment collection by the source's id"""
        stored: list[dict[str, Any]] = [_assignment(FIRST_ASSIGNMENT_ID, FIRST_MEASURE_ID)]
        manager = MagicMock(spec=RiskAssessmentManager)
        manager.get_many_from_other_collection.return_value = stored

        assert read_source_assignments(manager, SOURCE_ID) == stored
        manager.get_many_from_other_collection.assert_called_once_with(
            IsmsControlMeasureAssignment.COLLECTION, criteria={RISK_ASSESSMENT_KEY: SOURCE_ID},
        )

    def test_a_failed_read_is_its_own_400(self) -> None:
        """Not the generic 500"""
        manager = MagicMock(spec=RiskAssessmentManager)
        manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')

        refusal: HTTPException = _refusal(read_source_assignments, manager, SOURCE_ID)

        assert (refusal.code, refusal.description) == (HTTPStatus.BAD_REQUEST, DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       COPIES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCopiedAssignments:
    """What one duplicate stores"""

    def test_each_copy_points_at_the_duplicate_without_an_id(self) -> None:
        """Every other key carried over"""
        originals: list[dict[str, Any]] = [
            _assignment(FIRST_ASSIGNMENT_ID, FIRST_MEASURE_ID), _assignment(SECOND_ASSIGNMENT_ID, SECOND_MEASURE_ID),
        ]

        assert copied_assignments(originals, DUPLICATE_ID) == [
            {RISK_ASSESSMENT_KEY: DUPLICATE_ID, CONTROL_MEASURE_KEY: FIRST_MEASURE_ID},
            {RISK_ASSESSMENT_KEY: DUPLICATE_ID, CONTROL_MEASURE_KEY: SECOND_MEASURE_ID},
        ]

    def test_the_originals_are_untouched(self) -> None:
        """They are copied again for the next duplicate"""
        original: dict[str, Any] = _assignment(FIRST_ASSIGNMENT_ID, FIRST_MEASURE_ID)

        copied_assignments([original], DUPLICATE_ID)

        assert original == _assignment(FIRST_ASSIGNMENT_ID, FIRST_MEASURE_ID)

    def test_two_duplicates_get_separate_documents(self) -> None:
        """An insert adds keys to what it stores - one duplicate's copy must not be another's"""
        originals: list[dict[str, Any]] = [_assignment(FIRST_ASSIGNMENT_ID, FIRST_MEASURE_ID)]

        first: list[dict[str, Any]] = copied_assignments(originals, DUPLICATE_ID)
        second: list[dict[str, Any]] = copied_assignments(originals, DUPLICATE_ID + 1)

        assert first[0] is not second[0]
        assert second[0][RISK_ASSESSMENT_KEY] == DUPLICATE_ID + 1

    def test_no_originals_no_copies(self) -> None:
        """copy_cma with a source that has none"""
        assert not copied_assignments([], DUPLICATE_ID)
