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
Server-side updates that carry a CmdbType's field changes into every CmdbObject of that type

When a type gains or loses a field - through a type edit or a section template - every object of the
type has to follow: its flat ``fields`` list and, for a multi-data section, every row of that section.
Each builder here produces **one** ``update_many`` (a `RawUpdate`) that does that for all objects of the
type inside MongoDB, so no object is read and none is written back from memory:

* nothing is loaded, whatever the number of objects
* an update touches only the entries it adds or removes, so an object edit saved concurrently is not
  overwritten by a stale copy
* every update is idempotent - an entry is only pushed where it is missing (``$ne`` filter), and a
  ``$pull`` of something absent changes nothing - so a re-run modifies no document

The MDS row updates address the section and its rows through positional array filters (``$[s]`` for
the section, ``$[v]`` / ``$[]`` for the rows). An object's MDS ``section_id`` is the type section's
``name``, which is what the builders are keyed by. `ObjectsManager.apply_raw_updates` runs a list of them.
"""
from dataclasses import dataclass
from typing import Any

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RawUpdate',
    'build_add_field_update',
    'build_add_mds_field_update',
    'build_field_entry',
    'build_remove_fields_update',
    'build_remove_mds_fields_update',
    'build_remove_mds_section_update',
    'build_remove_undeclared_fields_update',
]

# The array-filter identifiers the MDS row updates use: `s` is the section, `v` one of its rows
SECTION_IDENTIFIER: str = 's'
ROW_IDENTIFIER: str = 'v'

FIELD_NAME_PATH: str = f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.NAME.value}'
MDS_SECTION_ID_PATH: str = f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.SECTION_ID.value}'


@dataclass(frozen=True)
class RawUpdate:
    """
    One ``update_many`` against ``framework.objects``: which documents, what to change, and the
    identifiers of the positional ``$[<identifier>]`` paths the change uses
    """
    filter_query: dict[str, Any]
    update: dict[str, Any]
    array_filters: list[dict[str, Any]] | None = None


def build_field_entry(field_definition: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the ``{name, value, type}`` entry an object stores for one field of its type

    The value is the field definition's default (``value``) when it declares one, None otherwise - a
    newly added field starts from what the type says an empty object of it holds. The type falls back
    to ``text`` for a definition that does not carry one

    Args:
        field_definition (dict[str, Any]): The field as the CmdbType declares it

    Returns:
        dict[str, Any]: The entry to store in an object's ``fields`` list or in an MDS row
    """
    return {
        CmdbObjectFieldKey.NAME.value: field_definition[FieldKey.NAME],
        CmdbObjectFieldKey.TYPE.value: field_definition.get(FieldKey.TYPE, FieldType.TEXT.value),
        CmdbObjectFieldKey.VALUE.value: field_definition.get(FieldKey.VALUE),
    }


def build_add_field_update(type_id: int, entry: dict[str, Any]) -> RawUpdate:
    """
    Appends a field entry to the flat ``fields`` list of every object of a type that lacks it

    Args:
        type_id (int): public_id of the CmdbType
        entry (dict[str, Any]): The entry to append (see `build_field_entry`)

    Returns:
        RawUpdate: The update; objects already carrying the field name are not matched
    """
    return RawUpdate(
        filter_query={
            CmdbObjectKey.TYPE_ID.value: type_id,
            FIELD_NAME_PATH: {'$ne': entry[CmdbObjectFieldKey.NAME.value]},
        },
        update={'$push': {CmdbObjectKey.FIELDS.value: entry}},
    )


def build_remove_fields_update(type_id: int, field_names: list[str]) -> RawUpdate:
    """
    Removes the named entries from the flat ``fields`` list of every object of a type

    Args:
        type_id (int): public_id of the CmdbType
        field_names (list[str]): The names of the fields to remove

    Returns:
        RawUpdate: The update
    """
    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update={'$pull': {CmdbObjectKey.FIELDS.value: {CmdbObjectFieldKey.NAME.value: {'$in': field_names}}}},
    )


def build_remove_undeclared_fields_update(type_id: int, declared_names: list[str]) -> RawUpdate:
    """
    Removes every flat ``fields`` entry whose name the type does not declare, from every object of it

    Unlike `build_remove_fields_update` this does not need to know WHICH names are stale: an entry an
    object carries for a field that was never part of the type is removed as well

    Args:
        type_id (int): public_id of the CmdbType
        declared_names (list[str]): Every field name the type declares

    Returns:
        RawUpdate: The update
    """
    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update={'$pull': {CmdbObjectKey.FIELDS.value: {CmdbObjectFieldKey.NAME.value: {'$nin': declared_names}}}},
    )


def build_add_mds_field_update(type_id: int, section_id: str, entry: dict[str, Any]) -> RawUpdate:
    """
    Appends a field entry to every row of one MDS section that lacks it, on every object of a type

    Rows already carrying the field name are left alone, and an object with the section but no rows
    gains nothing - a row exists only once a user captured one

    Args:
        type_id (int): public_id of the CmdbType
        section_id (str): The MDS section's id, i.e. the type section's name
        entry (dict[str, Any]): The entry to append (see `build_field_entry`)

    Returns:
        RawUpdate: The update
    """
    values_key: str = CmdbObjectMdsKey.VALUES.value
    data_key: str = CmdbObjectMdsRowKey.DATA.value
    row_data_path: str = (
        f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.$[{SECTION_IDENTIFIER}].{values_key}'
        f'.$[{ROW_IDENTIFIER}].{data_key}'
    )

    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id, MDS_SECTION_ID_PATH: section_id},
        update={'$push': {row_data_path: entry}},
        array_filters=[
            {f'{SECTION_IDENTIFIER}.{CmdbObjectMdsKey.SECTION_ID.value}': section_id},
            {
                f'{ROW_IDENTIFIER}.{data_key}.{CmdbObjectFieldKey.NAME.value}':
                    {'$ne': entry[CmdbObjectFieldKey.NAME.value]},
            },
        ],
    )


def build_remove_mds_fields_update(type_id: int, section_id: str, field_names: list[str]) -> RawUpdate:
    """
    Removes the named entries from every row of one MDS section, on every object of a type

    Args:
        type_id (int): public_id of the CmdbType
        section_id (str): The MDS section's id, i.e. the type section's name
        field_names (list[str]): The names of the fields to remove

    Returns:
        RawUpdate: The update
    """
    all_rows_data_path: str = (
        f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.$[{SECTION_IDENTIFIER}].{CmdbObjectMdsKey.VALUES.value}'
        f'.$[].{CmdbObjectMdsRowKey.DATA.value}'
    )

    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id, MDS_SECTION_ID_PATH: section_id},
        update={'$pull': {all_rows_data_path: {CmdbObjectFieldKey.NAME.value: {'$in': field_names}}}},
        array_filters=[{f'{SECTION_IDENTIFIER}.{CmdbObjectMdsKey.SECTION_ID.value}': section_id}],
    )


def build_remove_mds_section_update(type_id: int, section_id: str) -> RawUpdate:
    """
    Removes one MDS section - all of its rows - from every object of a type

    Args:
        type_id (int): public_id of the CmdbType
        section_id (str): The MDS section's id, i.e. the type section's name

    Returns:
        RawUpdate: The update
    """
    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update={'$pull': {CmdbObjectKey.MULTI_DATA_SECTIONS.value: {CmdbObjectMdsKey.SECTION_ID.value: section_id}}},
    )
