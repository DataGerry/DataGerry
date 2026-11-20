# DataGerry - OpenSource Enterprise CMDB
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
What keeps a synced person from moving to its new target Type - judged without reading anything

A person moves keeping its ``public_id`` (``sync_relocation``); every reference to it stays. A move is blocked when
something would break or be lost:

  - **a value the new Type cannot hold**: a non-empty value of a field the new Type does not declare with the same
    kind, or rows of a multi-data section it does not declare
  - **a reference restricted by Type**: another object holds the person in a reference field whose ``ref_types`` do
    not name the new Type, or in a reference section's field - which shows the old Type's fields
  - **an object relation side**: the relation definition does not allow the new Type on the person's side
  - **the location tree**: a placed person's node belongs to its Type's location field

A person selector chooses persons by marker, never by Type - it never blocks. Each check answers its blockers as
sentences (``RelocationBlocker``)
"""
from dataclasses import dataclass, field
from typing import Any, Iterator

from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.type_model import CmdbType, FieldKey
from cmdb.models.type_model.field_type_enum import FieldType

from cmdb.framework.configuration_transfer.best_practice_preview import as_id_list
from cmdb.framework.object_field_value_rules import has_no_value
from cmdb.framework.object_required_fields import mds_section_field_names
from cmdb.framework.person_sync.person_sync_constants import (
    RELOCATION_REFERENCE_KINDS,
    RelocationBlocker,
    RelocationKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonRelocation',
    'type_field_kinds',
    'lost_value_blockers',
    'reference_blockers',
    'relation_blockers',
    'location_blockers',
]

# The relation side a person is on, as a blocker names it
PARENT_SIDE: str = 'parent'
CHILD_SIDE: str = 'child'


@dataclass(frozen=True)
class PersonRelocation:
    """
    One synced person whose target Type changes

    Attributes:
        user_id (int): Its user
        person_id (int): The person
        from_type_id (int): The Type it lives in
        to_type_id (int): Its new target Type
        blockers (tuple[str, ...]): Why it cannot move; empty when it can
    """
    user_id: int
    person_id: int
    from_type_id: int
    to_type_id: int
    blockers: tuple[str, ...] = field(default_factory=tuple)


    @property
    def blocked(self) -> bool:
        """
        Whether the person cannot move

        Returns:
            bool: True when a blocker was found
        """
        return bool(self.blockers)


    def to_json(self) -> dict[str, Any]:
        """
        Answers the relocation as the pre-check does

        Returns:
            dict[str, Any]: ``user_id``, ``person_id``, ``from_type_id``, ``to_type_id`` and ``blockers``
        """
        return {
            RelocationKey.USER_ID.value: self.user_id,
            RelocationKey.PERSON_ID.value: self.person_id,
            RelocationKey.FROM_TYPE_ID.value: self.from_type_id,
            RelocationKey.TO_TYPE_ID.value: self.to_type_id,
            RelocationKey.BLOCKERS.value: list(self.blockers),
        }


def type_field_kinds(type_instance: CmdbType) -> dict[str, Any]:
    """
    Returns each field's kind by name, as the Type declares it

    Args:
        type_instance (CmdbType): The Type

    Returns:
        dict[str, Any]: field name -> kind
    """
    return {definition.get(FieldKey.NAME.value): definition.get(FieldKey.TYPE.value)
            for definition in type_instance.get_fields() or []}


def _lost_names(entries: list[dict[str, Any]], kinds: dict[str, Any], allowed: set[str]) -> list[str]:
    """
    Names the entries holding a value the new Type cannot keep: not among the allowed names, or of another kind

    Args:
        entries (list[dict[str, Any]]): Field entries - an object's ``fields`` or one row's ``data``
        kinds (dict[str, Any]): The new Type's kinds by field name
        allowed (set[str]): The names the list may carry in the new Type

    Returns:
        list[str]: The entry names that would lose a value
    """
    return [
        entry.get(CmdbObjectFieldKey.NAME.value) for entry in entries
        if not has_no_value(entry.get(CmdbObjectFieldKey.VALUE.value))
        and (entry.get(CmdbObjectFieldKey.NAME.value) not in allowed
             or kinds.get(entry.get(CmdbObjectFieldKey.NAME.value)) != entry.get(CmdbObjectFieldKey.TYPE.value))
    ]


def lost_value_blockers(person: dict[str, Any], to_type: CmdbType) -> list[str]:
    """
    Judges whether the new Type can hold every value the person carries

    Args:
        person (dict[str, Any]): The stored person
        to_type (CmdbType): Its new Type

    Returns:
        list[str]: At most one blocker for fields, one for sections
    """
    kinds: dict[str, Any] = type_field_kinds(to_type)
    sections: dict[str, list[str]] = mds_section_field_names(to_type)
    row_names: set[str] = {name for names in sections.values() for name in names}
    lost_fields: list[str] = _lost_names(person.get(CmdbObjectKey.FIELDS.value) or [], kinds,
                                         set(kinds) - row_names)
    lost_sections: list[str] = []

    for section in person.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        section_id: Any = section.get(CmdbObjectMdsKey.SECTION_ID.value)
        rows: list[dict[str, Any]] = section.get(CmdbObjectMdsKey.VALUES.value) or []

        if section_id not in sections:
            if any(not has_no_value(entry.get(CmdbObjectFieldKey.VALUE.value))
                   for row in rows for entry in row.get(CmdbObjectMdsRowKey.DATA.value) or []):
                lost_sections.append(section_id)
            continue

        for row in rows:
            lost_fields.extend(_lost_names(row.get(CmdbObjectMdsRowKey.DATA.value) or [], kinds,
                                           set(sections[section_id])))

    blockers: list[str] = []

    if lost_fields:
        blockers.append(RelocationBlocker.LOST_FIELDS.value.format(names=sorted(set(lost_fields)),
                                                                   type_id=to_type.public_id))

    if lost_sections:
        blockers.append(RelocationBlocker.LOST_SECTIONS.value.format(names=sorted(lost_sections),
                                                                     type_id=to_type.public_id))

    return blockers


def _reference_entries(holder: dict[str, Any], person_id: int) -> Iterator[dict[str, Any]]:
    """
    Yields every reference entry of an object - fields and multi-data rows - that holds the person

    Args:
        holder (dict[str, Any]): The referencing object
        person_id (int): The person

    Yields:
        dict[str, Any]: The entries of a reference kind whose value is the person
    """
    entries: list[dict[str, Any]] = list(holder.get(CmdbObjectKey.FIELDS.value) or [])

    for section in holder.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            entries.extend(row.get(CmdbObjectMdsRowKey.DATA.value) or [])

    for entry in entries:
        if (entry.get(CmdbObjectFieldKey.TYPE.value) in RELOCATION_REFERENCE_KINDS
                and entry.get(CmdbObjectFieldKey.VALUE.value) == person_id):
            yield entry


def reference_blockers(person_id: int, to_type_id: int, holders: list[dict[str, Any]],
                       holder_types: dict[int, CmdbType]) -> list[str]:
    """
    Judges the references other objects hold to the person against its new Type

    Args:
        person_id (int): The person
        to_type_id (int): Its new Type
        holders (list[dict[str, Any]]): The objects holding a reference value - any person's; each is searched
        holder_types (dict[int, CmdbType]): Their Types by id

    Returns:
        list[str]: One blocker per reference that would not allow the new Type
    """
    blockers: list[str] = []

    for holder in holders:
        holder_id: int = holder[CmdbObjectKey.PUBLIC_ID.value]
        holder_type: CmdbType | None = holder_types.get(holder[CmdbObjectKey.TYPE_ID.value])
        definitions: dict[str, dict[str, Any]] = {
            definition.get(FieldKey.NAME.value): definition
            for definition in (holder_type.get_fields() if holder_type is not None else None) or []
        }

        for entry in _reference_entries(holder, person_id):
            name: Any = entry.get(CmdbObjectFieldKey.NAME.value)

            if entry.get(CmdbObjectFieldKey.TYPE.value) == FieldType.REF_SECTION.value:
                blockers.append(RelocationBlocker.REFERENCE_SECTION.value.format(holder_id=holder_id, name=name))
                continue

            allowed: list[int] = as_id_list(definitions.get(name, {}).get(FieldKey.REF_TYPES.value))

            if to_type_id not in allowed:
                blockers.append(RelocationBlocker.REFERENCE_FIELD.value.format(holder_id=holder_id, name=name,
                                                                               type_ids=allowed))

    return blockers


def relation_blockers(person_id: int, to_type_id: int, relations: list[dict[str, Any]],
                      definitions: dict[int, dict[str, Any]]) -> list[str]:
    """
    Judges the person's object relations: the definition must allow the new Type on the person's side

    Args:
        person_id (int): The person
        to_type_id (int): Its new Type
        relations (list[dict[str, Any]]): The object relations - any person's; the person's sides are judged
        definitions (dict[int, dict[str, Any]]): The relation definitions by id

    Returns:
        list[str]: One blocker per side that would not allow the new Type
    """
    blockers: list[str] = []
    sides: tuple[tuple[str, str, str], ...] = (
        (ObjectRelationKey.RELATION_PARENT_ID.value, RelationKey.PARENT_TYPE_IDS.value, PARENT_SIDE),
        (ObjectRelationKey.RELATION_CHILD_ID.value, RelationKey.CHILD_TYPE_IDS.value, CHILD_SIDE),
    )

    for relation in relations:
        definition_id: Any = relation.get(ObjectRelationKey.RELATION_ID.value)
        definition: dict[str, Any] = definitions.get(definition_id, {})

        for id_key, allowed_key, side in sides:
            allowed: list[int] = as_id_list(definition.get(allowed_key))

            if relation.get(id_key) == person_id and to_type_id not in allowed:
                blockers.append(RelocationBlocker.RELATION_SIDE.value.format(
                    relation_id=relation.get(ObjectRelationKey.PUBLIC_ID.value), definition_id=definition_id,
                    type_ids=allowed, side=side))

    return blockers


def location_blockers(person_id: int, placed_ids: set[int]) -> list[str]:
    """
    Judges whether the person is placed in the location tree

    Args:
        person_id (int): The person
        placed_ids (set[int]): The objects with a location node

    Returns:
        list[str]: The blocker when it is placed
    """
    return [RelocationBlocker.LOCATION.value] if person_id in placed_ids else []
