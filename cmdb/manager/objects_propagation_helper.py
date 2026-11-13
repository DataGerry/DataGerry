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

**A field's ``type`` on an object is the type's, never its own.** ``build_field_kind_update`` is one pipeline
``update_many`` that stamps every entry - flat and in every MDS row - with the type its field declares; an entry
of a field whose type CHANGED (it does not carry the new one) is reset to the field's default ``value``, or None. A
value of the old type is not carried into the new one: a text is no select option, a date string no reference.

**A person selector's value has the shape its ``multiple`` setting says.** ``build_person_value_shape_update`` is one
pipeline ``update_many`` reshaping every entry of the type's person selectors - flat and in every MDS row: a selector
holding several objects stores a list (one id becomes a one-item list, None an empty one), a selector holding one
stores an id or None (a list becomes its only item, or None when empty; a narrowing to one object is refused while a
list holds more). State-based and idempotent like the kind stamp.
"""
from dataclasses import dataclass
from typing import Any

from cmdb.utils import Builder

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.person_selector_rules import is_multiple, is_person_selector
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RawUpdate',
    'build_add_field_update',
    'build_field_kind_update',
    'build_person_value_shape_update',
    'field_kind_changes',
    'build_add_mds_field_update',
    'build_field_entry',
    'build_remove_fields_update',
    'build_remove_mds_fields_update',
    'build_remove_mds_section_update',
    'build_remove_undeclared_fields_update',
    'build_remove_undeclared_mds_fields_update',
    'build_remove_undeclared_mds_sections_update',
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
    update: dict[str, Any] | list[dict[str, Any]]
    array_filters: list[dict[str, Any]] | None = None


def build_field_entry(field_definition: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the ``{name, value, type}`` entry an object stores for one field of its type

    The value is the field definition's default (``value``) when it declares one, None otherwise - a
    newly added field starts from what the type says an empty object of it holds; a person selector holding several
    objects starts from an empty list, the shape its value has. The type falls back to ``text`` for a definition
    that does not carry one

    Args:
        field_definition (dict[str, Any]): The field as the CmdbType declares it

    Returns:
        dict[str, Any]: The entry to store in an object's ``fields`` list or in an MDS row
    """
    empty: Any = [] if is_person_selector(field_definition) and is_multiple(field_definition) else None

    return {
        CmdbObjectFieldKey.NAME.value: field_definition[FieldKey.NAME],
        CmdbObjectFieldKey.TYPE.value: field_definition.get(FieldKey.TYPE, FieldType.TEXT.value),
        CmdbObjectFieldKey.VALUE.value: field_definition.get(FieldKey.VALUE, empty),
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


def build_remove_undeclared_mds_sections_update(type_id: int, declared_section_ids: list[str]) -> RawUpdate:
    """
    Removes every MDS section the type does not declare - all of its rows - from every object of it

    The state-based counterpart of `build_remove_mds_section_update`: it does not need to know WHICH sections an
    edit removed, so it also brings back in line an object a half-finished edit left behind

    Args:
        type_id (int): public_id of the CmdbType
        declared_section_ids (list[str]): The names of every MDS section the type declares

    Returns:
        RawUpdate: The update
    """
    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update={'$pull': {
            CmdbObjectKey.MULTI_DATA_SECTIONS.value: {
                CmdbObjectMdsKey.SECTION_ID.value: {'$nin': declared_section_ids},
            },
        }},
    )


def build_remove_undeclared_mds_fields_update(type_id: int, section_id: str, declared_names: list[str]) -> RawUpdate:
    """
    Removes every entry whose name one MDS section does not declare, from every row of it, on every object of a type

    The state-based counterpart of `build_remove_mds_fields_update`: it does not need to know WHICH fields an edit
    removed

    Args:
        type_id (int): public_id of the CmdbType
        section_id (str): The MDS section's id, i.e. the type section's name
        declared_names (list[str]): Every field name the section declares

    Returns:
        RawUpdate: The update
    """
    all_rows_data_path: str = (
        f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.$[{SECTION_IDENTIFIER}].{CmdbObjectMdsKey.VALUES.value}'
        f'.$[].{CmdbObjectMdsRowKey.DATA.value}'
    )

    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id, MDS_SECTION_ID_PATH: section_id},
        update={'$pull': {all_rows_data_path: {CmdbObjectFieldKey.NAME.value: {'$nin': declared_names}}}},
        array_filters=[{f'{SECTION_IDENTIFIER}.{CmdbObjectMdsKey.SECTION_ID.value}': section_id}],
    )


