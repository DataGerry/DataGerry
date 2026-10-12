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
The field / section structure every CmdbType must have - one rule set for the type write routes and the type import

A Type declares its fields once in a flat ``fields`` list; its sections, its summary line and its external links only
name them. These rules hold that pairing and the shape of each field and section (``validate_type_structure``); the
type create and update routes and both type-import verbs ask the same list, so a document is legal through one exactly
when it is legal through the other. Every rule returns a message rather than raising, so all findings of one document
are reported together
"""
from typing import Any, Callable, NamedTuple

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import (
    DG_LOCATION_FIELD_NAME,
    EXTERNAL_LINK_OBJECT_ID,
    LEGACY_EXTERNALS_KEY,
    STRUCTURE_ERROR_SEPARATOR,
    TypeStructureError,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.utils import duplicate_names, is_non_blank_string
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['STRUCTURE_RULES', 'TypeStructure', 'read_type_structure', 'validate_type_structure']

class TypeStructure(NamedTuple):
    """
    The parts of an uploaded type the structural rules inspect, resolved once

    Malformed entries (a field or section that is not a dictionary) are dropped while reading, so the
    rules never have to guard against them. Fields and sections keep their position in the upload so a
    nameless one can still be pointed at in the report
    """
    fields: list[tuple[int, dict[str, Any]]]
    sections: list[tuple[int, dict[str, Any]]]
    field_names: list[Any]
    known_fields: set[str]
    claimed: list[str]
    render_meta: dict[str, Any]


def read_type_structure(type_entry: dict[str, Any]) -> TypeStructure:
    """
    Reads the field / section structure of an uploaded type into the shape the rules work on

    Args:
        type_entry (dict[str, Any]): A single uploaded type entry

    Returns:
        TypeStructure: The resolved fields, sections and the names derived from them
    """
    fields = [
        (position, field)
        for position, field in enumerate(type_entry.get(TypeSchemaKey.FIELDS.value) or [])
        if isinstance(field, dict)
    ]
    raw_render_meta = type_entry.get(TypeSchemaKey.RENDER_META.value)
    render_meta: dict[str, Any] = raw_render_meta if isinstance(raw_render_meta, dict) else {}
    sections = [
        (position, section)
        for position, section in enumerate(render_meta.get(TypeSchemaKey.SECTIONS.value) or [])
        if isinstance(section, dict)
    ]
    field_names = [field.get(FieldKey.NAME.value) for _, field in fields]

    return TypeStructure(
        fields=fields,
        sections=sections,
        field_names=field_names,
        known_fields={name for name in field_names if isinstance(name, str)},
        claimed=_section_assigned_field_names(sections),
        render_meta=render_meta,
    )


def _section_assigned_field_names(sections: list[tuple[int, dict[str, Any]]]) -> list[str]:
    """
    Collects every field name the sections claim, one entry per claim so duplicates stay visible

    A field is claimed by a section through its `fields` list, or through an MDS section's extra
    `hidden_fields` list. A ref-section's own field is claimed by neither - it is exempted from the
    assignment rule by its field type instead (see `validate_type_structure`)

    Args:
        sections (list[tuple[int, dict[str, Any]]]): The type's sections with their upload position

    Returns:
        list[str]: The claimed field names, including repeats when several sections claim the same one
    """
    claimed: list[str] = []

    for _, section in sections:
        for key in (SectionKey.FIELDS.value, SectionKey.HIDDEN_FIELDS.value):
            claimed.extend(name for name in section.get(key) or [] if isinstance(name, str))

    return claimed


def _referenced_field_names(entries: list[Any]) -> list[Any]:
    """
    Collects the field names a list of `fields` lists refers to, e.g. the summary or external links

    Args:
        entries (list[Any]): The `fields` lists to flatten, each expected to be a list of names

    Returns:
        list[Any]: Every referenced name, duplicates included
    """
    referenced: list[Any] = []

    for entry in entries:
        if isinstance(entry, list):
            referenced.extend(entry)

    return referenced


def _duplicate_field_names_error(structure: TypeStructure) -> str | None:
    """
    Reports field names used more than once - a field name is its immutable identifier

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every field name is unique
    """
    duplicates = duplicate_names(structure.field_names)

    if not duplicates:
        return None

    return TypeStructureError.DUPLICATE_FIELD_NAMES.format(names=sorted(duplicates))


def _missing_field_names_error(structure: TypeStructure) -> str | None:
    """
    Reports fields with no usable name, pointing at their position in the uploaded `fields` list

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every field is named
    """
    positions = [
        position for position, field in structure.fields
        if not is_non_blank_string(field.get(FieldKey.NAME.value))
    ]

    if not positions:
        return None

    return TypeStructureError.MISSING_FIELD_NAMES.format(positions=positions)


def _invalid_field_types_error(structure: TypeStructure) -> str | None:
    """
    Reports fields whose `type` is not a known FieldType, labelled `name (type)`

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every field type is known
    """
    invalid = sorted(
        f'{field.get(FieldKey.NAME.value)} ({field.get(FieldKey.TYPE.value)})'
        for _, field in structure.fields
        if not FieldType.is_valid(field.get(FieldKey.TYPE.value))
    )

    if not invalid:
        return None

    return TypeStructureError.INVALID_FIELD_TYPES.format(
        fields=invalid,
        allowed=', '.join(member.value for member in FieldType),
    )


def _duplicate_section_names_error(structure: TypeStructure) -> str | None:
    """
    Reports section names used more than once

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every section name is unique
    """
    duplicates = duplicate_names(section.get(SectionKey.NAME.value) for _, section in structure.sections)

    if not duplicates:
        return None

    return TypeStructureError.DUPLICATE_SECTION_NAMES.format(names=sorted(duplicates))


def _missing_section_names_error(structure: TypeStructure) -> str | None:
    """
    Reports sections with no usable name, pointing at their position in the uploaded section list

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every section is named
    """
    positions = [
        position for position, section in structure.sections
        if not is_non_blank_string(section.get(SectionKey.NAME.value))
    ]

    if not positions:
        return None

    return TypeStructureError.MISSING_SECTION_NAMES.format(positions=positions)


def _invalid_section_types_error(structure: TypeStructure) -> str | None:
    """
    Reports sections whose `type` is not a known SectionType, labelled `name (type)`

    An unknown value is not harmless: TypeRenderMeta falls back to a plain field section for it, so an
    MDS or ref-section with a mistyped marker would be silently imported as something else

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every section type is known
    """
    invalid = sorted(
        f'{section.get(SectionKey.NAME.value)} ({section.get(SectionKey.TYPE.value)})'
        for _, section in structure.sections
        if not SectionType.is_valid(section.get(SectionKey.TYPE.value))
    )

    if not invalid:
        return None

    return TypeStructureError.INVALID_SECTION_TYPES.format(
        sections=invalid,
        allowed=', '.join(member.value for member in SectionType),
    )


def _undefined_section_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports field names a section claims although the type does not define them

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every claimed field exists
    """
    undefined = sorted(set(structure.claimed) - structure.known_fields)

    if not undefined:
        return None

    return TypeStructureError.SECTION_FIELD_NOT_DEFINED.format(names=undefined)


