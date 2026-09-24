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
What a CmdbType edit has to change in the multi-data-section rows of its CmdbObjects

A multi-data section is the one part of a type whose data lives per ROW: the type declares which
fields the section has, and every object stores a `values` list of rows, each row holding one
``{name, value, type}`` entry per declared field (`CmdbObjectMdsKey` / `CmdbObjectMdsRowKey`). So a
field added to an MDS section has to be appended to every row of every object of that type, a removed
field stripped from them, and a removed **section** dropped from the objects entirely - which is the
only way an object stops carrying a section its type no longer declares.

Two contracts hold this together:

* an object's MDS ``section_id`` equals the type section's ``name``. That is what lets a plan be
  keyed by name and a statement be addressed by section_id
* a new entry is built from the **updated** type's field definition - its declared ``type`` and its
  default ``value`` - because the old type by definition does not contain a newly added field

Everything here is pure. `plan_mds_changes` answers what has to change from the two type states, and
`build_mds_updates` turns the plan into the server-side statements that perform it
(`objects_propagation_helper`), which `ObjectsManager.apply_raw_updates` runs. No object is read: the
statements add an entry only to rows lacking it and pull only what is named, so they neither overwrite
a concurrent edit of an object nor change anything on a re-run.
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.objects_propagation_helper import (
    RawUpdate,
    build_add_mds_field_update,
    build_field_entry,
    build_remove_mds_fields_update,
    build_remove_mds_section_update,
)
from cmdb.models.type_model import (
    CmdbType,
    FieldKey,
    SectionKey,
    SectionType,
    TypeSchemaKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MdsChangePlan',
    'build_field_definition_map',
    'build_mds_updates',
    'build_new_field_entry',
    'diff_field_names',
    'plan_mds_changes',
]

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class MdsChangePlan:
    """
    What one CmdbType edit changes in its objects' multi-data sections

    Keyed by the type section's ``name``, which is the objects' ``section_id``. `field_definitions`
    comes from the UPDATED type, so a newly added field is written with the type it was declared with
    and starts from its declared default value
    """
    added_fields: dict[str, list[str]] = field(default_factory=dict)
    deleted_fields: dict[str, list[str]] = field(default_factory=dict)
    removed_sections: list[str] = field(default_factory=list)
    field_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)


    @property
    def is_empty(self) -> bool:
        """
        Reports whether the plan asks for nothing at all

        Returns:
            bool: True when no object of the type can be affected
        """
        return not (self.added_fields or self.deleted_fields or self.removed_sections)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the plan                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def diff_field_names(initial_fields: list[str], updated_fields: list[str]) -> tuple[list[str], list[str]]:
    """
    Compares two field-name lists and reports what was added and what was removed

    Both results are sorted: they end up as the order of the entries appended to every row, and an
    arbitrary set order would make the same edit produce a different document each time it ran

    Args:
        initial_fields (list[str]): The section's field names before the edit
        updated_fields (list[str]): The section's field names after the edit

    Returns:
        tuple[list[str], list[str]]: The added and the removed field names
    """
    initial: set[str] = set(initial_fields)
    updated: set[str] = set(updated_fields)

    return sorted(updated - initial), sorted(initial - updated)