def field_kind_changes(old_fields: list[dict[str, Any]], new_fields: list[dict[str, Any]]) -> list[str]:
    """
    The names of the fields both versions declare whose type differs between them

    A field that keeps its name but changes its type - in the UI: deleted and dropped again as another control
    under the same identifier, in one save - is neither added nor removed, so the name diffs never see it

    Args:
        old_fields (list[dict[str, Any]]): The field definitions before the change
        new_fields (list[dict[str, Any]]): The field definitions after it

    Returns:
        list[str]: The changed field names, sorted
    """
    old_kinds: dict[Any, Any] = {field.get(FieldKey.NAME): field.get(FieldKey.TYPE) for field in old_fields}

    return sorted(
        field[FieldKey.NAME] for field in new_fields
        if field.get(FieldKey.NAME) in old_kinds and old_kinds[field.get(FieldKey.NAME)] != field.get(FieldKey.TYPE)
    )


@dataclass(frozen=True)
class DeclaredKinds:
    """The type's declared fields as parallel ``$literal`` arrays, for lookups inside a pipeline"""
    names: dict[str, Any]
    kinds: dict[str, Any]
    defaults: dict[str, Any]
    reset_names: dict[str, Any]


def build_field_kind_update(
        type_id: int,
        field_definitions: list[dict[str, Any]],
        reset_names: list[str]) -> RawUpdate:
    """
    Stamps every field entry of every object of a type with the type its field declares, resetting the changed ones

    One pipeline ``update_many``, flat ``fields`` and every MDS row alike, nothing read into Python. For an entry of a
    declared field:

    * its name is in ``reset_names`` AND it does not carry the declared type (another one, or none): the field's type
      changed, so the entry becomes ``{name, type: <declared>, value: <the field's default value, or None>}``
    * otherwise its ``type`` is set to the declared one and its value kept - an entry of an unchanged field written
      without a type, or with one the server never declared, is corrected without losing data

    An entry of an undeclared field is left alone (the field alignment removes it). State-based: a second run finds
    every entry stamped and changes nothing, so a half-finished run is completed by running it again. The names,
    types and defaults go in as ``$literal`` arrays, so a name or a default starting with ``$`` stays a value

    Args:
        type_id (int): public_id of the CmdbType
        field_definitions (list[dict[str, Any]]): Every field the type declares
        reset_names (list[str]): The fields whose type changed - their stale entries lose their value

    Returns:
        RawUpdate: The update
    """
    declared: DeclaredKinds = DeclaredKinds(
        names={'$literal': [field[FieldKey.NAME] for field in field_definitions]},
        kinds={'$literal': [field.get(FieldKey.TYPE, FieldType.TEXT.value) for field in field_definitions]},
        defaults={'$literal': [field.get(FieldKey.VALUE) for field in field_definitions]},
        reset_names={'$literal': list(reset_names)},
    )
    fields_key: str = CmdbObjectKey.FIELDS.value
    sections_key: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
    values_key: str = CmdbObjectMdsKey.VALUES.value
    data_key: str = CmdbObjectMdsRowKey.DATA.value

    rows_aligned: dict[str, Any] = map_if_array(f'$$section.{values_key}', 'row', {'$mergeObjects': [
        '$$row', {data_key: map_if_array(f'$$row.{data_key}', 'entry', aligned_entry('entry', declared))},
    ]})

    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update=[Builder.set_({
            fields_key: map_if_array(f'${fields_key}', 'field', aligned_entry('field', declared)),
            sections_key: map_if_array(f'${sections_key}', 'section', {'$mergeObjects': [
                '$$section', {values_key: rows_aligned},
            ]}),
        })],
    )


def map_if_array(path: str, variable: str, expression: Any) -> dict[str, Any]:
    """
    ``$map`` over an array, leaving anything that is not one (missing, null, garbage) exactly as it is

    Args:
        path (str): The array's ``$`` / ``$$`` path
        variable (str): The name the element is bound to
        expression (Any): What each element becomes

    Returns:
        dict[str, Any]: The aggregation expression
    """
    return {'$cond': [{'$isArray': path}, {'$map': {'input': path, 'as': variable, 'in': expression}}, path]}


