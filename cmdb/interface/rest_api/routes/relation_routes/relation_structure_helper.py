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
The internal-consistency rules of a CmdbRelation payload

A CmdbRelation declares every field once, in its flat ``fields`` list; its sections carry only the
NAMES of the fields they show. That is the same pairing a CmdbType has, and it breaks the same way -
except that a relation's sections have a second consumer: the update diff
(``relations_helper.get_added_and_removed_fields``) reads the field names out of the sections and
writes what it finds onto **every dependent CmdbObjectRelation**. A section naming a field the
relation does not declare therefore does not merely render nothing; it is propagated.

``CmdbRelation.SCHEMA`` owns the SHAPE of both halves - a section's ``fields`` is a list of non-blank
strings, a field's ``type`` is a known ``FieldType``. What a Cerberus schema cannot express is a rule
that spans two keys, which is what this module holds: that a referenced name is declared, and that no
identifier is used twice.

The rules live here rather than in ``relations_helper`` because they are one self-contained theme;
that module owns the diff, the type-id validation and the update orchestration.
"""
from typing import Any

from flask import abort

from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey

from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    RELATION_DUPLICATE_FIELD_IDENTIFIER_MESSAGE,
    RELATION_DUPLICATE_SECTION_IDENTIFIER_MESSAGE,
    RELATION_SECTION_FIELD_UNKNOWN_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

def duplicated_names(names: list[str]) -> list[str]:
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


def relation_structure_blocker(data: dict[str, Any]) -> str | None:
    """
    Reports why a CmdbRelation payload is not internally consistent, if it is not

    Three refusals, reported one at a time in the order a caller can act on them: duplicate field
    identifiers, duplicate section identifiers, then the first section referencing an unknown field.
    The identifier rules come first because an ambiguous name makes the pairing unanswerable.

    What is deliberately NOT checked here: a declared field that no section shows. A relation under
    construction legitimately has them, and they render nowhere without breaking anything - the same
    exemption the CmdbType structure guard makes

    Args:
        data (dict[str, Any]): The CmdbRelation payload an insert or an update would persist

    Returns:
        str | None: The reason the payload is refused, or None when it is consistent
    """
    fields: list[dict[str, Any]] = data.get(RelationKey.FIELDS.value) or []
    sections: list[dict[str, Any]] = data.get(RelationKey.SECTIONS.value) or []

    declared: list[str] = [
        field.get(FieldKey.NAME.value) for field in fields if isinstance(field, dict)
    ]

    repeated_fields: list[str] = duplicated_names([name for name in declared if name])

    if repeated_fields:
        return RELATION_DUPLICATE_FIELD_IDENTIFIER_MESSAGE.format(
            duplicates=', '.join(repeated_fields),
        )

    section_names: list[str] = [
        section.get(SectionKey.NAME.value) for section in sections if isinstance(section, dict)
    ]
    repeated_sections: list[str] = duplicated_names([name for name in section_names if name])

    if repeated_sections:
        return RELATION_DUPLICATE_SECTION_IDENTIFIER_MESSAGE.format(
            duplicates=', '.join(repeated_sections),
        )

    known: set[str] = {name for name in declared if name}

    for section in sections:
        if not isinstance(section, dict):
            continue

        unknown: list[str] = [
            name for name in (section.get(SectionKey.FIELDS.value) or []) if name not in known
        ]

        if unknown:
            return RELATION_SECTION_FIELD_UNKNOWN_MESSAGE.format(
                section_name=section.get(SectionKey.NAME.value),
                unknown=', '.join(str(name) for name in unknown),
            )

    return None


def guard_relation_structure(data: dict[str, Any]) -> None:
    """
    Aborts 400 when a CmdbRelation payload would store a relation that cannot render itself

    The route-level wrapper around `relation_structure_blocker`, applied on create AND on update:
    both write the whole document, so both can introduce the inconsistency

    Args:
        data (dict[str, Any]): The CmdbRelation payload an insert or an update would persist

    Raises:
        HTTPException: 400 when the payload is not internally consistent
    """
    blocker: str | None = relation_structure_blocker(data)

    if blocker:
        abort(400, blocker)
