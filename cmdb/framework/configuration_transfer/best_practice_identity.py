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
What two entries of one name from two best-practice models are compared on

Each model numbers its entries from 1, so an id means something only inside its own file. Before two entries are
compared, every id they hold is replaced by the name it stands for in its file (``comparable_type`` and its siblings),
and the keys the combination ignores are left out (``TYPE_IGNORED_KEYS`` and the others in ``best_practice_constants``).
A list of target types - a reference field's ``ref_types``, a relation side - is compared as a set: which types it
names matters, not in which order. The order of fields and sections does matter, it is what a user sees.

``differing_parts`` names what differs: the top-level keys, and inside ``render_meta`` the nested key (for instance
``render_meta.sections``). Nothing here reads a database
"""
from copy import deepcopy
from typing import Any

from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.configuration_transfer.best_practice_constants import (
    CATEGORY_COMPARED_KEYS,
    NESTED_PART,
    RELATION_IGNORED_KEYS,
    SECTION_TEMPLATE_IGNORED_KEYS,
    TYPE_IGNORED_KEYS,
    TYPE_IGNORED_RENDER_META_KEYS,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'comparable_category',
    'comparable_relation',
    'comparable_section_template',
    'comparable_type',
    'differing_parts',
    'is_id',
    'names_by_id',
]


def is_id(value: Any) -> bool:
    """
    Whether a stored value is a public_id: a whole number, a boolean excluded

    Args:
        value (Any): The stored value

    Returns:
        bool: True for an int that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def names_by_id(items: list[dict[str, Any]], name_key: str) -> dict[int, Any]:
    """
    Maps each entry's public_id to its name, inside one file

    Args:
        items (list[dict[str, Any]]): The entries of one component of one file
        name_key (str): The key holding the entry's name

    Returns:
        dict[int, Any]: public_id -> name, for every entry whose public_id is an id
    """
    return {item[TypeSchemaKey.PUBLIC_ID.value]: item.get(name_key) for item in items
            if is_id(item.get(TypeSchemaKey.PUBLIC_ID.value))}


def _target_names(value: Any, type_names: dict[int, Any]) -> list[str]:
    """
    The names of the types a stored target value names, as a sorted set

    The value is one id or a list of them, a list entry possibly a list itself (``ref_types``). An id the file does not
    hold is kept as its id - it can then only equal the same unknown id

    Args:
        value (Any): The stored value
        type_names (dict[int, Any]): The file's type public_id -> name

    Returns:
        list[str]: The distinct names, sorted
    """
    values: list[Any] = value if isinstance(value, list) else [value]
    flat: list[Any] = [nested for item in values for nested in (item if isinstance(item, list) else [item])]

    return sorted({str(type_names.get(item, item)) for item in flat if item is not None})


def comparable_type(item: dict[str, Any], type_names: dict[int, Any]) -> dict[str, Any]:
    """
    A type entry as two models' types of one name are compared

    The ignored keys are left out, ``render_meta`` without its ignored keys; a reference field's targets and a
    reference section's type are replaced by the names of the types they name

    Args:
        item (dict[str, Any]): The type entry
        type_names (dict[int, Any]): Its file's type public_id -> name

    Returns:
        dict[str, Any]: A new dict - the entry is not changed
    """
    comparable: dict[str, Any] = {key: deepcopy(value) for key, value in item.items() if key not in TYPE_IGNORED_KEYS}

    for field in comparable.get(TypeSchemaKey.FIELDS.value) or []:
        if isinstance(field, dict) and FieldKey.REF_TYPES.value in field:
            field[FieldKey.REF_TYPES.value] = _target_names(field[FieldKey.REF_TYPES.value], type_names)

    render_meta: Any = comparable.get(TypeSchemaKey.RENDER_META.value)

    if isinstance(render_meta, dict):
        render_meta = {key: value for key, value in render_meta.items() if key not in TYPE_IGNORED_RENDER_META_KEYS}
        comparable[TypeSchemaKey.RENDER_META.value] = render_meta

        for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
            reference: Any = section.get(SectionKey.REFERENCE.value) if isinstance(section, dict) else None

            if isinstance(reference, dict) and SectionReferenceKey.TYPE_ID.value in reference:
                reference[SectionReferenceKey.TYPE_ID.value] = _target_names(
                    reference[SectionReferenceKey.TYPE_ID.value], type_names,
                )

    return comparable


def comparable_section_template(item: dict[str, Any]) -> dict[str, Any]:
    """
    A section template entry as two models' templates of one name are compared

    Args:
        item (dict[str, Any]): The template entry

    Returns:
        dict[str, Any]: The entry without the ignored keys
    """
    return {key: value for key, value in item.items() if key not in SECTION_TEMPLATE_IGNORED_KEYS}


def comparable_relation(item: dict[str, Any], type_names: dict[int, Any]) -> dict[str, Any]:
    """
    A relation entry as two models' relations of one name are compared - both sides by the names of their types

    Args:
        item (dict[str, Any]): The relation entry
        type_names (dict[int, Any]): Its file's type public_id -> name

    Returns:
        dict[str, Any]: A new dict - the entry is not changed
    """
    comparable: dict[str, Any] = {key: value for key, value in item.items() if key not in RELATION_IGNORED_KEYS}

    for side in (RelationKey.PARENT_TYPE_IDS.value, RelationKey.CHILD_TYPE_IDS.value):
        if side in comparable:
            comparable[side] = _target_names(comparable[side], type_names)

    return comparable


def comparable_category(item: dict[str, Any], category_names: dict[int, Any]) -> dict[str, Any]:
    """
    A category entry as two models' categories of one name are compared: its label and its parent's name

    Its types are combined, not compared; its meta (icon, order) is the first model's

    Args:
        item (dict[str, Any]): The category entry
        category_names (dict[int, Any]): Its file's category public_id -> name

    Returns:
        dict[str, Any]: ``{label, parent}``
    """
    comparable: dict[str, Any] = {key: item.get(key) for key in CATEGORY_COMPARED_KEYS}
    parent: Any = comparable.get(CategoryKey.PARENT.value)

    if parent is not None:
        comparable[CategoryKey.PARENT.value] = category_names.get(parent, parent)

    return comparable


def differing_parts(first: dict[str, Any], other: dict[str, Any]) -> list[str]:
    """
    The parts in which two comparable entries differ

    A key one of them lacks differs. Inside ``render_meta`` the nested keys are named (``render_meta.sections``)

    Args:
        first (dict[str, Any]): The first model's comparable entry
        other (dict[str, Any]): The other model's comparable entry

    Returns:
        list[str]: The differing parts, sorted; empty when the entries are equal
    """
    parts: list[str] = []

    for key in sorted(set(first) | set(other)):
        first_value: Any = first.get(key)
        other_value: Any = other.get(key)

        if first_value == other_value and (key in first) == (key in other):
            continue

        if key == TypeSchemaKey.RENDER_META.value and isinstance(first_value, dict) \
                and isinstance(other_value, dict):
            parts += [NESTED_PART.format(key=key, nested=nested)
                      for nested in sorted(set(first_value) | set(other_value))
                      if first_value.get(nested) != other_value.get(nested)
                      or (nested in first_value) != (nested in other_value)]
            continue

        parts.append(key)

    return parts
