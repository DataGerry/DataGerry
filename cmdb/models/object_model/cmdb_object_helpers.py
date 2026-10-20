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
Pure helpers that operate on a CmdbObject in its dict / document form

These are used wherever the application reads a CmdbObject through the manager layer's
``as_dict=True`` path (overviews, validators, enforcement guards) — i.e. on the BSON-shaped
document, not on the CmdbObject Python instance. Every helper here is stateless and free of
DB access so it remains unit-testable in isolation. The companion CmdbObjectKey /
CmdbObjectFieldKey / CmdbObjectMdsKey / CmdbObjectMdsRowKey enums in this package supply the
schema keys; bare string literals must not appear in new code that consumes these documents
"""
from typing import Any, Callable

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.object_model.object_constants import ObjectChangeKey
# -------------------------------------------------------------------------------------------------------------------- #


def extract_field_value(obj_dict: dict[str, Any], field_name: str) -> Any:
    """
    Returns the 'value' of the first entry in obj_dict's 'fields' list whose 'name' matches

    Robust against partial / drifted documents: a missing 'fields' key, a 'fields' value of
    None, an empty list, an entry without a 'name' key, or an entry without a 'value' key all
    surface as None rather than raising. When multiple entries share the same name the first
    encounter wins (callers should treat duplicates as a data-integrity issue, not rely on
    this for deduplication)

    Args:
        obj_dict (dict[str, Any]): A CmdbObject document (typically loaded via
            ObjectsManager.find_objects(..., as_dict=True))
        field_name (str): The field 'name' to look up (commonly an IPAM SubnetField /
            SupernetField / VlanField enum member, but any string works)

    Returns:
        Any: The matching field's 'value', or None when no matching field exists or the value
            is itself None
    """
    for field in obj_dict.get(CmdbObjectKey.FIELDS, []) or []:
        if field.get(CmdbObjectFieldKey.NAME) == field_name:
            return field.get(CmdbObjectFieldKey.VALUE)

    return None


def field_entry_identity(entry: dict[str, Any]) -> tuple[Any, Any]:
    """
    Returns what makes two field entries the same value: their name and their value

    The entry's ``type`` is left out on purpose. It mirrors the type's field definition, so a stored entry
    written without it and the same entry with it filled in hold the same value - compared whole, they read
    as a change

    Args:
        entry (dict[str, Any]): One field entry ({name, value, type}), top-level or inside an MDS row

    Returns:
        tuple[Any, Any]: The entry's name and value
    """
    return entry.get(CmdbObjectFieldKey.NAME), entry.get(CmdbObjectFieldKey.VALUE)


def mds_section_identity(section: dict[str, Any]) -> tuple[Any, list[tuple[Any, list[tuple[Any, Any]]]]]:
    """
    Returns what makes two multi-data-section entries hold the same rows

    Each row reduces to its id and the identities of its field entries (see ``field_entry_identity``). The
    section's ``highest_id`` is left out: it is the row-id counter, not data, and a deleted row leaves it
    where it was

    Args:
        section (dict[str, Any]): One entry of a CmdbObject's ``multi_data_sections``

    Returns:
        tuple: The section id and its rows, in their stored order
    """
    rows: list[tuple[Any, list[tuple[Any, Any]]]] = [
        (
            row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID),
            [field_entry_identity(entry) for entry in row.get(CmdbObjectMdsRowKey.DATA) or []],
        )
        for row in section.get(CmdbObjectMdsKey.VALUES) or []
    ]

    return section.get(CmdbObjectMdsKey.SECTION_ID), rows


def diff_entries(
        old_entries: list[dict[str, Any]],
        new_entries: list[dict[str, Any]],
        identity: Callable[[dict[str, Any]], Any],
    ) -> dict[str, list[dict[str, Any]]]:
    """
    Returns the entries only one of two lists has, compared by ``identity``

    The identities are compared with ``==``, not hashed, because a value may be a list or a dict

    Args:
        old_entries (list[dict[str, Any]]): The entries as they were
        new_entries (list[dict[str, Any]]): The entries as they are
        identity (Callable[[dict[str, Any]], Any]): What two entries must share to be the same

    Returns:
        dict[str, list[dict[str, Any]]]: ``{'old': only in old_entries, 'new': only in new_entries}``, each
            entry as it is stored
    """
    old_identities: list[Any] = [identity(entry) for entry in old_entries]
    new_identities: list[Any] = [identity(entry) for entry in new_entries]

    return {
        ObjectChangeKey.OLD.value: [
            entry for entry, key in zip(old_entries, old_identities) if key not in new_identities
        ],
        ObjectChangeKey.NEW.value: [
            entry for entry, key in zip(new_entries, new_identities) if key not in old_identities
        ],
    }


def count_changed_field_names(changes: dict[str, Any]) -> int:
    """
    Counts the distinct field names a field diff touches

    A changed value appears on both sides of the diff and counts once; a field only one side carries -
    added, or dropped from the object - counts too

    Args:
        changes (dict[str, Any]): A field diff (see ``diff_entries``)

    Returns:
        int: How many fields changed
    """
    return len({
        entry.get(CmdbObjectFieldKey.NAME)
        for side in (ObjectChangeKey.OLD, ObjectChangeKey.NEW)
        for entry in changes.get(side.value, [])
    })
