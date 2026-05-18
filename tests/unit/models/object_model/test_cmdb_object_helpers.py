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
Unit tests for cmdb.models.object_model.cmdb_object_helpers

Pure tests: no Mongo, no Flask, no fixtures. Each behavior is exercised through a
pytest.mark.parametrize table. Fixture documents reference CmdbObjectKey / CmdbObjectFieldKey
enums for structural keys (per the no-magic-values rule), while the field-name strings used
as needles are literal test data
"""
from typing import Any

import pytest

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    extract_field_value,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                              robustness against missing keys                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('obj_dict', [
    {},
    {CmdbObjectKey.FIELDS: None},
    {CmdbObjectKey.FIELDS: []},
])
def test_extract_field_value_returns_none_when_no_fields_to_search(obj_dict: dict[str, Any]) -> None:
    """Empty document, missing 'fields' key, explicit None, and empty list all surface as None"""
    assert extract_field_value(obj_dict, 'any-field-name') is None


def test_extract_field_value_returns_none_when_field_not_found() -> None:
    """No entry with the requested name returns None"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'other-field', CmdbObjectFieldKey.VALUE: 'X'},
        ],
    }

    assert extract_field_value(obj_dict, 'missing-field') is None


def test_extract_field_value_returns_none_when_entry_has_no_name() -> None:
    """A malformed field entry without a 'name' key is silently skipped"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.VALUE: 'orphaned'},
        ],
    }

    assert extract_field_value(obj_dict, 'any-field-name') is None


def test_extract_field_value_returns_none_when_match_has_no_value_key() -> None:
    """A matching entry that lacks a 'value' key returns None (the dict's .get fallback)"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'target-field'},
        ],
    }

    assert extract_field_value(obj_dict, 'target-field') is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                successful lookups                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('stored_value', [
    'string-value',
    42,
    True,
    False,
    0,
    '',
    [1, 2, 3],
    {'nested': 'dict'},
    None,
])
def test_extract_field_value_returns_match_for_any_value_type(stored_value: Any) -> None:
    """A successful lookup returns the stored 'value' regardless of its Python type"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'target-field', CmdbObjectFieldKey.VALUE: stored_value},
        ],
    }

    assert extract_field_value(obj_dict, 'target-field') == stored_value


def test_extract_field_value_finds_match_among_many_fields() -> None:
    """The target entry is found regardless of its position in the fields list"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'first-field', CmdbObjectFieldKey.VALUE: 'A'},
            {CmdbObjectFieldKey.NAME: 'second-field', CmdbObjectFieldKey.VALUE: 'B'},
            {CmdbObjectFieldKey.NAME: 'target-field', CmdbObjectFieldKey.VALUE: 'C'},
            {CmdbObjectFieldKey.NAME: 'fourth-field', CmdbObjectFieldKey.VALUE: 'D'},
        ],
    }

    assert extract_field_value(obj_dict, 'target-field') == 'C'


def test_extract_field_value_returns_first_match_on_duplicates() -> None:
    """When two entries share a name, the first occurrence wins (callers treat duplicates as a data-integrity issue)"""
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'duplicate-field', CmdbObjectFieldKey.VALUE: 'first'},
            {CmdbObjectFieldKey.NAME: 'duplicate-field', CmdbObjectFieldKey.VALUE: 'second'},
        ],
    }

    assert extract_field_value(obj_dict, 'duplicate-field') == 'first'


# -------------------------------------------------------------------------------------------------------------------- #
#                                       enum members are interchangeable with strings                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_field_value_accepts_enum_member_as_field_name() -> None:
    """
    The function takes a string for the field-name needle. Because IPAM field-name enums extend
    (str, Enum), a member compares equal to its string value and is accepted transparently
    """
    obj_dict: dict[str, Any] = {
        CmdbObjectKey.FIELDS: [
            {CmdbObjectFieldKey.NAME: 'dg-network-range', CmdbObjectFieldKey.VALUE: '10.0.0.0/24'},
        ],
    }

    from cmdb.models.special_type_model.ipam_constants import SubnetField

    assert extract_field_value(obj_dict, SubnetField.NETWORK_RANGE) == '10.0.0.0/24'
