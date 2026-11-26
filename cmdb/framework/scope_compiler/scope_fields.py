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
What a scope condition's field is, read from the scope role's Types (phase 9 step 3, ruled R10)

A role names several Types, or every Type. A field name is resolved across the Types carrying it - its carriers: none
is refused, carriers disagreeing on the field's kind are refused (one kind casts a value once), and the objects of a
Type without the field never match the condition. A person selector holding several persons is its own kind
(``MULTIPLE_PERSON_KIND``); a field in a multi-data section is marked, the condition is refused for it (R7); the
options of a select / radio field, and the kinds a person selector selects, are the union over the carriers
"""
from dataclasses import dataclass
from typing import Any, Iterable

from cmdb.models.type_model import FieldKey, FieldType, SectionKey, SectionType, TypeSchemaKey
from cmdb.models.type_model.person_selector_rules import selectable_kinds
from cmdb.framework.scope_compiler.scope_compiler_constants import MULTIPLE_PERSON_KIND, ScopeMessage
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ScopeField',
    'field_views',
    'field_views_of_document',
    'resolve_scope_fields',
]


@dataclass(frozen=True)
class ScopeField:
    """
    A field as a scope condition sees it

    Attributes:
        kind (str): The field's kind - a ``FieldType`` value, or ``MULTIPLE_PERSON_KIND``
        options (frozenset[str]): The option names of a select / radio field, else empty
        in_mds (bool): Whether the field sits in a multi-data section
        selectable (frozenset[str]): The special types a person selector selects (PERSON / PERSON_GROUP), else empty -
            what a user token may stand for on it
    """
    kind: str
    options: frozenset[str] = frozenset()
    in_mds: bool = False
    selectable: frozenset[str] = frozenset()


def field_views(fields: Iterable[Any], mds_field_names: Iterable[str]) -> dict[str, ScopeField]:
    """
    Each field of one Type as a scope condition sees it

    Args:
        fields (Iterable[Any]): The Type's field definitions
        mds_field_names (Iterable[str]): The names of its fields in multi-data sections

    Returns:
        dict[str, ScopeField]: By field name; an entry without a text name or kind is left out
    """
    in_mds: set[str] = set(mds_field_names)
    views: dict[str, ScopeField] = {}

    for field in fields:
        if not isinstance(field, dict):
            continue

        name: Any = field.get(FieldKey.NAME.value)
        kind: Any = field.get(FieldKey.TYPE.value)

        if not isinstance(name, str) or not isinstance(kind, str):
            continue

        if kind == FieldType.PERSON.value and field.get(FieldKey.MULTIPLE.value) is True:
            kind = MULTIPLE_PERSON_KIND

        views[name] = ScopeField(kind, _option_names(field), name in in_mds, _selectable(field))

    return views


def field_views_of_document(type_document: dict[str, Any]) -> dict[str, ScopeField]:
    """
    Each field of a stored Type document as a scope condition sees it

    Args:
        type_document (dict[str, Any]): A CmdbType document (``fields`` and ``render_meta`` read)

    Returns:
        dict[str, ScopeField]: By field name
    """
    sections: Any = (type_document.get(TypeSchemaKey.RENDER_META.value) or {}).get(TypeSchemaKey.SECTIONS.value) or []
    mds_names: list[str] = [name for section in sections if isinstance(section, dict)
                            and section.get(SectionKey.TYPE.value) == SectionType.MDS_SECTION.value
                            for name in section.get(SectionKey.FIELDS.value) or [] if isinstance(name, str)]

    return field_views(type_document.get(TypeSchemaKey.FIELDS.value) or [], mds_names)


def resolve_scope_fields(names: Iterable[str], types: Iterable[dict[str, ScopeField]]
                         ) -> tuple[dict[str, ScopeField], list[str]]:
    """
    Resolves each field name across the scope role's Types

    Args:
        names (Iterable[str]): The field names the scope compares
        types (Iterable[dict[str, ScopeField]]): Each of the role's Types as ``field_views``

    Returns:
        tuple[dict[str, ScopeField], list[str]]: The resolved fields (a refused name left out), and the problems - no
            carrier, or carriers disagreeing on the kind
    """
    type_views: list[dict[str, ScopeField]] = list(types)
    resolved: dict[str, ScopeField] = {}
    problems: list[str] = []

    for name in dict.fromkeys(names):
        carriers: list[ScopeField] = [views[name] for views in type_views if name in views]
        kinds: list[str] = sorted({carrier.kind for carrier in carriers})

        if not carriers:
            problems.append(ScopeMessage.NO_CARRIER.value.format(field=name))
        elif len(kinds) > 1:
            problems.append(ScopeMessage.KINDS_DISAGREE.value.format(field=name, kinds=kinds))
        else:
            resolved[name] = ScopeField(kinds[0], frozenset().union(*(carrier.options for carrier in carriers)),
                                        any(carrier.in_mds for carrier in carriers),
                                        frozenset().union(*(carrier.selectable for carrier in carriers)))

    return resolved, problems


def _selectable(field: dict[str, Any]) -> frozenset[str]:
    """
    The special types a person selector selects

    Args:
        field (dict[str, Any]): The field definition

    Returns:
        frozenset[str]: Its selectable markers; empty for another kind
    """
    if field.get(FieldKey.TYPE.value) != FieldType.PERSON.value:
        return frozenset()

    return frozenset(selectable_kinds(field))


def _option_names(field: dict[str, Any]) -> frozenset[str]:
    """
    The option names of a select / radio field

    Args:
        field (dict[str, Any]): The field definition

    Returns:
        frozenset[str]: The names; empty for another kind or no options
    """
    if field.get(FieldKey.TYPE.value) not in (FieldType.SELECT.value, FieldType.RADIO.value):
        return frozenset()

    return frozenset(option.get(FieldKey.NAME.value) for option in field.get(FieldKey.OPTIONS.value) or []
                     if isinstance(option, dict) and isinstance(option.get(FieldKey.NAME.value), str))