def _multi_assigned_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports fields claimed by more than one section

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when no field is claimed twice
    """
    multi_assigned = sorted(
        name for name in duplicate_names(structure.claimed) if name in structure.known_fields
    )

    if not multi_assigned:
        return None

    return TypeStructureError.FIELD_IN_MULTIPLE_SECTIONS.format(names=multi_assigned)


def _summary_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports summary fields the type does not define - the summary line would render them as blanks

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when the summary only names defined fields
    """
    summary = structure.render_meta.get(TypeSchemaKey.SUMMARY.value)

    if not isinstance(summary, dict):
        return None

    referenced = _referenced_field_names([summary.get(TypeSchemaKey.FIELDS.value)])
    undefined = sorted({str(name) for name in referenced} - structure.known_fields)

    if not undefined:
        return None

    return TypeStructureError.SUMMARY_FIELD_NOT_DEFINED.format(names=undefined)


def _repeated_summary_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports summary fields named more than once - the summary line would show the value twice

    Args:
        structure (TypeStructure): The resolved structure of the type

    Returns:
        str | None: The error message, or None when every summary field is named once
    """
    summary = structure.render_meta.get(TypeSchemaKey.SUMMARY.value)

    if not isinstance(summary, dict):
        return None

    repeated = duplicate_names(_referenced_field_names([summary.get(TypeSchemaKey.FIELDS.value)]))

    if not repeated:
        return None

    return TypeStructureError.SUMMARY_FIELD_REPEATED.format(names=repeated)


def _external_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports external-link fields the type does not define - their href could not be filled in

    ``object_id`` is accepted besides the declared fields: the type builder offers it, and every object has one

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every external link only names defined fields
    """
    externals = (
        structure.render_meta.get(TypeSchemaKey.EXTERNALS.value)
        or structure.render_meta.get(LEGACY_EXTERNALS_KEY)
        or []
    )

    if not isinstance(externals, list):
        return None

    referenced = _referenced_field_names([
        external.get(TypeSchemaKey.FIELDS.value) for external in externals if isinstance(external, dict)
    ])
    # The object's own public_id is offered next to the declared fields - it is no field, and always there
    undefined = sorted({str(name) for name in referenced} - structure.known_fields - {EXTERNAL_LINK_OBJECT_ID})

    if not undefined:
        return None

    return TypeStructureError.EXTERNAL_FIELD_NOT_DEFINED.format(names=undefined)


