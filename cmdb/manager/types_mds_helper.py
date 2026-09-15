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
  keyed by name and looked up by section_id
* an entry's ``type`` comes from the **updated** type's field list. Reading it from the old type
  (which by definition does not contain a newly added field) is what silently wrote every new MDS
  field as ``text``, whatever it was declared as

Everything here is pure: `plan_mds_changes` answers what has to change from the two type states, and
`apply_plan` performs it on one object in memory and reports whether that object actually changed. The
manager owns the reads and the batching, the caller owns the writes - which is why an object is only
reported as changed when a value really moved, so an idempotent re-run writes nothing
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import (
    CmdbType,
    FieldKey,
    FieldType,
    SectionKey,
    SectionType,
    TypeSchemaKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MdsChangePlan',
    'apply_plan',
    'build_field_type_map',
    'diff_field_names',
    'plan_mds_changes',
]

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class MdsChangePlan:
    """
    What one CmdbType edit changes in its objects' multi-data sections

    Keyed by the type section's ``name``, which is the objects' ``section_id``. `field_type_map` comes
    from the UPDATED type, so a newly added field is written with the type it was declared with
    """
    added_fields: dict[str, list[str]] = field(default_factory=dict)
    deleted_fields: dict[str, list[str]] = field(default_factory=dict)
    removed_sections: list[str] = field(default_factory=list)
    field_type_map: dict[str, str] = field(default_factory=dict)


    @property
    def is_empty(self) -> bool:
        """
        Reports whether the plan asks for nothing at all

        Returns:
            bool: True when no object of the type can be affected
        """
        return not (self.added_fields or self.deleted_fields or self.removed_sections)


    @property
    def affected_section_ids(self) -> list[str]:
        """
        The MDS section_ids an object must carry at least one of to be affected

        Lets the caller skip every object that carries none of them - such an object can not change

        Returns:
            list[str]: The affected section_ids, sorted so the query is reproducible
        """
        return sorted(set(self.added_fields) | set(self.deleted_fields) | set(self.removed_sections))

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


def build_field_type_map(fields: list[dict[str, Any]]) -> dict[str, str]:
    """
    Maps each declared field name to its declared field type

    Built from the type the edit produced, because the entries being written describe its fields.
    An entry without a name is skipped rather than guessed at

    Args:
        fields (list[dict[str, Any]]): The ``fields`` list of a CmdbType document

    Returns:
        dict[str, str]: field name -> field type
    """
    field_type_map: dict[str, str] = {}

    for type_field in fields:
        field_name: Any = type_field.get(FieldKey.NAME.value)

        if not isinstance(field_name, str):
            LOGGER.warning("[build_field_type_map] Skipping a type field without a name: %r", type_field)
            continue

        field_type_map[field_name] = type_field.get(FieldKey.TYPE.value, FieldType.TEXT.value)

    return field_type_map


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
        field_type_map=build_field_type_map(updated_type.get(TypeSchemaKey.FIELDS.value) or []),
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                             applying it to one object                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def mds_rows(mds_section: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The captured rows of one MDS section

    Args:
        mds_section (dict[str, Any]): An object's multi_data_sections entry

    Returns:
        list[dict[str, Any]]: The section's rows, empty when it has none
    """
    return mds_section.get(CmdbObjectMdsKey.VALUES.value) or []


def row_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The ``{name, value, type}`` entries of one MDS row

    Args:
        row (dict[str, Any]): One row of an MDS section

    Returns:
        list[dict[str, Any]]: The row's field entries, empty when it has none
    """
    return row.get(CmdbObjectMdsRowKey.DATA.value) or []


def add_field_entries(
        mds_section: dict[str, Any],
        field_names: list[str],
        field_type_map: dict[str, str]) -> bool:
    """
    Appends an entry per newly declared field to every row of an MDS section, in place

    A new field is appended with a ``None`` value, so a row keeps exactly one entry per declared
    field. An entry already present is left alone, which is what makes a re-run write nothing

    Args:
        mds_section (dict[str, Any]): The MDS section to extend
        field_names (list[str]): The names of the fields to add
        field_type_map (dict[str, str]): field name -> declared type, from the updated CmdbType

    Returns:
        bool: True when at least one entry was appended
    """
    changed: bool = False

    for row in mds_rows(mds_section):
        row.setdefault(CmdbObjectMdsRowKey.DATA.value, [])
        present: set[Any] = {entry.get(CmdbObjectFieldKey.NAME.value) for entry in row_entries(row)}

        for field_name in field_names:
            if field_name in present:
                continue

            row[CmdbObjectMdsRowKey.DATA.value].append({
                CmdbObjectFieldKey.NAME.value: field_name,
                CmdbObjectFieldKey.VALUE.value: None,
                CmdbObjectFieldKey.TYPE.value: field_type_map.get(field_name, FieldType.TEXT.value),
            })
            changed = True

    return changed


def remove_field_entries(mds_section: dict[str, Any], field_names: list[str]) -> bool:
    """
    Drops the entries of the named fields from every row of an MDS section, in place

    Args:
        mds_section (dict[str, Any]): The MDS section to strip
        field_names (list[str]): The names of the fields the type no longer declares

    Returns:
        bool: True when at least one entry was dropped
    """
    dropped: set[str] = set(field_names)
    changed: bool = False

    for row in mds_rows(mds_section):
        if CmdbObjectMdsRowKey.DATA.value not in row:
            continue

        kept: list[dict[str, Any]] = [
            entry for entry in row_entries(row)
            if entry.get(CmdbObjectFieldKey.NAME.value) not in dropped
        ]

        if len(kept) != len(row_entries(row)):
            row[CmdbObjectMdsRowKey.DATA.value] = kept
            changed = True

    return changed


def apply_plan(plan: MdsChangePlan, cmdb_object: CmdbObject) -> bool:
    """
    Applies a change plan to one CmdbObject in memory

    Three things can happen per section: entries are appended for newly declared fields, entries of
    fields the type dropped are removed, and a section the type no longer declares is removed from the
    object altogether. The object is reported as changed only when a value really moved, so the caller
    writes exactly the objects that need writing

    Args:
        plan (MdsChangePlan): What the type edit changes
        cmdb_object (CmdbObject): The object to update in place

    Returns:
        bool: True when the object's multi_data_sections changed
    """
    removed: set[str] = set(plan.removed_sections)
    kept_sections: list[dict[str, Any]] = []
    changed: bool = False

    for mds_section in cmdb_object.multi_data_sections:
        section_id: Any = mds_section.get(CmdbObjectMdsKey.SECTION_ID.value)

        if section_id in removed:
            changed = True
            continue

        if add_field_entries(mds_section, plan.added_fields.get(section_id, []), plan.field_type_map):
            changed = True

        if remove_field_entries(mds_section, plan.deleted_fields.get(section_id, [])):
            changed = True

        kept_sections.append(mds_section)

    if changed:
        cmdb_object.multi_data_sections = kept_sections

    return changed
