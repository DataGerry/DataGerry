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
Pure helpers for the value of a person field (FieldType.PERSON)

A single person field stores one ``{'ref_type': ..., 'id': ...}`` pair or None, a multiple one a list of
those pairs. Nothing here touches the database: the shape is canonicalised and judged here, whether the ids
exist is the enforcement's business
"""
from typing import Any, Iterator

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.person_constants import PersonRefKind, PersonValueKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'allowed_ref_types',
    'get_person_field_definitions',
    'is_public_id',
    'iter_person_entries',
    'normalize_person_value',
    'person_value_errors',
    'referenced_ids',
    'selections_of',
]


def is_public_id(value: Any) -> bool:
    """
    Answers whether a value can name a stored document

    Args:
        value (Any): The candidate id

    Returns:
        bool: True for an integer that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def allowed_ref_types(field_definition: dict[str, Any]) -> frozenset[str]:
    """
    The SpecialType tokens a person field may select

    A field without a 'person_ref_kind' allows both, so a hand-written type stays usable

    Args:
        field_definition (dict[str, Any]): The person field's definition on its CmdbType

    Returns:
        frozenset[str]: A subset of {'PERSON', 'PERSON_GROUP'}
    """
    kind: Any = field_definition.get(FieldKey.PERSON_REF_KIND.value) or PersonRefKind.BOTH.value

    if kind == PersonRefKind.PERSON.value:
        return frozenset({SpecialType.PERSON.value})

    if kind == PersonRefKind.PERSON_GROUP.value:
        return frozenset({SpecialType.PERSON_GROUP.value})

    return frozenset({SpecialType.PERSON.value, SpecialType.PERSON_GROUP.value})


def get_person_field_definitions(type_fields: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """
    The person fields of a CmdbType, by name

    Args:
        type_fields (list[dict[str, Any]] | None): The 'fields' list of a CmdbType

    Returns:
        dict[str, dict[str, Any]]: {field name: field definition} of every FieldType.PERSON field
    """
    return {
        field[FieldKey.NAME.value]: field
        for field in type_fields or []
        if isinstance(field, dict) and field.get(FieldKey.TYPE.value) == FieldType.PERSON.value
        and isinstance(field.get(FieldKey.NAME.value), str)
    }


def iter_person_entries(
        object_data: dict[str, Any],
        person_fields: dict[str, dict[str, Any]]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """
    Every stored entry of a CmdbObject that belongs to one of the given person fields

    Covers the top-level 'fields' list and the rows of every multi-data-section, so a person field inside an
    MDS is judged like any other

    Args:
        object_data (dict[str, Any]): A CmdbObject document
        person_fields (dict[str, dict[str, Any]]): The type's person fields, by name

    Yields:
        tuple[dict[str, Any], dict[str, Any]]: (the entry, edited in place by a caller, its field definition)
    """
    entries: list[Any] = list(object_data.get(CmdbObjectKey.FIELDS.value) or [])

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        if not isinstance(section, dict):
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            if isinstance(row, dict):
                entries.extend(row.get(CmdbObjectMdsRowKey.DATA.value) or [])

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        definition: dict[str, Any] | None = person_fields.get(entry.get(CmdbObjectFieldKey.NAME.value))

        if definition is not None:
            yield entry, definition


def normalize_person_value(value: Any, multiple: bool) -> Any:
    """
    Canonicalises a person field's value to the stored shape

    The empty values become None (single) or [] (multiple); a single pair sent to a multiple field becomes a
    one-entry list and a one-entry list sent to a single field becomes the pair. Duplicate ids of a list are
    dropped, keeping the first. Anything else is returned as given for person_value_errors to reject

    Args:
        value (Any): The value as sent
        multiple (bool): The field's 'multiple' flag

    Returns:
        Any: The canonical value, or the unchanged value when it has no recognisable shape
    """
    if value is None or value == '' or value == [] or value == {}:
        return [] if multiple else None

    if multiple:
        if isinstance(value, dict):
            value = [value]

        if not isinstance(value, list):
            return value

        seen: set[Any] = set()
        unique: list[Any] = []

        for selection in value:
            selection_id: Any = selection.get(PersonValueKey.ID.value) if isinstance(selection, dict) else None

            if is_public_id(selection_id):
                if selection_id in seen:
                    continue

                seen.add(selection_id)

            unique.append(selection)

        return unique

    if isinstance(value, list) and len(value) == 1:
        return value[0]

    return value


def selections_of(value: Any) -> list[Any]:
    """
    The selections a canonical person value holds

    Args:
        value (Any): A canonical person value (None, one pair or a list of pairs)

    Returns:
        list[Any]: The pairs, unvalidated; empty for None
    """
    if value is None:
        return []

    return list(value) if isinstance(value, list) else [value]


def person_value_errors(field_name: str, value: Any, field_definition: dict[str, Any]) -> list[str]:
    """
    Judges the shape of a canonical person value against its field definition

    Args:
        field_name (str): The field's name, for the messages
        value (Any): The canonical value (see normalize_person_value)
        field_definition (dict[str, Any]): The field's definition on its CmdbType

    Returns:
        list[str]: One message per problem; empty when the shape is valid
    """
    multiple: bool = bool(field_definition.get(FieldKey.MULTIPLE.value))

    if multiple and not isinstance(value, list):
        return [f"The person field '{field_name}' expects a list of selections"]

    if not multiple and value is not None and not isinstance(value, dict):
        return [f"The person field '{field_name}' expects a single selection"]

    allowed: frozenset[str] = allowed_ref_types(field_definition)
    errors: list[str] = []

    for selection in selections_of(value):
        if not isinstance(selection, dict) or set(selection) != {PersonValueKey.REF_TYPE.value, PersonValueKey.ID.value}:
            errors.append(
                f"A selection of the person field '{field_name}' must be an object with exactly "
                f"'{PersonValueKey.REF_TYPE.value}' and '{PersonValueKey.ID.value}'"
            )
            continue

        if selection[PersonValueKey.REF_TYPE.value] not in allowed:
            errors.append(
                f"The person field '{field_name}' does not allow '{selection[PersonValueKey.REF_TYPE.value]}' "
                f"(allowed: {sorted(allowed)})"
            )

        if not is_public_id(selection[PersonValueKey.ID.value]):
            errors.append(f"The person field '{field_name}' holds an id that is not a public_id")

    return errors


def referenced_ids(value: Any) -> list[tuple[str, int]]:
    """
    The (ref_type, id) pairs a canonical, shape-checked person value references

    Args:
        value (Any): A canonical person value

    Returns:
        list[tuple[str, int]]: One pair per valid selection
    """
    return [
        (selection[PersonValueKey.REF_TYPE.value], selection[PersonValueKey.ID.value])
        for selection in selections_of(value)
        if isinstance(selection, dict) and is_public_id(selection.get(PersonValueKey.ID.value))
    ]
