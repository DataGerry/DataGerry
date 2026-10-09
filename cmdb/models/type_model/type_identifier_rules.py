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
What a NEW field or section identifier of a CmdbType may be

A field's ``name`` and a section's ``name`` are the identifiers everything else refers to them by: a CmdbObject keys
its stored values by the field name, a multi-data section's rows sit under the section name, the name-keyed read
format (``?view=values``) uses both as JSON keys, and the object import template writes the field name into a column
header. Three shapes break one of those, so a new identifier is refused when it is:

  - **blank** (empty or whitespace only) - nothing can address it
  - **padded** (leading or trailing whitespace) - ``"cpu"`` and ``"cpu "`` read as one name and are two
  - **bracketed** (``[`` or ``]``) - the import template cannot read it back (``IDENTIFIER_FORBIDDEN_CHARACTERS``)

**Everything else is allowed**, dots and non-ASCII letters included: the type builder derives a name from its
label (lowercase, spaces to hyphens), so ``ip.address`` and ``größe`` are ordinary names, and a JSON key may be any
string. A consumer of ``?view=values`` must therefore not split a key on dots.

**Only NEW identifiers are judged.** An identifier is immutable - renaming one would orphan every stored value - so a
name already on the stored type is never refused here, whatever it looks like; the rule binds the names a write adds.
One rule for the type routes and the type import
"""
from collections.abc import Collection, Iterable
from typing import Any, TYPE_CHECKING

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_constants import (
    IDENTIFIER_FORBIDDEN_CHARACTERS,
    IdentifierKind,
    TypeIdentifierError,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

if TYPE_CHECKING:
    # For the annotation only: cmdb_type imports the type_model package this module belongs to
    from cmdb.models.type_model.cmdb_type import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'identifier_error',
    'identifier_problem',
    'payload_identifier_names',
    'stored_identifier_names',
]


def identifier_problem(name: Any) -> TypeIdentifierError | None:
    """
    Judges one identifier by the rule

    Args:
        name (Any): The identifier; a value that is no string is left to the schema / structure rules

    Returns:
        TypeIdentifierError | None: Why the identifier is refused, or None when it is usable
    """
    if not isinstance(name, str):
        return None

    if not name.strip():
        return TypeIdentifierError.BLANK

    if name != name.strip():
        return TypeIdentifierError.SURROUNDING_WHITESPACE

    if any(character in name for character in IDENTIFIER_FORBIDDEN_CHARACTERS):
        return TypeIdentifierError.FORBIDDEN_CHARACTER

    return None


def _first_new_identifier_error(names: Iterable[Any], stored: Collection[Any], kind: IdentifierKind) -> str | None:
    """
    The message about the first new identifier the rule refuses

    Args:
        names (Iterable[Any]): The identifiers the write would store
        stored (Collection[Any]): The identifiers the stored type already holds - never judged
        kind (IdentifierKind): Field or section, for the message

    Returns:
        str | None: The message, or None when every new identifier is usable
    """
    for name in names:
        if name in stored:
            continue

        problem: TypeIdentifierError | None = identifier_problem(name)

        if problem is not None:
            return problem.format(kind=kind.value, name=name)

    return None


def identifier_error(
        field_names: Iterable[Any],
        section_names: Iterable[Any],
        stored_field_names: Collection[Any] = (),
        stored_section_names: Collection[Any] = ()) -> str | None:
    """
    Reports why a write may not store its new field or section identifiers, if it may not

    The first refused identifier is reported - fields before sections, in the order the write lists them

    Args:
        field_names (Iterable[Any]): The field identifiers the write would store
        section_names (Iterable[Any]): The section identifiers the write would store
        stored_field_names (Collection[Any]): The stored type's field identifiers; empty for a create
        stored_section_names (Collection[Any]): The stored type's section identifiers; empty for a create

    Returns:
        str | None: The reason the write is refused, or None when every new identifier is usable
    """
    return (
        _first_new_identifier_error(field_names, stored_field_names, IdentifierKind.FIELD)
        or _first_new_identifier_error(section_names, stored_section_names, IdentifierKind.SECTION)
    )


def payload_identifier_names(data: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """
    The field and section identifiers a CmdbType payload (or stored document) carries

    Args:
        data (dict[str, Any]): A CmdbType payload or document

    Returns:
        tuple[list[Any], list[Any]]: (field identifiers, section identifiers), in payload order
    """
    fields: list[Any] = data.get(TypeSchemaKey.FIELDS.value) or []
    sections: list[Any] = (data.get(TypeSchemaKey.RENDER_META.value) or {}).get(TypeSchemaKey.SECTIONS.value) or []

    return (
        [field.get(FieldKey.NAME.value) for field in fields if isinstance(field, dict)],
        [section.get(SectionKey.NAME.value) for section in sections if isinstance(section, dict)],
    )


def stored_identifier_names(cmdb_type: 'CmdbType') -> tuple[set[Any], set[Any]]:
    """
    The field and section identifiers a CmdbType already holds - the ones the rule never judges

    Args:
        cmdb_type (CmdbType): The stored CmdbType

    Returns:
        tuple[set[Any], set[Any]]: (field identifiers, section identifiers)
    """
    return (
        {field.get(FieldKey.NAME.value) for field in cmdb_type.get_fields() if isinstance(field, dict)},
        {section.name for section in cmdb_type.get_sections()},
    )
