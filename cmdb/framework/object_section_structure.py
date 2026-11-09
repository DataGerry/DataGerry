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
The shared structure rule of a CmdbObject's ``fields`` names and ``multi_data_sections``

Every object write path runs it before anything else reads the sections - the REST insert, update, bulk update and
patch (``objects_helper``) and the object importer - so a stored object holds:

- each top-level field name once;
- a list of section objects, each with a ``section_id`` the type declares as a multi-data section, each id once;
- per section a list of row objects, each with a ``multi_data_id`` that is a whole number from ``MIN_ROW_ID`` and
  unique in the section - the row's identity, which the port interface links, the IPAM self-exclusion and the
  PATCH row edits address it by;
- per row a list of entries, each an object with a string ``name`` the section declares, each name once.

The client chooses a new row's id; the server only checks it. ``highest_id`` is the section's row-id counter: the
server sets it to the largest of what was sent, every row id present and what the stored object held, so it never
falls below a row id (a PATCH-created row takes the next id above it) and never goes back, so an id is never reused.

The check answers reasons rather than raising, so each caller words the refusal its own way: the REST routes abort
with one 400 (``guard_object_structure``), the importer collects the reasons as the object's errors
"""
from typing import Any

from flask import abort

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.utils import duplicate_names
from cmdb.framework.object_required_fields import mds_section_field_names
from cmdb.framework.object_section_structure_constants import (
    ENTRY_INVALID,
    FIELDS_REPEATED,
    HIGHEST_ID_INVALID,
    MAX_LISTED_REASONS,
    MIN_ROW_ID,
    MORE_REASONS_PART,
    OBJECT_STRUCTURE_INVALID_MSG,
    REASON_SEPARATOR,
    ROW_DATA_NOT_A_LIST,
    ROW_FIELDS_REPEATED,
    ROW_FIELDS_UNDECLARED,
    ROW_ID_INVALID,
    ROW_IDS_REPEATED,
    ROW_NOT_AN_OBJECT,
    SECTION_NOT_AN_OBJECT,
    SECTION_REPEATED,
    SECTION_UNDECLARED,
    SECTION_WITHOUT_ID,
    SECTIONS_NOT_A_LIST,
    VALUES_NOT_A_LIST,
)
# -------------------------------------------------------------------------------------------------------------------- #

# {section_id: the names of its fields} of every multi-data section the type declares; None judges no declaration
DeclaredSections = dict[str, set[str]] | None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     THE RULES                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def declared_sections_of(type_instance: CmdbType) -> dict[str, set[str]]:
    """
    The multi-data sections a CmdbType declares, each with the names of its fields

    Args:
        type_instance (CmdbType): The object's type

    Returns:
        dict[str, set[str]]: {section_id: field names}
    """
    return {section_id: set(names) for section_id, names in mds_section_field_names(type_instance).items()}


def is_row_id(value: Any) -> bool:
    """
    Whether a value is a row id (or a ``highest_id``): a whole number from MIN_ROW_ID; a bool is none

    Args:
        value (Any): The value sent or stored

    Returns:
        bool: True for a row id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_ROW_ID


def field_name_reasons(fields: Any) -> list[str]:
    """
    The reason a top-level ``fields`` list names a field more than once

    Args:
        fields (Any): The object's ``fields`` as sent; anything but a list of objects is left to the field checks

    Returns:
        list[str]: One reason naming every repeated name, or none
    """
    if not isinstance(fields, list):
        return []

    repeated: list[Any] = duplicate_names(
        entry.get(CmdbObjectFieldKey.NAME.value) for entry in fields
        if isinstance(entry, dict) and isinstance(entry.get(CmdbObjectFieldKey.NAME.value), str)
    )

    return [FIELDS_REPEATED.format(names=repeated)] if repeated else []


