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
The settings of a person selector field (``FieldType.PERSON``) - what a field definition must carry, and how it reads

A person selector stores the public_id of an object whose type carries the PERSON or PERSON_GROUP marker. Its
definition says which of the two may be selected (``selectable``: PERSON and / or PERSON_GROUP, each once, at least
one) and whether one object or several (``multiple``: a boolean; the value is then a list of ids instead of one id or
None). It carries no default value: a default would be an object id, which no type can know in advance.

The type write routes, both type-import verbs and the section-template writes judge a definition by
``person_selector_problems``; everything that reads one stored definition uses ``selectable_kinds`` / ``is_multiple``
"""
from typing import Any

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_constants import PersonSelectorError
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SELECTABLE_KINDS',
    'is_person_selector',
    'is_multiple',
    'selectable_kinds',
    'person_selector_problems',
    'person_value_shapes',
    'person_value_shape_changed',
]

# What a person selector may select: the objects of the types carrying these markers
SELECTABLE_KINDS: tuple[SpecialType, ...] = (SpecialType.PERSON, SpecialType.PERSON_GROUP)


def is_person_selector(field: Any) -> bool:
    """
    Tells whether a field definition is a person selector

    Args:
        field (Any): A field definition - anything else is no person selector

    Returns:
        bool: True for a dict declaring ``type: person``
    """
    return isinstance(field, dict) and field.get(FieldKey.TYPE.value) == FieldType.PERSON.value


def selectable_kinds(field: dict[str, Any]) -> list[str]:
    """
    The markers a stored person selector may select, in the order it lists them

    Args:
        field (dict[str, Any]): A person selector definition

    Returns:
        list[str]: The selectable markers; empty when the setting is missing or not a list
    """
    raw: Any = field.get(FieldKey.SELECTABLE.value)

    return [kind for kind in raw if isinstance(kind, str)] if isinstance(raw, list) else []


def is_multiple(field: dict[str, Any]) -> bool:
    """
    Whether a stored person selector holds a list of ids rather than one id

    Args:
        field (dict[str, Any]): A person selector definition

    Returns:
        bool: True only for ``multiple: true``
    """
    return field.get(FieldKey.MULTIPLE.value) is True


def person_selector_problems(field: dict[str, Any]) -> list[str]:
    """
    Reports what is wrong with one person selector definition

    Args:
        field (dict[str, Any]): A field definition of kind ``person``

    Returns:
        list[str]: One message per broken setting, naming the field; empty when the definition is sound
    """
    name: Any = field.get(FieldKey.NAME.value)
    problems: list[str] = []
    selectable: Any = field.get(FieldKey.SELECTABLE.value)
    allowed: list[str] = [kind.value for kind in SELECTABLE_KINDS]

    if not (isinstance(selectable, list) and selectable and len(set(map(str, selectable))) == len(selectable)
            and all(kind in allowed for kind in selectable)):
        problems.append(PersonSelectorError.SELECTABLE.format(name=name, allowed=allowed))

    if not isinstance(field.get(FieldKey.MULTIPLE.value), bool):
        problems.append(PersonSelectorError.MULTIPLE.format(name=name))

    if field.get(FieldKey.VALUE.value) not in (None, '', []):
        problems.append(PersonSelectorError.DEFAULT.format(name=name))

    return problems


def person_value_shapes(fields: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """
    Splits a type's person selectors by the shape their stored value has

    Args:
        fields (list[dict[str, Any]]): The type's field definitions

    Returns:
        tuple[list[str], list[str]]: The names holding one id (or None), and the names holding a list of ids
    """
    selectors: list[dict[str, Any]] = [field for field in fields if is_person_selector(field)]

    return (
        [field[FieldKey.NAME.value] for field in selectors if not is_multiple(field)],
        [field[FieldKey.NAME.value] for field in selectors if is_multiple(field)],
    )


def person_value_shape_changed(old_fields: list[dict[str, Any]], new_fields: list[dict[str, Any]]) -> bool:
    """
    Whether an update changes the stored shape of a person selector's value

    True for a person selector the stored type did not declare as one (added, or another kind before), and for one
    switching between one object and several

    Args:
        old_fields (list[dict[str, Any]]): The stored field definitions
        new_fields (list[dict[str, Any]]): The field definitions the update writes

    Returns:
        bool: True when a selector's values must be reshaped
    """
    stored: dict[Any, dict[str, Any]] = {
        field.get(FieldKey.NAME.value): field for field in old_fields if is_person_selector(field)
    }

    return any(
        field.get(FieldKey.NAME.value) not in stored or is_multiple(stored[field.get(FieldKey.NAME.value)]) !=
        is_multiple(field)
        for field in new_fields if is_person_selector(field)
    )
