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
The person selector values an object holds - where they are, what shape they have, which ids they name

Pure functions over an object document and its type's field definitions. A selector value sits in the object's flat
``fields`` and, for a selector shown by a multi-data section, in every row of that section. Each place is addressed
by a ``SelectorPlace`` - the section and row it is in (none for a flat entry) and the field name - so an update can
compare a candidate's value with the stored one at the same place
"""
from typing import Any, NamedTuple

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.person_selector_rules import is_multiple, is_person_selector
from cmdb.framework.rendering.render_constants import RenderedFieldKey
from cmdb.utils import coerce_whole_number
from cmdb.framework.person_selector.person_selector_constants import (
    PERSON_SELECTOR_CELL_ERROR,
    SELECTOR_CELL_SEPARATOR,
    PersonSelectorWriteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SelectorPlace',
    'selector_fields',
    'selector_entries',
    'ids_of',
    'canonicalize_and_check_shapes',
    'stored_values_by_place',
    'parse_selector_value',
]

# What an empty single selector is sent as by a form, besides None
EMPTY_TEXT: str = ''


class SelectorPlace(NamedTuple):
    """Where one selector value sits: (section, row) for a multi-data row, (None, None) for a flat entry"""
    section_id: Any
    row_id: Any
    name: str


def selector_fields(fields: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """
    The person selectors a type declares, by name

    Args:
        fields (list[dict[str, Any]] | None): The type's field definitions

    Returns:
        dict[str, dict[str, Any]]: Every person selector definition, keyed by its name
    """
    return {field[FieldKey.NAME.value]: field for field in fields or [] if is_person_selector(field)}


def selector_entries(object_data: dict[str, Any] | None,
                     selectors: dict[str, dict[str, Any]]) -> list[tuple[SelectorPlace, dict[str, Any]]]:
    """
    Every entry of the object holding a value of one of the given selectors, flat and in every multi-data row

    The entries are the object's own dicts, so a caller may change them in place

    Args:
        object_data (dict[str, Any] | None): The object document
        selectors (dict[str, dict[str, Any]]): The type's person selectors, by name

    Returns:
        list[tuple[SelectorPlace, dict[str, Any]]]: Each entry with its place
    """
    if not object_data or not selectors:
        return []

    def picked(entries: Any, section_id: Any, row_id: Any) -> list[tuple[SelectorPlace, dict[str, Any]]]:
        if not isinstance(entries, list):
            return []

        return [
            (SelectorPlace(section_id, row_id, entry[CmdbObjectFieldKey.NAME.value]), entry)
            for entry in entries
            if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) in selectors
        ]

    found = picked(object_data.get(CmdbObjectKey.FIELDS.value), None, None)

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        if not isinstance(section, dict):
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            if isinstance(row, dict):
                found += picked(row.get(CmdbObjectMdsRowKey.DATA.value),
                                section.get(CmdbObjectMdsKey.SECTION_ID.value),
                                row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value))

    return found


def ids_of(value: Any) -> list[int]:
    """
    The object ids a stored selector value names, in its order

    Args:
        value (Any): A selector value - one id, a list of ids, or nothing

    Returns:
        list[int]: The whole-number ids it holds (a boolean is no id)
    """
    candidates: list[Any] = value if isinstance(value, list) else [value]

    return [item for item in candidates if isinstance(item, int) and not isinstance(item, bool)]


def _is_id(value: Any) -> bool:
    """A whole number that is no boolean"""
    return isinstance(value, int) and not isinstance(value, bool)


def canonicalize_and_check_shapes(entries: list[tuple[SelectorPlace, dict[str, Any]]],
                                  selectors: dict[str, dict[str, Any]]) -> list[str]:
    """
    Brings each selector value into its canonical empty form, drops render-only keys, and reports a wrong shape

    An empty single selector is None (an empty text becomes None), an empty multiple one ``[]`` (None or an empty
    text becomes ``[]``). The render's ``persons`` expansion, which a client may send back, is never stored. A single
    selector holds one id or None; a multiple one a list of ids, each once

    Args:
        entries (list[tuple[SelectorPlace, dict[str, Any]]]): The candidate's selector entries (changed in place)
        selectors (dict[str, dict[str, Any]]): The type's person selectors, by name

    Returns:
        list[str]: One message per selector holding a wrong shape (each selector named once)
    """
    refused: dict[str, str] = {}

    for place, entry in entries:
        entry.pop(RenderedFieldKey.PERSONS.value, None)
        value: Any = entry.get(CmdbObjectFieldKey.VALUE.value)

        if is_multiple(selectors[place.name]):
            if value is None or value == EMPTY_TEXT:
                entry[CmdbObjectFieldKey.VALUE.value] = value = []

            if not (isinstance(value, list) and all(_is_id(item) for item in value) and len(set(value)) == len(value)):
                refused.setdefault(place.name, PersonSelectorWriteError.SHAPE_MULTIPLE.format(name=place.name))
        else:
            if value == EMPTY_TEXT:
                entry[CmdbObjectFieldKey.VALUE.value] = value = None

            if value is not None and not _is_id(value):
                refused.setdefault(place.name, PersonSelectorWriteError.SHAPE_SINGLE.format(name=place.name))

    return list(refused.values())


def stored_values_by_place(previous_object: dict[str, Any] | None,
                           selectors: dict[str, dict[str, Any]]) -> dict[SelectorPlace, Any]:
    """
    The stored selector values of an object, by place

    Args:
        previous_object (dict[str, Any] | None): The stored object; None on a create
        selectors (dict[str, dict[str, Any]]): The type's person selectors, by name

    Returns:
        dict[SelectorPlace, Any]: Each stored value at its place; empty on a create
    """
    return {
        place: entry.get(CmdbObjectFieldKey.VALUE.value)
        for place, entry in selector_entries(previous_object, selectors)
    }


def parse_selector_value(value: Any, multiple: bool) -> tuple[Any, str | None]:
    """
    Reads an imported selector value: a native id or list (JSON), or the cell text of a tabular file

    A cell holds one id, or - for a selector holding several - ids separated by ``SELECTOR_CELL_SEPARATOR``; a
    spreadsheet may hand a whole number over as a float. Whether the ids exist, may be read and are of a selectable
    kind is the write rule's question, asked afterwards

    Args:
        value (Any): The imported value, not empty
        multiple (bool): Whether the selector holds several

    Returns:
        tuple[Any, str | None]: The id, or the list of ids, and None - or the value unchanged and why it is refused
    """
    parts: list[Any] = value if isinstance(value, list) else (
        value.split(SELECTOR_CELL_SEPARATOR) if isinstance(value, str) else [value]
    )
    ids: list[int | None] = [
        coerce_whole_number(part.strip() if isinstance(part, str) else part) for part in parts
        if not (isinstance(part, str) and not part.strip())
    ]

    if not ids or any(object_id is None for object_id in ids) or (not multiple and len(ids) > 1):
        return value, PERSON_SELECTOR_CELL_ERROR.format(value=value)

    return (ids if multiple else ids[0]), None
