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
Unit tests for cmdb.utils.validation_error

Verifies the public wire-format string values on ValidationErrorKey (the frontend depends on
these literal strings) and the build_error factory's contract: always emits MESSAGE, adds the
DETAILS key only when a non-empty context dict is supplied, preserves non-empty details, and
returns independent dicts per call so callers can mutate safely. Inherited is_valid /
(str, Enum) semantics are covered by test_base_str_enum.py
"""
from typing import Any

from cmdb.utils.validation_error import ValidationErrorKey, build_error
# -------------------------------------------------------------------------------------------------------------------- #


SAMPLE_MESSAGE: str = 'sample human-readable message'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ValidationErrorKey                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validation_error_key_pins_wire_format_string_values() -> None:
    """
    Member string values must stay stable

    The frontend and any JSON consumers read these literal strings; renaming them is a wire
    break, not a refactor. Pin them here so an accidental rename fails loudly
    """
    assert ValidationErrorKey.MESSAGE == 'message'
    assert ValidationErrorKey.DETAILS == 'details'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  build_error                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_error_emits_only_message_when_no_details() -> None:
    """Without details the error is a bare {message} - the DETAILS key is omitted entirely"""
    error = build_error(SAMPLE_MESSAGE)

    assert error == {ValidationErrorKey.MESSAGE: SAMPLE_MESSAGE}


def test_build_error_omits_details_key_for_empty_dict() -> None:
    """Passing an explicit empty dict still omits the DETAILS key"""
    error = build_error(SAMPLE_MESSAGE, {})

    assert ValidationErrorKey.DETAILS not in error


def test_build_error_includes_non_empty_details_unchanged() -> None:
    """A non-empty details dict is propagated through verbatim under the DETAILS key"""
    details: dict[str, Any] = {'row_index': 2, 'first_row_index': 0}

    error = build_error(SAMPLE_MESSAGE, details)

    assert error[ValidationErrorKey.DETAILS] == {'row_index': 2, 'first_row_index': 0}


def test_build_error_preserves_arbitrary_value_types_in_details() -> None:
    """Detail values may be any type (ints, nested structures) — none are coerced"""
    details: dict[str, Any] = {'row_index': 3, 'nested': [{'a': 1}]}

    error = build_error(SAMPLE_MESSAGE, details)

    assert error[ValidationErrorKey.DETAILS] == details


def test_build_error_copies_message_into_envelope() -> None:
    """The provided message is stored under MESSAGE verbatim"""
    error = build_error(SAMPLE_MESSAGE)

    assert error[ValidationErrorKey.MESSAGE] == SAMPLE_MESSAGE


def test_build_error_returns_independent_dict_per_call() -> None:
    """
    Each call returns a fresh dict; mutating one does not leak into the next

    Protects against a future refactor that introduces a shared mutable object for the envelope
    """
    first = build_error(SAMPLE_MESSAGE)
    first['injected'] = 'oops'

    second = build_error(SAMPLE_MESSAGE)

    assert second == {ValidationErrorKey.MESSAGE: SAMPLE_MESSAGE}
