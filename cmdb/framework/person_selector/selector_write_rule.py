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
What a CmdbObject write may hold in a person selector

Every object write - create, update, patch, bulk update - asks ``check_person_selector_values`` before it stores the
candidate. In order:

1. **shape** - a selector holding one object holds an id or None, one holding several a list of ids, each once; the
   empty forms are canonicalised and the render's ``persons`` expansion is dropped (400)
2. **what the writer cannot see stays** - an update keeps the stored ids of objects the writer may not READ: the render
   withheld them, so a value sent back without them does not mean "remove them"
3. **every id the write introduces** (not stored at that selector before) names an existing object (400), one the
   writer may READ (403), of a type carrying a marker the selector selects (400)

An id already stored is not judged again - the object it names may have changed since, and refusing every later edit
of the holder for it would lock the holder. Reads: none for a type without selectors or a write introducing nothing;
else one projected read of the named objects and one of their types' markers
"""
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.person_selector_rules import is_multiple, selectable_kinds
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.person_selector.person_selector_constants import PersonSelectorWriteError
from cmdb.framework.person_selector.selector_values import (
    SelectorPlace,
    canonicalize_and_check_shapes,
    ids_of,
    selector_entries,
    selector_fields,
    stored_values_by_place,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['SelectorRefusal', 'check_person_selector_values', 'read_object_type_ids']

# Separator between the messages of several refused selectors
REFUSAL_SEPARATOR: str = '; '
MONGO_ID: str = '_id'


@dataclass(frozen=True)
class SelectorRefusal:
    """Why a write is refused: the HTTP status and the message"""
    status: int
    message: str


def read_object_type_ids(objects_manager: ObjectsManager, object_ids: set[int]) -> dict[int, int]:
    """
    The type of each named object that exists

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        object_ids (set[int]): The ids to read

    Raises:
        BaseManagerGetError: When the read fails

    Returns:
        dict[int, int]: The type_id of every id that names an object
    """
    if not object_ids:
        return {}

    return {
        document[CmdbObjectKey.PUBLIC_ID.value]: document.get(CmdbObjectKey.TYPE_ID.value)
        for document in objects_manager.find(
            {CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(object_ids)}},
            projection={MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1},
        )
    }


def _keep_hidden_stored_ids(objects_manager: ObjectsManager,
                            hidden_types: HiddenTypeIds,
                            entries: list[tuple[SelectorPlace, dict[str, Any]]],
                            stored: dict[SelectorPlace, Any],
                            selectors: dict[str, dict[str, Any]]) -> None:
    """
    Puts back the stored ids at each place that name objects the writer may not READ

    A selector holding several gets them appended where the candidate left them out; one holding one keeps its stored
    id when the candidate sends nothing there

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        hidden_types (HiddenTypeIds): The writer's denied Types
        entries (list[tuple[SelectorPlace, dict[str, Any]]]): The candidate's selector entries (changed in place)
        stored (dict[SelectorPlace, Any]): The stored values by place
        selectors (dict[str, dict[str, Any]]): The type's person selectors, by name
    """
    stored_ids: set[int] = {object_id for value in stored.values() for object_id in ids_of(value)}

    if not stored_ids or not hidden_types():
        return

    type_ids: dict[int, int] = read_object_type_ids(objects_manager, stored_ids)
    hidden: set[int] = {object_id for object_id, type_id in type_ids.items() if type_id in hidden_types()}

    for place, entry in entries:
        kept: list[int] = [object_id for object_id in ids_of(stored.get(place)) if object_id in hidden]

        if not kept:
            continue

        value: Any = entry.get(CmdbObjectFieldKey.VALUE.value)

        if is_multiple(selectors[place.name]) and isinstance(value, list):
            value.extend(object_id for object_id in kept if object_id not in value)
        elif not is_multiple(selectors[place.name]) and value is None:
            entry[CmdbObjectFieldKey.VALUE.value] = kept[0]


def _introduced_ids(entries: list[tuple[SelectorPlace, dict[str, Any]]],
                    stored: dict[SelectorPlace, Any]) -> dict[str, set[int]]:
    """
    The ids each selector names that it did not hold before, anywhere in the object

    Args:
        entries (list[tuple[SelectorPlace, dict[str, Any]]]): The candidate's selector entries
        stored (dict[SelectorPlace, Any]): The stored values by place

    Returns:
        dict[str, set[int]]: The introduced ids by selector name; a selector introducing none is absent
    """
    held: dict[str, set[int]] = {}

    for place, value in stored.items():
        held.setdefault(place.name, set()).update(ids_of(value))

    introduced: dict[str, set[int]] = {}

    for place, entry in entries:
        new_ids = set(ids_of(entry.get(CmdbObjectFieldKey.VALUE.value))) - held.get(place.name, set())

        if new_ids:
            introduced.setdefault(place.name, set()).update(new_ids)

    return introduced


def _judge_introduced(types_manager: TypesManager,
                      hidden_types: HiddenTypeIds,
                      introduced: dict[str, set[int]],
                      type_ids: dict[int, int],
                      selectors: dict[str, dict[str, Any]]) -> SelectorRefusal | None:
    """
    Refuses introduced ids naming nothing, an object the writer may not read, or an object of a kind not selectable

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The writer's denied Types
        introduced (dict[str, set[int]]): The introduced ids by selector name
        type_ids (dict[int, int]): The type of every introduced id that names an object
        selectors (dict[str, dict[str, Any]]): The type's person selectors, by name

    Returns:
        SelectorRefusal | None: The first kind of refusal any selector earns, naming every selector earning it
    """
    unknown: list[str] = [
        PersonSelectorWriteError.UNKNOWN.format(name=name, ids=sorted(ids - type_ids.keys()))
        for name, ids in introduced.items() if ids - type_ids.keys()
    ]

    if unknown:
        return SelectorRefusal(HTTPStatus.BAD_REQUEST, REFUSAL_SEPARATOR.join(unknown))

    unreadable: list[str] = [
        PersonSelectorWriteError.NOT_READABLE.format(
            name=name, ids=sorted(object_id for object_id in ids if type_ids[object_id] in hidden_types()),
        )
        for name, ids in introduced.items() if any(type_ids[object_id] in hidden_types() for object_id in ids)
    ]

    if unreadable:
        return SelectorRefusal(HTTPStatus.FORBIDDEN, REFUSAL_SEPARATOR.join(unreadable))

    markers: dict[int, Any] = {
        document[TypeSchemaKey.PUBLIC_ID.value]: document.get(TypeSchemaKey.SPECIAL_TYPE.value)
        for document in types_manager.find(
            {TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(set(type_ids.values()))}},
            projection={MONGO_ID: 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.SPECIAL_TYPE.value: 1},
        )
    }
    not_selectable: list[str] = []

    for name, ids in introduced.items():
        kinds: list[str] = selectable_kinds(selectors[name])
        refused: list[int] = sorted(object_id for object_id in ids if markers.get(type_ids[object_id]) not in kinds)

        if refused:
            not_selectable.append(PersonSelectorWriteError.NOT_SELECTABLE.format(name=name, kinds=kinds, ids=refused))

    if not_selectable:
        return SelectorRefusal(HTTPStatus.BAD_REQUEST, REFUSAL_SEPARATOR.join(not_selectable))

    return None


def check_person_selector_values(objects_manager: ObjectsManager,
                                 types_manager: TypesManager,
                                 hidden_types: HiddenTypeIds,
                                 candidate: dict[str, Any],
                                 type_fields: list[dict[str, Any]] | None,
                                 previous_object: dict[str, Any] | None = None) -> SelectorRefusal | None:
    """
    Judges, and canonicalises in place, every person selector value an object write would store

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The writer's denied Types, read once when needed
        candidate (dict[str, Any]): The document about to be stored (changed in place)
        type_fields (list[dict[str, Any]] | None): The field definitions of the candidate's type
        previous_object (dict[str, Any] | None): The stored document on an update; None on a create

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        SelectorRefusal | None: Why the write is refused, or None when it may be stored
    """
    selectors: dict[str, dict[str, Any]] = selector_fields(type_fields)

    if not selectors:
        return None

    entries = selector_entries(candidate, selectors)
    shape_errors: list[str] = canonicalize_and_check_shapes(entries, selectors)

    if shape_errors:
        return SelectorRefusal(HTTPStatus.BAD_REQUEST, REFUSAL_SEPARATOR.join(shape_errors))

    stored: dict[SelectorPlace, Any] = stored_values_by_place(previous_object, selectors)
    _keep_hidden_stored_ids(objects_manager, hidden_types, entries, stored, selectors)

    introduced: dict[str, set[int]] = _introduced_ids(entries, stored)

    if not introduced:
        return None

    type_ids: dict[int, int] = read_object_type_ids(
        objects_manager, {object_id for ids in introduced.values() for object_id in ids},
    )

    return _judge_introduced(types_manager, hidden_types, introduced, type_ids, selectors)
