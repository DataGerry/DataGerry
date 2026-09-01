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
Unit tests for cmdb.framework.rack.enforcement

Covers the Rack detection (through the stored CmdbType, because a candidate off a request may not
carry the server-owned 'special_type' key yet), the in-place height canonicalisation both write paths
rely on, the structured error wrapping and the Rack-specific abort prefix
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.utils import ValidationErrorKey
from cmdb.framework.rack.rack_constants import ABORT_PREFIX, RackValidationError
from cmdb.framework.rack.enforcement import (
    enforce_rack_object_invariants,
    format_rack_errors_for_abort,
    is_rack_object,
    normalize_rack_object,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_TYPE_ID: int = 88
VALID_NAME: str = 'rack-1'
VALID_HEIGHT: int = 42


def _rack(name: Any = VALID_NAME, height: Any = VALID_HEIGHT, type_id: Any = RACK_TYPE_ID) -> dict[str, Any]:
    """Builds a Rack candidate document"""
    return {
        'type_id': type_id,
        'fields': [
            {'name': RackField.NAME.value, 'value': name, 'type': 'text'},
            {'name': RackField.HEIGHT.value, 'value': height, 'type': 'number'},
        ],
    }


def _types_manager(special_type: Any = SpecialType.RACK.value, found: bool = True) -> MagicMock:
    """A TypesManager whose get_type returns a type doc carrying the given special_type marker"""
    manager = MagicMock()
    manager.get_type.return_value = {'public_id': RACK_TYPE_ID, 'special_type': special_type} if found else None

    return manager


def _height_of(candidate: dict[str, Any]) -> Any:
    """Reads the height field's stored value back off the candidate"""
    return next(
        field[CmdbObjectFieldKey.VALUE.value]
        for field in candidate['fields']
        if field['name'] == RackField.HEIGHT.value
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  is_rack_object                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_is_rack_object_true_for_a_rack_type() -> None:
    """The stored type's RACK marker identifies a rack"""
    assert is_rack_object(_types_manager(), _rack()) is True


@pytest.mark.parametrize('special_type', [SpecialType.SUBNET.value, None, '', 'NOPE'], ids=str)
def test_is_rack_object_false_for_any_other_marker(special_type: Any) -> None:
    """Any other (or no) marker is not a rack"""
    assert is_rack_object(_types_manager(special_type=special_type), _rack()) is False


def test_is_rack_object_false_when_the_type_does_not_exist() -> None:
    """A dangling type_id is not a rack rather than an error"""
    assert is_rack_object(_types_manager(found=False), _rack()) is False


@pytest.mark.parametrize('type_id', [None, 'abc', 1.5], ids=str)
def test_is_rack_object_false_without_an_integer_type_id(type_id: Any) -> None:
    """A malformed type_id short-circuits before any database read"""
    manager = _types_manager()

    assert is_rack_object(manager, _rack(type_id=type_id)) is False
    manager.get_type.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                               normalize_rack_object                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('raw, expected', [('42', 42), ('42.0', 42), (42.0, 42), (' 7 ', 7)], ids=str)
def test_normalize_rack_object_stores_the_height_as_an_int(raw: Any, expected: int) -> None:
    """
    Both write paths persist from this dict, so the height must land as an int whoever sent it

    Otherwise the same rack height is stored as a string, a float or an int depending on the client.
    """
    candidate = _rack(height=raw)

    normalize_rack_object(candidate)

    assert _height_of(candidate) == expected
    assert isinstance(_height_of(candidate), int)


@pytest.mark.parametrize('raw', [3.5, 'abc', None, '', 0, -2], ids=str)
def test_normalize_rack_object_leaves_unusable_values_untouched(raw: Any) -> None:
    """A value the validators are about to reject is not silently rewritten"""
    candidate = _rack(height=raw)

    normalize_rack_object(candidate)

    assert _height_of(candidate) == raw


def test_normalize_rack_object_tolerates_a_missing_height_field() -> None:
    """A document without the field must not raise"""
    candidate: dict[str, Any] = {'type_id': RACK_TYPE_ID, 'fields': []}

    normalize_rack_object(candidate)

    assert candidate['fields'] == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_rack_object_invariants                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def test_enforce_is_a_noop_for_a_non_rack_object() -> None:
    """A non-rack object is neither validated nor normalised"""
    candidate = _rack(name='', height='42')

    assert enforce_rack_object_invariants(_types_manager(special_type=None), candidate) == []
    assert _height_of(candidate) == '42'


def test_enforce_returns_no_errors_for_a_valid_rack() -> None:
    """A valid rack passes"""
    assert enforce_rack_object_invariants(_types_manager(), _rack()) == []


def test_enforce_normalises_before_validating() -> None:
    """A string height is canonicalised and then accepted, not rejected for its type"""
    candidate = _rack(height='42')

    assert enforce_rack_object_invariants(_types_manager(), candidate) == []
    assert _height_of(candidate) == 42


def test_enforce_wraps_messages_into_structured_errors() -> None:
    """The REST path reports structured errors, so each message is wrapped"""
    errors = enforce_rack_object_invariants(_types_manager(), _rack(name=None, height=0))

    assert len(errors) == 2
    assert all(ValidationErrorKey.MESSAGE in error for error in errors)
    assert RackValidationError.MISSING_NAME.value in [
        error[ValidationErrorKey.MESSAGE] for error in errors
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                          format_rack_errors_for_abort                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_formatter_uses_the_rack_prefix() -> None:
    """
    A Rack problem must not be reported to the user under the IPAM feature's name

    The IPAM formatter hardcodes 'IPAM validation failed', which is why Rack has its own.
    """
    message = format_rack_errors_for_abort([{ValidationErrorKey.MESSAGE.value: 'boom'}])

    assert message == f'{ABORT_PREFIX}: boom'
    assert 'IPAM' not in message


def test_formatter_joins_several_messages() -> None:
    """Multiple errors are joined into one abort string"""
    errors = [
        {ValidationErrorKey.MESSAGE.value: 'first'},
        {ValidationErrorKey.MESSAGE.value: 'second'},
    ]

    assert format_rack_errors_for_abort(errors) == f'{ABORT_PREFIX}: first | second'


def test_formatter_falls_back_for_an_error_without_a_message() -> None:
    """A malformed error dict must not break the abort path"""
    assert 'unknown error' in format_rack_errors_for_abort([{}])
