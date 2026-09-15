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
Unit tests for cmdb.framework.rack.rack_validator

Covers the height coercion table (including the bool trap - bool is an int subclass, so True would
pass as 1 without an explicit guard), and the presence / value split: the two sets must not overlap,
because the bulk importer runs only the value set and would otherwise report a missing required value
twice
"""
from typing import Any

import pytest

from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.framework.rack.rack_constants import RackLimits, RackValidationError
from cmdb.framework.rack.rack_validator import (
    coerce_rack_height,
    validate_rack_field_values,
    validate_rack_object,
    validate_rack_required_values,
)
# -------------------------------------------------------------------------------------------------------------------- #

VALID_NAME: str = 'rack-1'
VALID_HEIGHT: int = 42


def _rack(name: Any = VALID_NAME, height: Any = VALID_HEIGHT, omit: tuple[str, ...] = ()) -> dict[str, Any]:
    """Builds a Rack candidate; names in 'omit' are left out of the fields list entirely"""
    fields: list[dict[str, Any]] = []

    if RackField.NAME.value not in omit:
        fields.append({'name': RackField.NAME.value, 'value': name, 'type': 'text'})

    if RackField.HEIGHT.value not in omit:
        fields.append({'name': RackField.HEIGHT.value, 'value': height, 'type': 'number'})

    return {'type_id': 1, 'fields': fields}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                coerce_rack_height                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [
    (42, 42),
    (0, 0),
    (-3, -3),
    (42.0, 42),
    ('42', 42),
    ('42.0', 42),
    ('  7 ', 7),
], ids=str)
def test_coerce_rack_height_accepts_whole_numbers(value: Any, expected: int) -> None:
    """Ints, whole floats and strings holding either are coerced; range is not this function's job"""
    assert coerce_rack_height(value) == expected


@pytest.mark.parametrize('value', [3.5, '3.5', 'abc', '', None, [], {}, '4,5'], ids=str)
def test_coerce_rack_height_rejects_non_whole_numbers(value: Any) -> None:
    """Anything that is not a whole number coerces to None for the validators to report"""
    assert coerce_rack_height(value) is None


@pytest.mark.parametrize('value', [True, False], ids=str)
def test_coerce_rack_height_rejects_booleans(value: bool) -> None:
    """
    bool is an int subclass in Python

    Without an explicit guard True would coerce to 1 and pass as a one-U rack.
    """
    assert coerce_rack_height(value) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                         validate_rack_required_values                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_required_values_pass_for_a_complete_rack() -> None:
    """A rack carrying both values reports nothing"""
    assert validate_rack_required_values(_rack()) == []


@pytest.mark.parametrize('name', [None, ''], ids=str)
def test_required_values_report_an_absent_name(name: Any) -> None:
    """A name of None or '' is absent"""
    assert RackValidationError.MISSING_NAME.value in validate_rack_required_values(_rack(name=name))


def test_required_values_report_a_name_field_that_is_not_there_at_all() -> None:
    """A payload omitting the field entirely is the same as sending no value"""
    errors = validate_rack_required_values(_rack(omit=(RackField.NAME.value,)))

    assert RackValidationError.MISSING_NAME.value in errors


@pytest.mark.parametrize('height', [None, ''], ids=str)
def test_required_values_report_an_absent_height(height: Any) -> None:
    """A height of None or '' is absent"""
    assert RackValidationError.MISSING_HEIGHT.value in validate_rack_required_values(_rack(height=height))


def test_required_values_do_not_report_a_present_but_invalid_height() -> None:
    """
    0 is a present value, so it belongs to the value rules, not the presence rules

    This split is what keeps the importer from reporting the same problem twice.
    """
    assert validate_rack_required_values(_rack(height=0)) == []


def test_required_values_do_not_report_a_blank_name() -> None:
    """'   ' is present, so it is the value rules' concern"""
    assert validate_rack_required_values(_rack(name='   ')) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                           validate_rack_field_values                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_field_values_pass_for_a_valid_rack() -> None:
    """A valid rack reports nothing"""
    assert validate_rack_field_values(_rack()) == []


@pytest.mark.parametrize('name', ['   ', '\t', '\n '], ids=repr)
def test_field_values_reject_a_whitespace_only_name(name: str) -> None:
    """
    A whitespace-only name is what the importer's required-field check lets through

    _is_value_missing there treats only None and '' as missing.
    """
    assert validate_rack_field_values(_rack(name=name)) == [RackValidationError.BLANK_NAME.value]


@pytest.mark.parametrize('name, absent', [(None, True), ('', True)], ids=str)
def test_field_values_ignore_an_absent_name(name: Any, absent: bool) -> None:
    """An absent name is the presence rules' concern, not reported twice here"""
    assert validate_rack_field_values(_rack(name=name)) == []


@pytest.mark.parametrize('height', [0, -1, -99], ids=str)
def test_field_values_reject_a_non_positive_height(height: int) -> None:
    """A rack of zero or negative U makes no sense"""
    errors = validate_rack_field_values(_rack(height=height))

    assert errors == [
        RackValidationError.NON_POSITIVE_HEIGHT.format(minimum=RackLimits.MIN_HEIGHT, value=height)
    ]


@pytest.mark.parametrize('height', [3.5, 'abc', '3.5'], ids=str)
def test_field_values_reject_a_height_that_is_not_a_whole_number(height: Any) -> None:
    """Half-U heights and junk are rejected with the value echoed back"""
    assert validate_rack_field_values(_rack(height=height)) == [
        RackValidationError.INVALID_HEIGHT.format(value=height)
    ]


def test_field_values_accept_the_minimum_height() -> None:
    """The lower bound itself is valid"""
    assert validate_rack_field_values(_rack(height=RackLimits.MIN_HEIGHT)) == []


def test_field_values_accept_a_numeric_string_height() -> None:
    """A CSV import carries the height as a string; the value is still valid"""
    assert validate_rack_field_values(_rack(height='42')) == []


def test_field_values_have_no_upper_bound() -> None:
    """No maximum height is enforced yet, by decision"""
    assert validate_rack_field_values(_rack(height=100_000)) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_rack_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_validate_rack_object_runs_both_sets() -> None:
    """The REST entry point reports an absent name and a bad height together"""
    errors = validate_rack_object(_rack(name=None, height=0))

    assert RackValidationError.MISSING_NAME.value in errors
    assert RackValidationError.NON_POSITIVE_HEIGHT.format(
        minimum=RackLimits.MIN_HEIGHT, value=0
    ) in errors


def test_validate_rack_object_passes_a_valid_rack() -> None:
    """A valid rack produces no errors at all"""
    assert validate_rack_object(_rack()) == []


def test_validate_rack_object_tolerates_a_document_without_fields() -> None:
    """A drifted document must report the missing values, not raise"""
    errors = validate_rack_object({'type_id': 1})

    assert RackValidationError.MISSING_NAME.value in errors
    assert RackValidationError.MISSING_HEIGHT.value in errors
