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
Which fields a write changes: the field names whose value differs between the stored object and the object as it would
be stored - pure, no reads

Only changed fields count, so a form that sends every other field unchanged writes only what it changed. Two empty
values (None, '' or []) are the same value. A field of a multi-data-section is changed when any row's value differs -
also through a row added or removed with a value in it
"""
from collections.abc import Mapping
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.framework.object_required_fields import is_value_missing
# -------------------------------------------------------------------------------------------------------------------- #

# Where a value sits: a top-level field has no section and no row
TOP_LEVEL: tuple[None, None] = (None, None)


def field_values(state: Mapping[str, Any] | None) -> dict[str, dict[tuple[Any, Any], Any]]:
    """
    Every field value of an object state by field name, each under where it sits: the top level, or a section and row

    Args:
        state (Mapping[str, Any] | None): The object document; None for no object (before a create)

    Returns:
        dict[str, dict[tuple[Any, Any], Any]]: ``{name: {(section_id, row id): value}}`` - a top-level field under
            ``TOP_LEVEL``; an entry without a name is passed over, and the first entry of a name in one place counts
    """
    values: dict[str, dict[tuple[Any, Any], Any]] = {}

    if not state:
        return values

    _collect(values, TOP_LEVEL, state.get(CmdbObjectKey.FIELDS.value))

    for section in _dicts(state.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value)):
        for row in _dicts(section.get(CmdbObjectMdsKey.VALUES.value)):
            place: tuple[Any, Any] = (section.get(CmdbObjectMdsKey.SECTION_ID.value),
                                      row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value))
            _collect(values, place, row.get(CmdbObjectMdsRowKey.DATA.value))

    return values


def changed_field_names(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> list[str]:
    """
    The names of the fields whose value differs between two states of an object

    Args:
        before (Mapping[str, Any] | None): The stored object; None for a create
        after (Mapping[str, Any] | None): The object as it would be stored; None for a delete

    Returns:
        list[str]: The changed field names, ascending
    """
    old: dict[str, dict[tuple[Any, Any], Any]] = field_values(before)
    new: dict[str, dict[tuple[Any, Any], Any]] = field_values(after)

    return sorted(name for name in old.keys() | new.keys() if not _same_values(old.get(name, {}), new.get(name, {})))


def same_value(old: Any, new: Any) -> bool:
    """
    Whether two field values are the same - two empty values are

    Args:
        old (Any): One value
        new (Any): The other value

    Returns:
        bool: True when equal or both empty
    """
    return old == new or (is_value_missing(old) and is_value_missing(new))


def _same_values(old: dict[tuple[Any, Any], Any], new: dict[tuple[Any, Any], Any]) -> bool:
    """
    Whether one field holds the same value everywhere it sits in both states - a place missing on one side is empty

    Args:
        old (dict[tuple[Any, Any], Any]): The field's values in one state, by place
        new (dict[tuple[Any, Any], Any]): The field's values in the other state, by place

    Returns:
        bool: True when no place differs
    """
    return all(same_value(old.get(place), new.get(place)) for place in old.keys() | new.keys())


def _collect(values: dict[str, dict[tuple[Any, Any], Any]], place: tuple[Any, Any], entries: Any) -> None:
    """
    Adds the field entries of one place

    Args:
        values (dict[str, dict[tuple[Any, Any], Any]]): The values collected so far
        place (tuple[Any, Any]): Where the entries sit
        entries (Any): The stored entry list; anything else adds nothing
    """
    for entry in _dicts(entries):
        name: Any = entry.get(CmdbObjectFieldKey.NAME.value)

        if isinstance(name, str):
            values.setdefault(name, {}).setdefault(place, entry.get(CmdbObjectFieldKey.VALUE.value))


def _dicts(items: Any) -> list[Mapping[str, Any]]:
    """
    The mappings of a stored list - anything else is no entry

    Args:
        items (Any): The stored value

    Returns:
        list[Mapping[str, Any]]: Its mappings; empty when it is no list
    """
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, Mapping)]
