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
these literal strings) and the build_error factory's contract: always emits the three top-level
keys, defaults details to a fresh empty dict for None / explicit {}, preserves non-empty
details, and returns independent dicts per call so callers can mutate safely. Inherited
is_valid / (str, Enum) semantics are covered by test_base_str_enum.py
"""
from typing import Any

from cmdb.utils.validation_error import ValidationErrorKey, build_error
# -------------------------------------------------------------------------------------------------------------------- #


SAMPLE_CODE: str = 'sample_code'
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
    assert ValidationErrorKey.CODE == 'code'
    assert ValidationErrorKey.MESSAGE == 'message'
    assert ValidationErrorKey.DETAILS == 'details'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  build_error                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_error_emits_all_three_top_level_keys() -> None:
    """The returned dict always has CODE, MESSAGE and DETAILS keys (DETAILS is never omitted)"""
    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE)

    assert set(error.keys()) == {
        ValidationErrorKey.CODE,
        ValidationErrorKey.MESSAGE,
        ValidationErrorKey.DETAILS,
    }


def test_build_error_defaults_details_to_empty_dict_when_argument_is_none() -> None:
    """Omitting details (or passing None) yields an empty DETAILS dict rather than None"""
    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE)

    assert error[ValidationErrorKey.DETAILS] == {}


def test_build_error_defaults_details_to_empty_dict_when_argument_is_empty_dict() -> None:
    """Passing an explicit empty dict still yields an empty DETAILS dict"""
    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE, {})

    assert error[ValidationErrorKey.DETAILS] == {}


def test_build_error_preserves_non_empty_details_unchanged() -> None:
    """A non-empty details dict is propagated through verbatim"""
    details: dict[str, Any] = {'object_id': 42, 'ip_address': '10.0.0.5'}

    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE, details)

    assert error[ValidationErrorKey.DETAILS] == {'object_id': 42, 'ip_address': '10.0.0.5'}


def test_build_error_preserves_arbitrary_value_types_in_details() -> None:
    """Detail values may be any type (lists, nested dicts, None, ints) — none are coerced"""
    details: dict[str, Any] = {
        'count': 3,
        'references': [{'public_id': 1}, {'public_id': 2}],
        'note': None,
    }

    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE, details)

    assert error[ValidationErrorKey.DETAILS] == details


def test_build_error_copies_code_and_message_into_envelope() -> None:
    """The provided code and message are stored under their keys verbatim"""
    error = build_error(SAMPLE_CODE, SAMPLE_MESSAGE)

    assert error[ValidationErrorKey.CODE] == SAMPLE_CODE
    assert error[ValidationErrorKey.MESSAGE] == SAMPLE_MESSAGE


def test_build_error_returns_independent_dict_per_call_for_default_details() -> None:
    """
    Each call returns a fresh outer dict; mutating one does not leak into the next

    Protects against a future refactor that introduces a shared mutable default (e.g. a module
    level _EMPTY constant) for the details fallback
    """
    first = build_error(SAMPLE_CODE, SAMPLE_MESSAGE)
    first[ValidationErrorKey.DETAILS]['injected'] = 'oops'

    second = build_error(SAMPLE_CODE, SAMPLE_MESSAGE)

    assert second[ValidationErrorKey.DETAILS] == {}
