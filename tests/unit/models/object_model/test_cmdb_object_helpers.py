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
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    count_changed_field_names,
    diff_entries,
    extract_field_value,
    field_entry_identity,
    mds_section_identity,
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the diff helpers                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _entry(name: str, value: Any, field_type: str | None = None) -> dict[str, Any]:
    """One field entry, with a type key only when one is given."""
    entry: dict[str, Any] = {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}

    if field_type is not None:
        entry[CmdbObjectFieldKey.TYPE] = field_type

    return entry


def _section(section_id: str, highest_id: int, rows: list[tuple[int, list[dict[str, Any]]]]) -> dict[str, Any]:
    """One MDS section built from (row id, entries) pairs."""
    return {
        CmdbObjectMdsKey.SECTION_ID: section_id,
        CmdbObjectMdsKey.HIGHEST_ID: highest_id,
        CmdbObjectMdsKey.VALUES: [
            {CmdbObjectMdsRowKey.MULTI_DATA_ID: row_id, CmdbObjectMdsRowKey.DATA: data} for row_id, data in rows
        ],
    }


def test_field_entry_identity_is_name_and_value_without_the_type() -> None:
    """The type key is left out; name and value come back in that order."""
    assert field_entry_identity(_entry('host', 'srv-01', 'text')) == ('host', 'srv-01')
    assert field_entry_identity({}) == (None, None)


def test_mds_section_identity_keeps_rows_in_order_and_drops_the_counter_and_types() -> None:
    """Rows reduce to (row id, entry identities); highest_id and every type key are left out."""
    section = _section('extra', 7, [(1, [_entry('a', 1, 'text')]), (3, [_entry('b', 2)])])

    assert mds_section_identity(section) == ('extra', [(1, [('a', 1)]), (3, [('b', 2)])])


def test_mds_section_identity_reads_a_section_without_rows() -> None:
    """A section added before its first row has an empty row list."""
    assert mds_section_identity({CmdbObjectMdsKey.SECTION_ID: 'extra'}) == ('extra', [])


def test_diff_entries_reports_each_side_alone_as_stored() -> None:
    """Entries are returned as they are stored, type key included, on the side only they appear on."""
    old = [_entry('a', 1, 'text'), _entry('b', 2, 'text')]
    new = [_entry('a', 1), _entry('b', 3, 'text'), _entry('c', [4], 'text')]

    assert diff_entries(old, new, field_entry_identity) == {
        'old': [_entry('b', 2, 'text')],
        'new': [_entry('b', 3, 'text'), _entry('c', [4], 'text')],
    }


def test_diff_entries_compares_unhashable_values() -> None:
    """A list or dict value compares by equality."""
    old = [_entry('a', {'k': [1]})]
    new = [_entry('a', {'k': [1]})]

    assert diff_entries(old, new, field_entry_identity) == {'old': [], 'new': []}


def test_diff_entries_sees_a_row_change_inside_a_section() -> None:
    """A section with a changed row value differs; an equal one beside it does not."""
    kept = _section('kept', 1, [(1, [_entry('a', 1)])])
    before = _section('edited', 1, [(1, [_entry('b', 'x')])])
    after = _section('edited', 2, [(1, [_entry('b', 'x')]), (2, [_entry('b', 'y')])])

    assert diff_entries([kept, before], [kept, after], mds_section_identity) == {'old': [before], 'new': [after]}


@pytest.mark.parametrize('changes,expected', [
    ({'old': [], 'new': []}, 0),
    ({'old': [_entry('a', 1)], 'new': [_entry('a', 2)]}, 1),        # a changed value counts once
    ({'old': [_entry('a', 1)], 'new': []}, 1),                      # a dropped field
    ({'old': [], 'new': [_entry('a', 1)]}, 1),                      # an added field
    ({'old': [_entry('a', 1)], 'new': [_entry('b', 2), _entry('a', 3)]}, 2),
    ({}, 0),
])
def test_count_changed_field_names(changes: dict[str, Any], expected: int) -> None:
    """Distinct names across both sides."""
    assert count_changed_field_names(changes) == expected