def _missing_field_labels_error(structure: TypeStructure) -> str | None:
    """
    Reports fields with no usable label - the label is what the user sees on every form and table

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every field is labelled
    """
    unlabelled = sorted(
        str(field.get(FieldKey.NAME.value))
        for _, field in structure.fields
        if not is_non_blank_string(field.get(FieldKey.LABEL.value))
    )

    if not unlabelled:
        return None

    return TypeStructureError.MISSING_FIELD_LABELS.format(names=unlabelled)


def _missing_section_labels_error(structure: TypeStructure) -> str | None:
    """
    Reports sections with no usable label - the label is the heading the section is rendered under

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every section is labelled
    """
    unlabelled = sorted(
        str(section.get(SectionKey.NAME.value))
        for _, section in structure.sections
        if not is_non_blank_string(section.get(SectionKey.LABEL.value))
    )

    if not unlabelled:
        return None

    return TypeStructureError.MISSING_SECTION_LABELS.format(names=unlabelled)


def _location_field_errors(structure: TypeStructure) -> str | None:
    """
    Reports the two ways an uploaded type can get its location field wrong

    A CmdbType has **at most one** location field and it always carries the reserved name
    `dg_location` - the renderer, the CI Explorer, DocAPI and the object import all resolve the
    location value by that name, so a second location field or a differently-named one would simply
    never be read. A non-location field squatting on the reserved name is refused for the same reason

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The joined findings, or None when the location field is sound
    """
    location_fields = [
        field for _, field in structure.fields
        if field.get(FieldKey.TYPE.value) == FieldType.LOCATION.value
    ]
    errors: list[str] = []

    if len(location_fields) > 1:
        errors.append(TypeStructureError.MULTIPLE_LOCATION_FIELDS.format(
            names=sorted(str(field.get(FieldKey.NAME.value)) for field in location_fields),
        ))

    # The reserved name and the location type imply each other: either both hold or neither does
    misnamed = sorted(
        str(field.get(FieldKey.NAME.value))
        for _, field in structure.fields
        if (field.get(FieldKey.NAME.value) == DG_LOCATION_FIELD_NAME)
        != (field.get(FieldKey.TYPE.value) == FieldType.LOCATION.value)
    )

    if misnamed:
        errors.append(TypeStructureError.RESERVED_LOCATION_FIELD_NAME.format(
            reserved=DG_LOCATION_FIELD_NAME, names=misnamed,
        ))

    return STRUCTURE_ERROR_SEPARATOR.join(errors) if errors else None


STRUCTURE_RULES: tuple[Callable[[TypeStructure], str | None], ...] = (
    _duplicate_field_names_error,
    _missing_field_names_error,
    _missing_field_labels_error,
    _invalid_field_types_error,
    _location_field_errors,
    _duplicate_section_names_error,
    _missing_section_names_error,
    _missing_section_labels_error,
    _invalid_section_types_error,
    _undefined_section_fields_error,
    _multi_assigned_fields_error,
    _summary_fields_error,
    _repeated_summary_fields_error,
    _external_fields_error,
)


def validate_type_structure(type_entry: Any) -> str | None:
    """
    Validates the field / section structure of a CmdbType - a type write's payload or an uploaded entry

    Every rule in STRUCTURE_RULES runs and all findings are reported together, so one round trip surfaces every
    structural problem:

    1. every field name in `fields` is unique - the name is a field's immutable identifier
    2. every field carries a non-blank name and a non-blank label
    3. every field declares a known `FieldType`
    4. the location field is singular and named `dg_location` - and only a location field is
    5. every section name in `render_meta.sections` is unique
    6. every section carries a non-blank name and a non-blank label
    7. every section declares a known `SectionType`
    8. every field name a section references is actually defined in `fields`
    9. no field is shown by more than one section
    10. `render_meta.summary` only references defined fields, each once
    11. the external links only reference defined fields or the object's own `object_id`

    Allowed on purpose: a field no section shows (it renders nowhere, which breaks nothing), a section that shows
    no field (an empty box) and a select / radio offering no option yet (it holds no value until options are added;
    the Cable blueprint creates one when no cable-type option exists). An MDS section's `hidden_fields` count as an
    assignment. A ref-section's own field is identified by its type (`FieldType.REF_SECTION`) because it is
    deliberately not listed in the section's `fields` list

    Args:
        type_entry (Any): The type document - a write payload or an uploaded entry

    Returns:
        str | None: The joined structural errors, or None when the structure is sound
    """
    if not isinstance(type_entry, dict):
        return None

    structure = read_type_structure(type_entry)
    errors = [error for error in (rule(structure) for rule in STRUCTURE_RULES) if error]

    return STRUCTURE_ERROR_SEPARATOR.join(errors) if errors else None
