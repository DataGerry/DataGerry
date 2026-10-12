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
The person source of the CI Explorer: the persons and groups a person field (FieldType.PERSON) connects

One hop in each direction:

* **children** - the persons and groups the focal object's person fields select. For a group this includes its
  members, since membership is the group's MEMBERS person field
* **parents** - the objects whose person fields select the focal object - for a person that includes the groups
  listing them

Every edge carries ``metadata.source='person'`` and the label of the person field that makes it
"""
from dataclasses import dataclass
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey
from cmdb.models.special_type_model.person_constants import PersonValueKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.framework.person.person_values import get_person_field_definitions, iter_person_entries, referenced_ids
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_RELATION_COLOR: str = '#16A34A'
PERSON_RELATION_LABEL: str = 'assigned'
PERSON_RELATION_ICON: str = 'fas fa-user'
PERSON_METADATA_SOURCE: str = 'person'

_ROW_TYPE: str = CmdbObjectFieldKey.TYPE.value
_ROW_VALUE_ID: str = f'{CmdbObjectFieldKey.VALUE.value}.{PersonValueKey.ID.value}'


@dataclass(frozen=True)
class PersonNeighbour:
    """
    One object connected to the focal object through a person field

    Attributes:
        neighbour_object: The neighbour's object document
        is_child_of_target: True when a person field of the focal object selects the neighbour, False when a
            person field of the neighbour selects the focal object
        field_label: The label of the person field making the connection
    """
    neighbour_object: dict[str, Any]
    is_child_of_target: bool
    field_label: str


def _field_labels(type_doc: dict[str, Any] | None) -> dict[str, str]:
    """
    The person fields of a CmdbType document, mapped to their labels

    Args:
        type_doc (dict[str, Any] | None): The CmdbType document

    Returns:
        dict[str, str]: {field name: label}
    """
    return {
        name: definition.get(FieldKey.LABEL.value) or name
        for name, definition in get_person_field_definitions((type_doc or {}).get(TypeSchemaKey.FIELDS.value)).items()
    }


def collect_person_neighbours(
        target_id: int,
        target_object: dict[str, Any],
        include_parents: bool,
        include_children: bool,
        types_filter: frozenset[int],
        remaining: int,
        item_limit_active: bool,
        objects_manager: ObjectsManager,
        types_manager: TypesManager) -> list[PersonNeighbour]:
    """
    Collects the person-field neighbours of the focal object, one hop in each requested direction

    Args:
        target_id (int): public_id of the focal object
        target_object (dict[str, Any]): The focal object's document
        include_parents (bool): Whether the objects selecting the focal object are collected
        include_children (bool): Whether the persons and groups the focal object selects are collected
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty disables filtering
        remaining (int): Slot budget still available; only honoured when ``item_limit_active``
        item_limit_active (bool): Whether the route is operating under an item_limit cap
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        list[PersonNeighbour]: The neighbours, children first; a neighbour reached both ways appears once per way
    """
    if item_limit_active and remaining <= 0:
        return []

    neighbours: list[PersonNeighbour] = []

    if include_children:
        labels: dict[str, str] = _field_labels(types_manager.get_type(target_object.get(CmdbObjectKey.TYPE_ID)))
        selected: dict[int, str] = {}

        for entry, _ in iter_person_entries(target_object, {name: {} for name in labels}):
            for _, object_id in referenced_ids(entry.get(CmdbObjectFieldKey.VALUE.value)):
                selected.setdefault(object_id, labels[entry[CmdbObjectFieldKey.NAME.value]])

        selected.pop(target_id, None)

        if selected:
            criteria: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID.value: {'$in': list(selected)}}

            if types_filter:
                criteria[CmdbObjectKey.TYPE_ID.value] = {'$in': list(types_filter)}

            neighbours.extend(
                PersonNeighbour(document, True, selected[document[CmdbObjectKey.PUBLIC_ID.value]])
                for document in objects_manager.find(criteria)
            )

    if include_parents:
        row_match: dict[str, Any] = {_ROW_TYPE: FieldType.PERSON.value, _ROW_VALUE_ID: target_id}
        criteria = {
            '$or': [
                {CmdbObjectKey.FIELDS.value: {'$elemMatch': row_match}},
                {'multi_data_sections.values.data': {'$elemMatch': row_match}},
            ],
            CmdbObjectKey.PUBLIC_ID.value: {'$ne': target_id},
        }

        if types_filter:
            criteria[CmdbObjectKey.TYPE_ID.value] = {'$in': list(types_filter)}

        type_labels: dict[int, dict[str, str]] = {}

        for document in objects_manager.find(criteria):
            type_id: int = document[CmdbObjectKey.TYPE_ID.value]

            if type_id not in type_labels:
                type_labels[type_id] = _field_labels(types_manager.get_type(type_id))

            label: str = next(
                (
                    type_labels[type_id][entry[CmdbObjectFieldKey.NAME.value]]
                    for entry, _ in iter_person_entries(document, {name: {} for name in type_labels[type_id]})
                    if any(object_id == target_id
                           for _, object_id in referenced_ids(entry.get(CmdbObjectFieldKey.VALUE.value)))
                ),
                PERSON_RELATION_LABEL,
            )
            neighbours.append(PersonNeighbour(document, False, label))

    if item_limit_active and len(neighbours) > remaining:
        neighbours = neighbours[:remaining]

    return neighbours


def compose_person_edge(edge_from: int, edge_to: int, field_label: str) -> dict[str, Any]:
    """
    Builds one person edge dict for the CI Explorer response

    The shape mirrors ``compose_ipam_edge``: no CmdbRelation backs the edge, so ``relation_id`` is None, and
    ``metadata.source='person'`` lets the frontend style it. Name and label are the person field's label - the
    text the edge is drawn with

    Args:
        edge_from (int): public_id of the object whose person field makes the connection
        edge_to (int): public_id of the selected person or group
        field_label (str): The label of that person field

    Returns:
        dict[str, Any]: ``{from, to, metadata: {relation_id, relation_name, relation_label, relation_icon,
            relation_color, source}}``
    """
    return {
        'from': edge_from,
        'to': edge_to,
        'metadata': {
            'relation_id': None,
            'relation_name': field_label,
            'relation_label': field_label,
            'relation_icon': PERSON_RELATION_ICON,
            'relation_color': PERSON_RELATION_COLOR,
            'source': PERSON_METADATA_SOURCE,
        },
    }
