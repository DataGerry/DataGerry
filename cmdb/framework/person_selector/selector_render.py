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
The person selectors of rendered CmdbObjects: what the render user may see of a selection, and how it is labelled

After a render, every person selector value - flat and in every multi-data row - keeps only the objects the render
user may READ that still exist and carry PERSON or PERSON_GROUP; the others are withheld, as an unreadable reference
is. A flat selector also gets the ``persons`` expansion: one entry per kept object with its id, type, kind and label
(the base field ``display_name`` of a person, ``name`` of a group). The labels of a row's selections come from the
picker route's id lookup.

One pass for the whole render: one projected read of every selected object and one of their types, for every result
at once - none when nothing is selected. ``resolve_person_selections`` is shared with the picker
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.person_selector_rules import is_multiple
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.rendering.render_constants import RenderedFieldKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.person_selector.person_selector_constants import LABEL_FIELD_BY_KIND, PersonSelectionKey
from cmdb.framework.person_selector.selector_values import ids_of, selector_fields
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['apply_person_selector_render', 'resolve_person_selections', 'selection_entry']

MONGO_ID: str = '_id'


def selection_entry(document: dict[str, Any], type_document: dict[str, Any]) -> dict[str, Any]:
    """
    One rendered selection: the object, its type, its kind and its label

    Args:
        document (dict[str, Any]): The selected object, with its ``fields``
        type_document (dict[str, Any]): Its type, with its ``label`` and ``special_type``

    Returns:
        dict[str, Any]: The selection under ``PersonSelectionKey``
    """
    kind = SpecialType(type_document[TypeSchemaKey.SPECIAL_TYPE.value])
    label_field: str = LABEL_FIELD_BY_KIND[kind]
    label: Any = next((entry.get(CmdbObjectFieldKey.VALUE.value) for entry in document.get(CmdbObjectKey.FIELDS.value)
                       or [] if entry.get(CmdbObjectFieldKey.NAME.value) == label_field), None)

    return {
        PersonSelectionKey.OBJECT_ID.value: document[CmdbObjectKey.PUBLIC_ID.value],
        PersonSelectionKey.TYPE_ID.value: type_document[TypeSchemaKey.PUBLIC_ID.value],
        PersonSelectionKey.TYPE_LABEL.value: type_document.get(TypeSchemaKey.LABEL.value),
        PersonSelectionKey.KIND.value: kind.value,
        PersonSelectionKey.LABEL.value: label,
    }


def resolve_person_selections(objects_manager: ObjectsManager,
                              types_manager: TypesManager,
                              hidden_types: HiddenTypeIds,
                              object_ids: set[int]) -> dict[int, dict[str, Any]]:
    """
    The selections the reader may see among the given ids: existing objects of a readable type carrying a person marker

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The reader's denied Types
        object_ids (set[int]): The ids to resolve

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        dict[int, dict[str, Any]]: The rendered selection of every visible id
    """
    if not object_ids:
        return {}

    documents: list[dict[str, Any]] = objects_manager.find(
        {CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(object_ids)}},
        projection={MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1,
                    CmdbObjectKey.FIELDS.value: 1},
    )
    type_ids: set[int] = {document.get(CmdbObjectKey.TYPE_ID.value) for document in documents} - set(hidden_types())

    if not type_ids:
        return {}

    types: dict[int, dict[str, Any]] = {
        document[TypeSchemaKey.PUBLIC_ID.value]: document
        for document in types_manager.find(
            {TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(type_ids)},
             TypeSchemaKey.SPECIAL_TYPE.value: {'$in': [kind.value for kind in LABEL_FIELD_BY_KIND]}},
            projection={MONGO_ID: 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.LABEL.value: 1,
                        TypeSchemaKey.SPECIAL_TYPE.value: 1},
        )
    }

    return {
        document[CmdbObjectKey.PUBLIC_ID.value]: selection_entry(document, types[document[CmdbObjectKey.TYPE_ID.value]])
        for document in documents if document.get(CmdbObjectKey.TYPE_ID.value) in types
    }


def _row_entries(result: RenderResult, selectors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The selector entries of every multi-data row of a rendered object"""
    return [
        entry
        for section in result.multi_data_sections or [] if isinstance(section, dict)
        for row in section.get(CmdbObjectMdsKey.VALUES.value) or [] if isinstance(row, dict)
        for entry in row.get(CmdbObjectMdsRowKey.DATA.value) or []
        if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) in selectors
    ]


def _flat_entries(result: RenderResult, selectors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The rendered flat fields of a rendered object that are person selectors"""
    return [field for field in result.fields or [] if field.get(FieldKey.NAME.value) in selectors]


def _kept(value: Any, multiple: bool, visible: dict[int, dict[str, Any]]) -> Any:
    """A selector value with every id the reader may not see taken out"""
    kept: list[int] = [object_id for object_id in ids_of(value) if object_id in visible]

    if multiple:
        return kept

    return kept[0] if kept else None


def apply_person_selector_render(rendered: list[tuple[RenderResult, CmdbType]],
                                 objects_manager: ObjectsManager,
                                 types_manager: TypesManager,
                                 hidden_types: HiddenTypeIds) -> None:
    """
    Withholds what the render user may not see of every person selector, and expands the flat ones

    Args:
        rendered (list[tuple[RenderResult, CmdbType]]): Each render result with its object's type (changed in place)
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The render user's denied Types

    Raises:
        BaseManagerGetError: When a read fails
    """
    with_selectors: list[tuple[RenderResult, dict[str, dict[str, Any]]]] = [
        (result, selectors) for result, object_type in rendered
        if (selectors := selector_fields(object_type.fields))
    ]

    if not with_selectors:
        return

    selected: set[int] = {
        object_id
        for result, selectors in with_selectors
        for entry in _flat_entries(result, selectors) + _row_entries(result, selectors)
        for object_id in ids_of(entry.get(FieldKey.VALUE.value))
    }
    visible: dict[int, dict[str, Any]] = resolve_person_selections(objects_manager, types_manager, hidden_types,
                                                                   selected)

    for result, selectors in with_selectors:
        for field in _flat_entries(result, selectors):
            multiple: bool = is_multiple(selectors[field[FieldKey.NAME.value]])
            field[FieldKey.VALUE.value] = _kept(field.get(FieldKey.VALUE.value), multiple, visible)
            field[RenderedFieldKey.PERSONS.value] = [visible[object_id]
                                                     for object_id in ids_of(field[FieldKey.VALUE.value])]

        for entry in _row_entries(result, selectors):
            multiple = is_multiple(selectors[entry[CmdbObjectFieldKey.NAME.value]])
            entry[CmdbObjectFieldKey.VALUE.value] = _kept(entry.get(CmdbObjectFieldKey.VALUE.value), multiple, visible)