def build_field_definition_map(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Maps each declared field name to its field definition

    Built from the type the edit produced, because the entries being written describe its fields.
    An entry without a name is skipped rather than guessed at

    Args:
        fields (list[dict[str, Any]]): The ``fields`` list of a CmdbType document

    Returns:
        dict[str, dict[str, Any]]: field name -> field definition
    """
    field_definitions: dict[str, dict[str, Any]] = {}

    for type_field in fields:
        field_name: Any = type_field.get(FieldKey.NAME.value) if isinstance(type_field, dict) else None

        if not isinstance(field_name, str):
            LOGGER.warning("[build_field_definition_map] Skipping a type field without a name: %r", type_field)
            continue

        field_definitions[field_name] = type_field

    return field_definitions

def plan_mds_changes(old_type: CmdbType, updated_type: dict[str, Any]) -> MdsChangePlan:
    """
    Works out what a CmdbType edit changes in the multi-data sections of its objects

    Compares each MDS section of the stored type with the same section of the edit - matched on
    ``(type, name)``, because a name alone could collide with a normal section - and records the added
    and removed field names. A section the edit no longer declares is recorded as removed, which is
    what makes the objects drop it: keeping it would leave every object carrying rows of a section its
    type does not have, invisible to every read and impossible to edit

    A payload that does not describe the sections at all (no ``render_meta.sections``) is reported and
    treated as "no MDS change" - it must not be read as "every section was removed", which would drop
    the rows of every object of the type. A payload that DOES carry the section list is authoritative,
    because a type update always sends the whole document

    Args:
        old_type (CmdbType): The CmdbType as stored before the edit
        updated_type (dict[str, Any]): The CmdbType document the edit produced

    Returns:
        MdsChangePlan: What has to change in the objects, empty when nothing does
    """
    render_meta: Any = updated_type.get(TypeSchemaKey.RENDER_META.value)

    if not isinstance(render_meta, dict) or TypeSchemaKey.SECTIONS.value not in render_meta:
        # A payload that does not describe the type's sections at all says nothing about them. It must
        # NOT be read as "every section was removed" - that would drop the MDS rows of every object of
        # the type. A type update always carries the whole document (there is no partial update), so
        # this is a malformed payload, and the type write itself has already been schema-validated
        LOGGER.warning(
            "[plan_mds_changes] The updated CmdbType carries no '%s.%s' - no MDS change is propagated",
            TypeSchemaKey.RENDER_META.value, TypeSchemaKey.SECTIONS.value,
        )

        return MdsChangePlan()

    updated_sections: Any = render_meta.get(TypeSchemaKey.SECTIONS.value) or []

    sections_by_identity: dict[tuple[Any, Any], dict[str, Any]] = {
        (section.get(SectionKey.TYPE.value), section.get(SectionKey.NAME.value)): section
        for section in updated_sections
        if isinstance(section, dict)
    }

    added_fields: dict[str, list[str]] = {}
    deleted_fields: dict[str, list[str]] = {}
    removed_sections: list[str] = []

    for old_section in old_type.render_meta.sections:
        if old_section.type != SectionType.MDS_SECTION:
            continue

        updated_section: dict[str, Any] | None = sections_by_identity.get(
            (old_section.type, old_section.name)
        )

        if updated_section is None:
            removed_sections.append(old_section.name)
            continue

        added, deleted = diff_field_names(
            old_section.fields, updated_section.get(SectionKey.FIELDS.value) or [],
        )

        if added:
            added_fields[old_section.name] = added

        if deleted:
            deleted_fields[old_section.name] = deleted

    return MdsChangePlan(
        added_fields=added_fields,
        deleted_fields=deleted_fields,
        removed_sections=removed_sections,
        field_definitions=build_field_definition_map(updated_type.get(TypeSchemaKey.FIELDS.value) or []),
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                           the statements that perform it                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def build_new_field_entry(plan: MdsChangePlan, field_name: str) -> dict[str, Any]:
    """
    Builds the entry a newly added MDS field gets in every existing row

    The updated type's definition decides the entry's type and its value - the field's declared
    default, or None when it declares none. A name the type does not declare as a field is written as
    an empty ``text`` entry rather than dropped, so every row still ends up with one entry per name
    the section lists

    Args:
        plan (MdsChangePlan): The plan the field belongs to
        field_name (str): The name of the added field

    Returns:
        dict[str, Any]: The ``{name, value, type}`` entry
    """
    return build_field_entry(plan.field_definitions.get(field_name, {FieldKey.NAME.value: field_name}))


def build_mds_updates(type_id: int, plan: MdsChangePlan) -> list[RawUpdate]:
    """
    Turns a change plan into the server-side statements that apply it to every object of the type

    Per section: one ``$push`` per added field (only into rows lacking it), one ``$pull`` for the
    removed fields, and one ``$pull`` of the whole section when the type no longer declares it. The
    order is deterministic - sections and field names sorted - so the same edit always issues the same
    statements

    Args:
        type_id (int): public_id of the CmdbType whose objects are updated
        plan (MdsChangePlan): What the type edit changes

    Returns:
        list[RawUpdate]: The statements, empty for an empty plan
    """
    updates: list[RawUpdate] = []

    for section_id in sorted(plan.added_fields):
        updates.extend(
            build_add_mds_field_update(type_id, section_id, build_new_field_entry(plan, field_name))
            for field_name in plan.added_fields[section_id]
        )

    for section_id in sorted(plan.deleted_fields):
        updates.append(build_remove_mds_fields_update(type_id, section_id, plan.deleted_fields[section_id]))

    for section_id in sorted(plan.removed_sections):
        updates.append(build_remove_mds_section_update(type_id, section_id))

    return updates
