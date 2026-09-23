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
The internal-consistency rules of a CmdbType payload

A CmdbType declares every field once, in its flat ``fields`` list; its sections and its summary line
carry only the NAMES of the fields they show. That pairing is what makes a Type renderable, and
nothing below the route re-checks it - the insert stores the payload as given and the update writes
the whole document. The rules live here rather than in ``types_helper`` because they are one
self-contained theme and that module is already at pylint's 1,500-line cap
"""
from typing import Any

from flask import abort

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    DUPLICATE_FIELD_IDENTIFIER_MESSAGE,
    DUPLICATE_SECTION_IDENTIFIER_MESSAGE,
    SECTION_FIELD_UNKNOWN_MESSAGE,
    SUMMARY_DUPLICATE_FIELD_MESSAGE,
    SUMMARY_FIELD_UNKNOWN_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

def duplicated(names: list[str]) -> list[str]:
    """
    Reports the names that occur more than once, in first-seen order

    Args:
        names (list[str]): The identifiers to inspect

    Returns:
        list[str]: Each repeated identifier once, empty when all are unique
    """
    seen: set[str] = set()
    repeated: dict[str, None] = {}

    for name in names:
        if name in seen:
            repeated[name] = None
        seen.add(name)

    return list(repeated)


def type_structure_blocker(data: dict[str, Any]) -> str | None:
    """
    Reports why a CmdbType payload is not internally consistent, if it is not

    A Type declares every field once in its flat ``fields`` list; its sections and its summary line
    carry only the NAMES of the fields they show. Nothing downstream re-checks that pairing, so a
    payload whose sections reference names the ``fields`` list does not declare is stored as sent and
    produces a Type that holds fields but renders none of them - while those names stay taken, so
    adding a field under the intended name is refused as a duplicate. Duplicate field or section
    identifiers break the same pairing from the other side, and a summary line naming a field the
    Type does not declare silently loses that entry from every place an Object is identified by its
    summary rather than opened.

    Five refusals, reported one at a time in the order a caller can act on them: duplicate field
    identifiers, duplicate section identifiers, the first section referencing an unknown field, then
    the summary line's unknown fields and its repeated ones.

    What is deliberately NOT checked here: a field that no section shows (a Type under construction
    legitimately has them, and they render nowhere without breaking anything), the referenced type's
    fields inside a ref-section's ``reference.selected_fields`` (they belong to the OTHER Type), and
    ``render_meta.externals`` (an external link accepts the ``object_id`` pseudo-field, which is not a
    declared field at all)

    Args:
        data (dict[str, Any]): The Type payload an insert or an update would persist

    Returns:
        str | None: The reason the payload is refused, or None when it is consistent
    """
    fields: list[dict[str, Any]] = data.get(TypeSchemaKey.FIELDS.value) or []
    sections: list[dict[str, Any]] = (data.get(TypeSchemaKey.RENDER_META.value) or {}).get(
        TypeSchemaKey.SECTIONS.value
    ) or []

    declared: list[str] = [field.get(FieldKey.NAME) for field in fields if isinstance(field, dict)]

    repeated_fields: list[str] = duplicated([name for name in declared if name])

    if repeated_fields:
        return DUPLICATE_FIELD_IDENTIFIER_MESSAGE.format(duplicates=', '.join(repeated_fields))

    section_names: list[str] = [
        section.get(SectionKey.NAME) for section in sections if isinstance(section, dict)
    ]
    repeated_sections: list[str] = duplicated([name for name in section_names if name])

    if repeated_sections:
        return DUPLICATE_SECTION_IDENTIFIER_MESSAGE.format(duplicates=', '.join(repeated_sections))

    known: set[str] = {name for name in declared if name}

    for section in sections:
        if not isinstance(section, dict):
            continue

        unknown: list[str] = [
            name for name in (section.get(SectionKey.FIELDS) or []) if name not in known
        ]

        if unknown:
            return SECTION_FIELD_UNKNOWN_MESSAGE.format(
                section_name=section.get(SectionKey.NAME),
                unknown=', '.join(str(name) for name in unknown),
            )

    return summary_blocker(data, known)


def summary_blocker(data: dict[str, Any], known: set[str]) -> str | None:
    """
    Reports why the summary line of a Type payload cannot be rendered as configured, if it cannot

    The summary line is what identifies an Object wherever it is referenced rather than opened, and it
    is composed by looking each configured name up in the Type's fields, in order. Two ways of writing
    that list survive every downstream read and still produce a line nobody asked for:

    * a name the Type does not declare resolves to nothing and is skipped by the renderer, so the
      entry disappears from the line and the Object reads as if it had no value there -
      indistinguishable from real data being absent
    * a name listed twice renders the same value twice, joined by the ' | ' the line puts between two
      DIFFERENT fields, so the duplicate reads as a second field holding the same value

    The unknown names are reported first: a name that is not a field at all cannot be judged as a
    repeat of anything the Type declares

    Args:
        data (dict[str, Any]): The Type payload an insert or an update would persist
        known (set[str]): The names the payload's ``fields`` list declares

    Returns:
        str | None: The reason the payload is refused, or None when the summary names each declared
            field at most once
    """
    summary: Any = (data.get(TypeSchemaKey.RENDER_META.value) or {}).get(TypeSchemaKey.SUMMARY.value)

    if not isinstance(summary, dict):
        return None

    names: list[Any] = summary.get(TypeSchemaKey.FIELDS.value) or []

    unknown: list[str] = [name for name in names if name not in known]

    if unknown:
        return SUMMARY_FIELD_UNKNOWN_MESSAGE.format(unknown=', '.join(str(name) for name in unknown))

    repeated: list[str] = duplicated([name for name in names if name])

    if repeated:
        return SUMMARY_DUPLICATE_FIELD_MESSAGE.format(duplicates=', '.join(repeated))

    return None


def guard_type_structure(data: dict[str, Any]) -> None:
    """
    Aborts 400 when a CmdbType payload would store a Type that cannot render itself

    The route-level wrapper around `type_structure_blocker`, applied on create AND on update: both
    write the whole document, so both can introduce the inconsistency

    Args:
        data (dict[str, Any]): The Type payload an insert or an update would persist

    Raises:
        HTTPException: 400 when the payload is not internally consistent
    """
    blocker: str | None = type_structure_blocker(data)

    if blocker:
        abort(400, blocker)