def aligned_entry(variable: str, declared: DeclaredKinds) -> dict[str, Any]:
    """
    What one field entry becomes: stamped with its declared type, or reset when its field's type changed

    Args:
        variable (str): The name the entry is bound to
        declared (DeclaredKinds): The type's declared fields

    Returns:
        dict[str, Any]: The aggregation expression
    """
    entry: str = f'$${variable}'
    name: str = f'{entry}.{CmdbObjectFieldKey.NAME.value}'
    stored_kind: dict[str, Any] = {'$ifNull': [f'{entry}.{CmdbObjectFieldKey.TYPE.value}', None]}
    position: dict[str, Any] = {'$indexOfArray': [declared.names, name]}
    declared_kind: dict[str, Any] = {'$arrayElemAt': [declared.kinds, position]}
    changed: dict[str, Any] = {'$and': [
        {'$in': [name, declared.reset_names]},
        {'$ne': [stored_kind, declared_kind]},
    ]}

    return {'$cond': [
        {'$in': [name, declared.names]},
        {'$cond': [
            changed,
            {'$mergeObjects': [entry, {
                CmdbObjectFieldKey.TYPE.value: declared_kind,
                CmdbObjectFieldKey.VALUE.value: {'$arrayElemAt': [declared.defaults, position]},
            }]},
            {'$mergeObjects': [entry, {CmdbObjectFieldKey.TYPE.value: declared_kind}]},
        ]},
        entry,
    ]}


def build_person_value_shape_update(type_id: int, single_names: list[str], multiple_names: list[str]) -> RawUpdate:
    """
    Reshapes every person selector value of every object of a type to the shape its field declares

    One pipeline ``update_many``, flat ``fields`` and every MDS row alike, nothing read into Python. An entry of a
    name in ``multiple_names`` becomes a list (a non-list id wrapped, None an empty list); an entry of a name in
    ``single_names`` becomes an id or None (a list's first item, None for an empty list). Every other entry is left
    as it is. A second run changes nothing. The names go in as ``$literal`` arrays

    Args:
        type_id (int): public_id of the CmdbType
        single_names (list[str]): The person selectors holding one object
        multiple_names (list[str]): The person selectors holding several

    Returns:
        RawUpdate: The update
    """
    singles: dict[str, Any] = {'$literal': list(single_names)}
    multiples: dict[str, Any] = {'$literal': list(multiple_names)}
    fields_key: str = CmdbObjectKey.FIELDS.value
    sections_key: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
    values_key: str = CmdbObjectMdsKey.VALUES.value
    data_key: str = CmdbObjectMdsRowKey.DATA.value

    def shaped(variable: str) -> dict[str, Any]:
        entry: str = f'$${variable}'
        name: str = f'{entry}.{CmdbObjectFieldKey.NAME.value}'
        value: dict[str, Any] = {'$ifNull': [f'{entry}.{CmdbObjectFieldKey.VALUE.value}', None]}
        as_list: dict[str, Any] = {'$cond': [
            {'$isArray': value}, value, {'$cond': [{'$eq': [value, None]}, [], [value]]},
        ]}
        as_single: dict[str, Any] = {'$cond': [
            {'$isArray': value}, {'$cond': [{'$gt': [{'$size': value}, 0]}, {'$arrayElemAt': [value, 0]}, None]}, value,
        ]}

        return {'$cond': [
            {'$in': [name, multiples]},
            {'$mergeObjects': [entry, {CmdbObjectFieldKey.VALUE.value: as_list}]},
            {'$cond': [{'$in': [name, singles]},
                       {'$mergeObjects': [entry, {CmdbObjectFieldKey.VALUE.value: as_single}]},
                       entry]},
        ]}

    rows_shaped: dict[str, Any] = map_if_array(f'$$section.{values_key}', 'row', {'$mergeObjects': [
        '$$row', {data_key: map_if_array(f'$$row.{data_key}', 'entry', shaped('entry'))},
    ]})

    return RawUpdate(
        filter_query={CmdbObjectKey.TYPE_ID.value: type_id},
        update=[Builder.set_({
            fields_key: map_if_array(f'${fields_key}', 'field', shaped('field')),
            sections_key: map_if_array(f'${sections_key}', 'section', {'$mergeObjects': [
                '$$section', {values_key: rows_shaped},
            ]}),
        })],
    )
