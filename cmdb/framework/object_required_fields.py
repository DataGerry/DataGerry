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
The shared required-field rule of a CmdbObject write

A CmdbType field flagged ``required`` must carry a value on every CmdbObject of that type. The same
rule applies wherever an object is written - the REST write pipeline (insert / update / patch) and the
object importer - so the parts both paths need live here: which of a type's fields are required, how
that set splits between the top-level field list and the multi-data sections, what counts as "no
value", and which required fields a candidate object leaves empty.

Only the rule is shared; each caller keeps its own error wording (the importer collects per-object
error strings, the REST routes abort with a message), and the importer additionally exempts the field
types whose value it clears on import.

A required field of a multi-data section is only checked in the rows an object actually carries: a
section with no rows is not a missing value, it is an empty section.
"""
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

def is_value_missing(value: Any) -> bool:
    """
    Reports whether a field value counts as "no value" for the required-field check

    Only None and the empty string are treated as missing; 0, False and other falsy-but-present values
    are considered valid values

    Args:
        value (Any): The field value to test

    Returns:
        bool: True when the value is None or an empty string
    """
    return value is None or value == ''


def mds_section_field_names(type_instance: CmdbType) -> dict[str, list[str]]:
    """
    Returns each multi-data-section's ordered field names, keyed by section id

    A section's name is what a CmdbObject stores as the ``section_id`` of its multi_data_sections
    entries, so the returned keys match the object side

    Args:
        type_instance (CmdbType): The CmdbType to read the sections from

    Returns:
        dict[str, list[str]]: ``{section_id: [field name, …]}`` for every multi-data-section
    """
    sections: dict[str, list[str]] = {}

    for section in type_instance.get_sections():
        if getattr(section, 'type', None) == SectionType.MDS_SECTION.value:
            sections[section.name] = list(section.get_fields())

    return sections


def collect_required_field_names(
        type_fields: list[dict[str, Any]] | None,
        exempt_field_types: frozenset[str] | None = None) -> set[str]:
    """
    Returns the names of the type's fields flagged ``required``

    Args:
        type_fields (list[dict[str, Any]] | None): The CmdbType's field definitions
        exempt_field_types (frozenset[str] | None): FieldType values that are never required-checked,
            whatever their flag says (the importer exempts the field types whose value it clears);
            None exempts nothing

    Returns:
        set[str]: The names of the required (non-exempt) fields
    """
    exempt: frozenset[str] = exempt_field_types or frozenset()

    return {
        field.get(FieldKey.NAME.value)
        for field in type_fields or []
        if field.get(FieldKey.REQUIRED.value) and field.get(FieldKey.TYPE.value) not in exempt
    }


def split_required_field_names(
        required_field_names: set[str],
        section_fields: dict[str, list[str]]) -> tuple[set[str], dict[str, set[str]]]:
    """
    Splits the required field names into the top-level ones and the per-MDS-section ones

    A field of a multi-data section is stored in that section's rows, never in the object's top-level
    'fields' list, so it must be checked per row instead of once per object

    Args:
        required_field_names (set[str]): Every required field name of the type
        section_fields (dict[str, list[str]]): ``{section_id: [field name, …]}`` of the type's
                                               multi-data-sections (see ``mds_section_field_names``)

    Returns:
        tuple[set[str], dict[str, set[str]]]: The required top-level field names, and the required
            field names per MDS section id (sections without a required field are omitted)
    """
    required_by_section: dict[str, set[str]] = {
        section_id: required_field_names.intersection(names)
        for section_id, names in section_fields.items()
        if required_field_names.intersection(names)
    }

    required_in_sections: set[str] = (
        set().union(*required_by_section.values()) if required_by_section else set()
    )

    return required_field_names - required_in_sections, required_by_section


def find_missing_required_values(
        field_entries: list[dict[str, Any]] | None,
        required_names: set[str]) -> set[str]:
    """
    Returns the required field names a single list of field entries leaves without a value

    Works on both entry lists a CmdbObject has, since they share the {'name', 'value', 'type'} shape:
    the top-level 'fields' list and an MDS row's 'data' list. A required name that is absent from the
    list counts as missing, exactly like one present with an empty value

    Args:
        field_entries (list[dict[str, Any]] | None): The field entries to inspect
        required_names (set[str]): The required field names to look for

    Returns:
        set[str]: The required names that are absent or hold no value
    """
    values: dict[str, Any] = {
        entry.get(CmdbObjectFieldKey.NAME.value): entry.get(CmdbObjectFieldKey.VALUE.value)
        for entry in field_entries or []
    }

    return {name for name in required_names if name not in values or is_value_missing(values[name])}


def collect_missing_required_values(
        object_data: dict[str, Any],
        required_top_level: set[str],
        required_by_section: dict[str, set[str]]) -> tuple[set[str], dict[str, set[str]]]:
    """
    Returns the required fields a candidate CmdbObject leaves without a value

    The top-level fields are checked once; the MDS fields are checked in every row of every section
    the object carries, and the names missing anywhere in a section are reported together for it. A
    section the object does not carry contributes nothing - an absent section is not an empty value

    Args:
        object_data (dict[str, Any]): The candidate CmdbObject document
        required_top_level (set[str]): The required top-level field names of the object's type
        required_by_section (dict[str, set[str]]): The required field names per MDS section id

    Returns:
        tuple[set[str], dict[str, set[str]]]: The missing top-level field names, and the missing field
            names per MDS section id (sections with nothing missing are omitted)
    """
    missing_top_level: set[str] = find_missing_required_values(
        object_data.get(CmdbObjectKey.FIELDS.value), required_top_level,
    )

    missing_by_section: dict[str, set[str]] = {}

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        section_id: Any = section.get(CmdbObjectMdsKey.SECTION_ID.value)
        required_here: set[str] = required_by_section.get(section_id, set())

        if not required_here:
            continue

        missing_here: set[str] = set()

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            missing_here.update(
                find_missing_required_values(row.get(CmdbObjectMdsRowKey.DATA.value), required_here)
            )

        if missing_here:
            missing_by_section[section_id] = missing_here

    return missing_top_level, missing_by_section


def build_missing_required_errors(
        missing_top_level: set[str],
        missing_by_section: dict[str, set[str]]) -> list[str]:
    """
    Turns the missing required fields into human-readable error messages

    One message for the top-level fields and one per multi-data section, so every caller reports a
    missing required value with the same wording

    Args:
        missing_top_level (set[str]): The missing top-level field names
        missing_by_section (dict[str, set[str]]): The missing field names per MDS section id

    Returns:
        list[str]: The error messages; empty when nothing is missing
    """
    messages: list[str] = []

    if missing_top_level:
        messages.append(f"Missing value for required field(s): {sorted(missing_top_level)}")

    for section_id, missing_in_section in missing_by_section.items():
        messages.append(
            f"Missing value for required field(s) {sorted(missing_in_section)} "
            f"in multi-data section '{section_id}'"
        )

    return messages
