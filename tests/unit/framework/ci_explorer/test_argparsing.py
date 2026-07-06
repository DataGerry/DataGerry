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
Unit tests for cmdb.framework.ci_explorer.argparsing
"""
import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.ci_explorer_model import NodeType
from cmdb.framework.ci_explorer.argparsing import (
    clamp_item_limit,
    parse_bool_arg,
    parse_int_list_filter,
    validate_node_type,
    validate_target_id,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_target_id                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_target_id_returns_value_when_set() -> None:
    """A valid integer flows through unchanged"""
    assert validate_target_id(42) == 42


def test_validate_target_id_aborts_400_when_none() -> None:
    """A missing target_id aborts with HTTP 400"""
    with pytest.raises(HTTPException) as exc:
        validate_target_id(None)
    assert exc.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_node_type                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value,expected', [
    ('CHILD', NodeType.CHILD),
    ('PARENT', NodeType.PARENT),
    ('BOTH', NodeType.BOTH),
])
def test_validate_node_type_accepts_every_member(value: str, expected: NodeType) -> None:
    """Every NodeType member's name parses to its enum value"""
    assert validate_node_type(value) is expected


def test_validate_node_type_aborts_400_for_unknown_value() -> None:
    """An unrecognised target_type aborts with HTTP 400"""
    with pytest.raises(HTTPException) as exc:
        validate_node_type('SIBLING')
    assert exc.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 parse_bool_arg                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_bool_arg_returns_default_for_none() -> None:
    """None returns the supplied default unchanged"""
    assert parse_bool_arg(None) is False
    assert parse_bool_arg(None, default=True) is True


def test_parse_bool_arg_returns_default_for_empty_string() -> None:
    """An empty string is treated as 'missing' and returns the default"""
    assert parse_bool_arg('', default=True) is True


@pytest.mark.parametrize('value', ['true', 'TRUE', 'True'])
def test_parse_bool_arg_returns_true_for_case_insensitive_true(value: str) -> None:
    """Any case-variant of 'true' returns True"""
    assert parse_bool_arg(value) is True


@pytest.mark.parametrize('value', ['false', 'FALSE', '0', '1', 'yes', 'no'])
def test_parse_bool_arg_returns_false_for_anything_else(value: str) -> None:
    """Anything other than 'true' (case-insensitive) returns False"""
    assert parse_bool_arg(value) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                clamp_item_limit                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_clamp_item_limit_returns_zero_for_none() -> None:
    """None collapses to 0 (=unlimited)"""
    assert clamp_item_limit(None) == 0


def test_clamp_item_limit_returns_zero_for_zero() -> None:
    """Zero is the 'unlimited' sentinel"""
    assert clamp_item_limit(0) == 0


def test_clamp_item_limit_passes_through_positive() -> None:
    """A positive integer is passed through unchanged"""
    assert clamp_item_limit(5) == 5


def test_clamp_item_limit_clamps_negative_to_zero() -> None:
    """Negative values clamp to 0 rather than raising"""
    assert clamp_item_limit(-3) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                             parse_int_list_filter                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_int_list_filter_returns_empty_for_none() -> None:
    """A missing argument returns an empty frozenset (falsy)"""
    assert parse_int_list_filter(None) == frozenset()


def test_parse_int_list_filter_returns_empty_for_empty_string() -> None:
    """An empty string is treated as 'missing'"""
    assert parse_int_list_filter('') == frozenset()


def test_parse_int_list_filter_parses_valid_int_list() -> None:
    """A JSON-encoded int list parses to a frozenset"""
    assert parse_int_list_filter('[1, 2, 3]') == frozenset({1, 2, 3})


def test_parse_int_list_filter_dedupes_repeated_values() -> None:
    """A frozenset collapses duplicate ids automatically"""
    assert parse_int_list_filter('[1, 1, 2]') == frozenset({1, 2})


def test_parse_int_list_filter_aborts_400_on_non_list_input() -> None:
    """A bare integer or dict is rejected with HTTP 400"""
    with pytest.raises(HTTPException) as exc:
        parse_int_list_filter('42')
    assert exc.value.code == 400


def test_parse_int_list_filter_aborts_400_on_unparseable_input() -> None:
    """A non-JSON / non-literal string is rejected with HTTP 400"""
    with pytest.raises(HTTPException) as exc:
        parse_int_list_filter('not-a-list')
    assert exc.value.code == 400


def test_parse_int_list_filter_aborts_400_on_non_integer_element() -> None:
    """A list whose elements can't be coerced to int is rejected with HTTP 400"""
    with pytest.raises(HTTPException) as exc:
        parse_int_list_filter('[1, "two", 3]')
    assert exc.value.code == 400