def row_reasons(section_id: str, position: int, row: Any, declared_fields: set[str] | None) -> list[str]:
    """
    The reasons one row breaks the rule; its id's uniqueness is the section's to judge

    Args:
        section_id (str): The row's section
        position (int): The row's position in the section's ``values``
        row (Any): The row as sent
        declared_fields (set[str] | None): The fields the section declares; None judges no declaration

    Returns:
        list[str]: The reasons, empty for a row in line
    """
    if not isinstance(row, dict):
        return [ROW_NOT_AN_OBJECT.format(section_id=section_id, position=position)]

    reasons: list[str] = []

    if not is_row_id(row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value)):
        reasons.append(ROW_ID_INVALID.format(section_id=section_id, position=position, minimum=MIN_ROW_ID))

    data: Any = row.get(CmdbObjectMdsRowKey.DATA.value, [])

    if not isinstance(data, list):
        return reasons + [ROW_DATA_NOT_A_LIST.format(section_id=section_id, position=position)]

    names: list[Any] = [entry.get(CmdbObjectFieldKey.NAME.value) if isinstance(entry, dict) else None
                        for entry in data]

    if not all(isinstance(name, str) for name in names):
        return reasons + [ENTRY_INVALID.format(section_id=section_id, position=position)]

    if declared_fields is not None and (undeclared := sorted(set(names) - declared_fields)):
        reasons.append(ROW_FIELDS_UNDECLARED.format(section_id=section_id, position=position, names=undeclared))

    if repeated := duplicate_names(names):
        reasons.append(ROW_FIELDS_REPEATED.format(section_id=section_id, position=position, names=repeated))

    return reasons


def rows_reasons(section_id: str, rows: list[Any], declared_fields: set[str] | None) -> list[str]:
    """
    The reasons a section's rows break the rule: each row's own, then the ids more than one row uses

    Args:
        section_id (str): The section
        rows (list[Any]): Its ``values`` as sent
        declared_fields (set[str] | None): The fields the section declares; None judges no declaration

    Returns:
        list[str]: The reasons, empty for rows in line
    """
    reasons: list[str] = []

    for position, row in enumerate(rows):
        reasons.extend(row_reasons(section_id, position, row, declared_fields))

    repeated: list[Any] = duplicate_names(
        row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value) for row in rows
        if isinstance(row, dict) and is_row_id(row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value))
    )

    if repeated:
        reasons.append(ROW_IDS_REPEATED.format(section_id=section_id, row_ids=repeated))

    return reasons


def section_reasons(position: int, section: Any, declared: DeclaredSections, seen: set[str]) -> list[str]:
    """
    The reasons one section breaks the rule

    Args:
        position (int): The section's position in ``multi_data_sections``
        section (Any): The section as sent
        declared (DeclaredSections): The type's multi-data sections; None judges no declaration
        seen (set[str]): The section_ids of the sections before it - this one's is added

    Returns:
        list[str]: The reasons, empty for a section in line
    """
    if not isinstance(section, dict):
        return [SECTION_NOT_AN_OBJECT.format(position=position)]

    section_id: Any = section.get(CmdbObjectMdsKey.SECTION_ID.value)

    if not isinstance(section_id, str) or not section_id:
        return [SECTION_WITHOUT_ID.format(position=position)]

    reasons: list[str] = []

    if section_id in seen:
        reasons.append(SECTION_REPEATED.format(section_id=section_id))

    seen.add(section_id)

    if declared is not None and section_id not in declared:
        return reasons or [SECTION_UNDECLARED.format(section_id=section_id)]

    highest_id: Any = section.get(CmdbObjectMdsKey.HIGHEST_ID.value)

    if highest_id is not None and not is_row_id(highest_id):
        reasons.append(HIGHEST_ID_INVALID.format(section_id=section_id, minimum=MIN_ROW_ID))

    rows: Any = section.get(CmdbObjectMdsKey.VALUES.value, [])

    if not isinstance(rows, list):
        return reasons + [VALUES_NOT_A_LIST.format(section_id=section_id)]

    return reasons + rows_reasons(section_id, rows, None if declared is None else declared[section_id])


def object_structure_reasons(object_data: dict[str, Any], declared: DeclaredSections) -> list[str]:
    """
    Every reason an object's field names and multi-data sections break the rule, in document order

    Args:
        object_data (dict[str, Any]): The candidate object
        declared (DeclaredSections): The type's multi-data sections; None (an importer without its type) judges no
            declaration - neither unknown sections nor fields outside their section

    Returns:
        list[str]: The reasons, empty for an object in line
    """
    reasons: list[str] = field_name_reasons(object_data.get(CmdbObjectKey.FIELDS.value))
    sections: Any = object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value)

    if sections is None:
        return reasons

    if not isinstance(sections, list):
        return reasons + [SECTIONS_NOT_A_LIST]

    seen: set[str] = set()

    for position, section in enumerate(sections):
        reasons.extend(section_reasons(position, section, declared, seen))

    return reasons


