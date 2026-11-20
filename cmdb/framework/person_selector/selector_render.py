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
The person selections of rendered CmdbObjects: what the render user may see of a selection, and how it is labelled

After a render, every surface showing a person selection keeps only the objects the render user may READ that still
exist and carry PERSON or PERSON_GROUP; the others are withheld, as an unreadable reference is. A selector field - the
object's own, or one pulled into a reference section - also gets the ``persons`` expansion: one entry per kept object
with its id, type, kind, label (the base field ``display_name`` of a person, ``name`` of a group), active state and
``system_ref`` (the user sync's link, null when there is none) - a deactivated person a selector still holds is shown,
marked; a multi-data row keeps ids, labelled through the picker
route's id lookup; summaries, reference lines and links show the labels as
text or leave the link out (``selector_surfaces``).

One pass for the whole render: one projected read of every selected object and one of their types, for every result
at once - none when nothing is selected. ``resolve_person_selections`` is shared with the picker and the CI Explorer
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.person_selector.person_selector_constants import LABEL_FIELD_BY_KIND, PersonSelectionKey
from cmdb.framework.person_selector.selector_surfaces import (
    PersonSurfaces,
    apply_to_reference,
    collect_render_surfaces,
    reference_person_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'apply_person_selector_render',
    'apply_person_selector_reference',
    'resolve_person_selections',
    'selection_entry',
]

MONGO_ID: str = '_id'


def selection_entry(document: dict[str, Any], type_document: dict[str, Any]) -> dict[str, Any]:
    """
    One rendered selection: the object, its type, its kind, its label, whether it is active and its sync link

    An object stored without the flag counts as active, as the object model reads it; one without a ``system_ref`` is
    not synced

    Args:
        document (dict[str, Any]): The selected object, with its ``fields``, ``active`` and ``system_ref``
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
        PersonSelectionKey.ACTIVE.value: document.get(CmdbObjectKey.ACTIVE.value, True) is not False,
        PersonSelectionKey.SYSTEM_REF.value: document.get(CmdbObjectKey.SYSTEM_REF.value),
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
                    CmdbObjectKey.FIELDS.value: 1, CmdbObjectKey.ACTIVE.value: 1, CmdbObjectKey.SYSTEM_REF.value: 1},
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


def apply_person_selector_render(rendered: list[tuple[RenderResult, CmdbType]],
                                 objects_manager: ObjectsManager,
                                 types_manager: TypesManager,
                                 hidden_types: HiddenTypeIds) -> None:
    """
    Rewrites every person surface of the rendered objects to what the render user may see

    The surfaces are ``selector_surfaces``': own selectors (flat + rows), pulled-in selectors, reference summaries and
    lines, own summaries and the summary line, external links. Their ids are resolved once for all results

    Args:
        rendered (list[tuple[RenderResult, CmdbType]]): Each render result with its object's type (changed in place)
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The render user's denied Types

    Raises:
        BaseManagerGetError: When a read fails
    """
    surfaces: list[PersonSurfaces] = [collect_render_surfaces(result, object_type) for result, object_type in rendered]
    selected: set[int] = {object_id for surface in surfaces for object_id in surface.ids()}
    visible: dict[int, dict[str, Any]] = resolve_person_selections(objects_manager, types_manager, hidden_types,
                                                                   selected)

    for surface in surfaces:
        surface.apply(visible)


def apply_person_selector_reference(reference: dict[str, Any],
                                    objects_manager: ObjectsManager,
                                    types_manager: TypesManager,
                                    hidden_types: HiddenTypeIds) -> None:
    """
    Rewrites the person summary values and the line of one reference payload built outside a render

    Args:
        reference (dict[str, Any]): The reference payload (changed in place)
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The reader's denied Types

    Raises:
        BaseManagerGetError: When a read fails
    """
    visible: dict[int, dict[str, Any]] = resolve_person_selections(objects_manager, types_manager, hidden_types,
                                                                   reference_person_ids(reference))
    apply_to_reference(reference, visible)