def describe_reasons(reasons: list[str]) -> str:
    """
    The reasons joined for one message: the first MAX_LISTED_REASONS, the rest counted

    Args:
        reasons (list[str]): The reasons, at least one

    Returns:
        str: The description
    """
    listed: str = REASON_SEPARATOR.join(reasons[:MAX_LISTED_REASONS])

    if len(reasons) <= MAX_LISTED_REASONS:
        return listed

    return MORE_REASONS_PART.format(listed=listed, more=len(reasons) - MAX_LISTED_REASONS)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  THE ROW-ID COUNTER                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def stored_highest_ids(stored_sections: Any) -> dict[str, int]:
    """
    The ``highest_id`` the stored object holds per section, where it is a row id

    Args:
        stored_sections (Any): The stored object's ``multi_data_sections``; None for a new object

    Returns:
        dict[str, int]: {section_id: highest_id}
    """
    if not isinstance(stored_sections, list):
        return {}

    return {
        section[CmdbObjectMdsKey.SECTION_ID.value]: section[CmdbObjectMdsKey.HIGHEST_ID.value]
        for section in stored_sections
        if isinstance(section, dict) and isinstance(section.get(CmdbObjectMdsKey.SECTION_ID.value), str)
        and is_row_id(section.get(CmdbObjectMdsKey.HIGHEST_ID.value))
    }


def next_row_id(section: dict[str, Any]) -> int:
    """
    The id a new row of a section takes: one above its ``highest_id`` and above every row id present

    Args:
        section (dict[str, Any]): The section the row is added to

    Returns:
        int: The new row's id
    """
    return aligned_highest_id(section, None) + 1


def aligned_highest_id(section: dict[str, Any], stored_highest: int | None) -> int:
    """
    A section's row-id counter: the largest of the sent ``highest_id``, every row id and the stored counter

    Args:
        section (dict[str, Any]): The section; a row that is no object or holds no row id counts for nothing
        stored_highest (int | None): The stored object's counter of this section; None when it holds none

    Returns:
        int: The counter
    """
    candidates: list[int] = [
        row[CmdbObjectMdsRowKey.MULTI_DATA_ID.value] for row in section.get(CmdbObjectMdsKey.VALUES.value) or []
        if isinstance(row, dict) and is_row_id(row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value))
    ]

    for counter in (section.get(CmdbObjectMdsKey.HIGHEST_ID.value), stored_highest):
        if is_row_id(counter):
            candidates.append(counter)

    return max(candidates, default=MIN_ROW_ID)


def align_highest_ids(object_data: dict[str, Any], stored_sections: Any) -> None:
    """
    Sets every section's ``highest_id`` to its aligned counter, in place

    Args:
        object_data (dict[str, Any]): The candidate object, in line with the rule
        stored_sections (Any): The stored object's ``multi_data_sections``; None for a new object
    """
    stored: dict[str, int] = stored_highest_ids(stored_sections)

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        section[CmdbObjectMdsKey.HIGHEST_ID.value] = aligned_highest_id(
            section, stored.get(section[CmdbObjectMdsKey.SECTION_ID.value]),
        )


def guard_object_structure(object_data: dict[str, Any], declared: DeclaredSections, stored_sections: Any) -> None:
    """
    Refuses an object write that breaks the structure rule, then aligns its row-id counters

    Args:
        object_data (dict[str, Any]): The candidate object; its counters are set in place
        declared (DeclaredSections): The type's multi-data sections ({section_id: field names})
        stored_sections (Any): The stored object's ``multi_data_sections``; None for a new object

    Raises:
        HTTPException: 400 naming every reason (the first MAX_LISTED_REASONS, the rest counted)
    """
    if reasons := object_structure_reasons(object_data, declared):
        abort(400, OBJECT_STRUCTURE_INVALID_MSG.format(reasons=describe_reasons(reasons)))

    align_highest_ids(object_data, stored_sections)
