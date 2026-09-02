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
The rules a CmdbType import judges an uploaded entry by

Every rule is a function that RETURNS a message instead of raising, so a single bad entry can be
reported in the partial report without touching the rest of the batch. Three groups live here:

    * the upload-only rules, gathered per verb by `validate_create_entry` / `validate_update_entry`
    * the structural rules, run together by `validate_type_structure` - one function per rule,
      registered in _STRUCTURE_RULES, all of them reported at once
    * `stored_type_update_blocker`, the rules an update can only answer against the STORED type

The repairs that quietly fix an upload instead of refusing it are the counterpart of this module and
live in `importer_type_repairs`
"""
from typing import Any, Callable, NamedTuple
from logging import Logger, getLogger

from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import (
    CmdbType,
    TypeSchemaKey,
    FieldKey,
    FieldType,
    SectionKey,
    SectionType,
    DG_LOCATION_FIELD_NAME,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.utils import duplicate_names, parse_import_bool, is_non_blank_string
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    location_field_removal_blocker,
    selectable_as_parent_change_blocker,
    referenced_section_removal_blocker,
    referenced_section_field_removal_blocker,
    uses_ports_change_blocker,
    special_type_is_unchanged,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS,
    STRUCTURE_ERROR_SEPARATOR,
    LEGACY_EXTERNALS_KEY,
    TypeImportError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The field types whose whole purpose is a list of options to pick from
_CHOICE_FIELD_TYPES: frozenset[str] = frozenset({FieldType.SELECT.value, FieldType.RADIO.value})

# -------------------------------------------------------------------------------------------------------------------- #


def special_type_license_error(type_entry: Any, ipam_locked: bool) -> str | None:
    """
    Reports an uploaded entry that would install an IPAM special type on an unlicensed instance

    Mirrors `types_helper.enforce_special_type_license`, which guards every other type write, but
    reports instead of aborting so one locked entry does not discard the rest of the upload. The
    licence state is the same for the whole request, so the caller evaluates it once and passes it in

    Only license-gated SpecialTypes are refused; an ungated member imports freely. Every gated
    member currently maps to the IPAM feature, RACK included as an interim decision (see
    SpecialType.get_license_gated_types). Only the UPLOADED entry's special_type is inspected, which is
    all a create can be judged by. On the update path the STORED type's marker is gated as well, by
    `stored_type_update_blocker` once the type has been read - an upload that simply omits the marker
    would otherwise let an unlicensed instance edit a Type that IS special here

    Args:
        type_entry (Any): A single entry of the uploaded payload
        ipam_locked (bool): Whether the IPAM feature is currently blocked for this request

    Returns:
        str | None: An error message if the entry may not be imported, None when it is allowed
    """
    if not ipam_locked or not isinstance(type_entry, dict):
        return None

    special_type = type_entry.get(TypeSchemaKey.SPECIAL_TYPE.value)

    if not SpecialType.is_license_gated(special_type):
        return None

    return TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type=special_type)


def uses_ports_license_error(type_entry: Any, ipam_locked: bool) -> str | None:
    """
    Reports an uploaded entry that would declare a port-bearing type on an unlicensed instance

    Mirrors `types_helper.enforce_uses_ports_license`, which guards the create and update routes, but
    reports instead of aborting so one locked entry does not discard the rest of the upload. The
    licence state is the same for the whole request, so the caller evaluates it once and passes it in

    Gated on the UPLOADED value only, matching the route guard: an entry that sets `uses_ports` false
    (or omits it) imports freely even unlicensed, so a port-bearing type can always be imported back
    with the flag turned off. Must run **after** `normalize_boolean_flags`, which is what turns the
    lenient spellings (`"yes"`, `1`) into the real boolean this rule reads

    Args:
        type_entry (Any): A single entry of the uploaded payload
        ipam_locked (bool): Whether the IPAM feature is currently blocked for this request

    Returns:
        str | None: An error message if the entry may not be imported, None when it is allowed
    """
    if not ipam_locked or not isinstance(type_entry, dict):
        return None

    if not type_entry.get(TypeSchemaKey.USES_PORTS.value):
        return None

    return TypeImportError.USES_PORTS_NOT_LICENSED.format(name=type_entry.get(TypeSchemaKey.NAME.value))


def validate_create_special_type(
    type_entry: Any,
    types_manager: TypesManager,
    ipam_locked: bool,
) -> str | None:
    """
    Applies every special_type rule that governs creating a CmdbType by import

    An entry declaring no special_type passes untouched - an exported ordinary type carries
    `special_type: ""`, which counts as "none". For an entry that does declare one, three rules apply
    in order, cheapest first:

    1. the value must be a `SpecialType` member
    2. the IPAM feature must be unlocked (delegated to `special_type_license_error`)
    3. no CmdbType may already carry that marker - a special type can exist only once

    Rule 3 is the only one that queries the database, and only for entries that got that far. It is
    also what makes a single upload declaring the same special_type twice safe: entries are inserted
    one at a time, so the second entry's check sees the first one's insert

    Args:
        type_entry (Any): A single entry of the uploaded payload
        types_manager (TypesManager): Manager used to check whether the marker is already claimed
        ipam_locked (bool): Whether the IPAM feature is currently blocked for this request

    Returns:
        str | None: An error message if the entry may not be created, None when it is allowed
    """
    if not isinstance(type_entry, dict):
        return None

    special_type = type_entry.get(TypeSchemaKey.SPECIAL_TYPE.value)

    if not special_type:
        return None

    if not SpecialType.is_valid(special_type):
        return TypeImportError.INVALID_SPECIAL_TYPE.format(
            special_type=special_type,
            allowed=', '.join(member.value for member in SpecialType),
        )

    license_error = special_type_license_error(type_entry, ipam_locked)

    if license_error:
        return license_error

    if types_manager.check_special_type_exists(special_type):
        return TypeImportError.SPECIAL_TYPE_EXISTS.format(special_type=special_type)

    return None


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

    return TypeImportError.DUPLICATE_FIELD_NAMES.format(names=sorted(duplicates))


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

    return TypeImportError.MISSING_FIELD_NAMES.format(positions=positions)


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

    return TypeImportError.INVALID_FIELD_TYPES.format(
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

    return TypeImportError.DUPLICATE_SECTION_NAMES.format(names=sorted(duplicates))


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

    return TypeImportError.MISSING_SECTION_NAMES.format(positions=positions)


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

    return TypeImportError.INVALID_SECTION_TYPES.format(
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

    return TypeImportError.SECTION_FIELD_NOT_DEFINED.format(names=undefined)


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

    return TypeImportError.FIELD_IN_MULTIPLE_SECTIONS.format(names=multi_assigned)


def _unassigned_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports fields no section claims

    A ref-section's own field belongs to its section by its type (`FieldType.REF_SECTION`) rather than
    by being listed in the section's `fields`, so it is never treated as orphaned

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every field has a section
    """
    exempt = {
        field.get(FieldKey.NAME.value)
        for _, field in structure.fields
        if field.get(FieldKey.TYPE.value) == FieldType.REF_SECTION.value
    }
    unassigned = sorted(structure.known_fields - set(structure.claimed) - exempt)

    if not unassigned:
        return None

    return TypeImportError.FIELD_WITHOUT_SECTION.format(names=unassigned)


def _empty_sections_error(structure: TypeStructure) -> str | None:
    """
    Reports sections that hold no field at all

    An MDS section's `hidden_fields` count as content. A ref-section is exempt: it owns no field list
    of its own, its content is the section of the referenced type. Nameless sections are skipped -
    `_missing_section_names_error` already reports those

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every section holds at least one field
    """
    empty: list[str] = []

    for _, section in structure.sections:
        section_name = section.get(SectionKey.NAME.value)

        if section.get(SectionKey.TYPE.value) == SectionType.REF_SECTION.value:
            continue

        if not is_non_blank_string(section_name):
            continue

        held = [
            name
            for key in (SectionKey.FIELDS.value, SectionKey.HIDDEN_FIELDS.value)
            for name in section.get(key) or []
        ]

        if not held:
            empty.append(section_name)

    if not empty:
        return None

    return TypeImportError.EMPTY_SECTION.format(names=sorted(empty))


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

    return TypeImportError.SUMMARY_FIELD_NOT_DEFINED.format(names=undefined)


def _external_fields_error(structure: TypeStructure) -> str | None:
    """
    Reports external-link fields the type does not define - their href could not be filled in

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
    undefined = sorted({str(name) for name in referenced} - structure.known_fields)

    if not undefined:
        return None

    return TypeImportError.EXTERNAL_FIELD_NOT_DEFINED.format(names=undefined)


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

    return TypeImportError.MISSING_FIELD_LABELS.format(names=unlabelled)


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

    return TypeImportError.MISSING_SECTION_LABELS.format(names=unlabelled)


def _missing_field_options_error(structure: TypeStructure) -> str | None:
    """
    Reports select / radio fields that offer nothing to pick

    A choice field is defined by its `options`, each of them a `{name, label}` pair: without at least
    one usable entry the field can never hold a value (and a radio renders as an empty group)

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        str | None: The error message, or None when every choice field offers a usable option
    """
    without_options = sorted(
        str(field.get(FieldKey.NAME.value))
        for _, field in structure.fields
        if field.get(FieldKey.TYPE.value) in _CHOICE_FIELD_TYPES and not _has_usable_options(field)
    )

    if not without_options:
        return None

    return TypeImportError.MISSING_FIELD_OPTIONS.format(names=without_options)


def _has_usable_options(field: dict[str, Any]) -> bool:
    """
    Reports whether a choice field carries at least one option a user could pick

    Args:
        field (dict[str, Any]): A field definition of the uploaded type

    Returns:
        bool: True when at least one option is a dict with a usable name and label
    """
    options = field.get(FieldKey.OPTIONS.value)

    if not isinstance(options, list):
        return False

    return any(
        isinstance(option, dict)
        and is_non_blank_string(option.get(FieldKey.NAME.value))
        and is_non_blank_string(option.get(FieldKey.LABEL.value))
        for option in options
    )


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
        errors.append(TypeImportError.MULTIPLE_LOCATION_FIELDS.format(
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
        errors.append(TypeImportError.RESERVED_LOCATION_FIELD_NAME.format(
            reserved=DG_LOCATION_FIELD_NAME, names=misnamed,
        ))

    return STRUCTURE_ERROR_SEPARATOR.join(errors) if errors else None


_STRUCTURE_RULES: tuple[Callable[[TypeStructure], str | None], ...] = (
    _duplicate_field_names_error,
    _missing_field_names_error,
    _missing_field_labels_error,
    _invalid_field_types_error,
    _missing_field_options_error,
    _location_field_errors,
    _duplicate_section_names_error,
    _missing_section_names_error,
    _missing_section_labels_error,
    _invalid_section_types_error,
    _undefined_section_fields_error,
    _multi_assigned_fields_error,
    _unassigned_fields_error,
    _empty_sections_error,
    _summary_fields_error,
    _external_fields_error,
)


def validate_type_structure(type_entry: Any) -> str | None:
    """
    Validates the field / section structure of an uploaded CmdbType

    Every rule in _STRUCTURE_RULES runs and all findings are reported together, so one upload round
    trip surfaces every structural problem:

    1. every field name in `fields` is unique - the name is a field's immutable identifier
    2. every field carries a non-blank name and a non-blank label
    3. every field declares a known `FieldType`
    4. a select / radio field offers at least one usable `{name, label}` option
    5. the location field is singular and named `dg_location` - and only a location field is
    6. every section name in `render_meta.sections` is unique
    7. every section carries a non-blank name and a non-blank label
    8. every section declares a known `SectionType`
    9. every field name a section references is actually defined in `fields`
    10. every field is assigned to exactly one section - neither orphaned nor claimed twice
    11. every section holds at least one field
    12. `render_meta.summary` and the external links only reference defined fields

    An MDS section's `hidden_fields` count as an assignment and as content. A ref-section is exempt
    from the "at least one field" rule and its own field from the assignment rule: that field is
    identified by its type (`FieldType.REF_SECTION`) because it is deliberately not listed in the
    section's `fields` list

    Args:
        type_entry (Any): A single entry of the uploaded payload

    Returns:
        str | None: The joined structural errors, or None when the structure is sound
    """
    if not isinstance(type_entry, dict):
        return None

    structure = read_type_structure(type_entry)
    errors = [error for error in (rule(structure) for rule in _STRUCTURE_RULES) if error]

    return STRUCTURE_ERROR_SEPARATOR.join(errors) if errors else None


def missing_type_name_error(type_entry: Any) -> str | None:
    """
    Reports an uploaded type that carries no usable name

    A type name is required and identifies the type in every list, filter and reference, so a missing
    or blank one is rejected here instead of surfacing as a CmdbType build failure with a message
    about the model

    Args:
        type_entry (Any): A single entry of the uploaded payload

    Returns:
        str | None: An error message if the entry has no name, None when it is named
    """
    if not isinstance(type_entry, dict):
        return None

    if is_non_blank_string(type_entry.get(TypeSchemaKey.NAME.value)):
        return None

    return TypeImportError.MISSING_TYPE_NAME.value


def as_public_id(value: Any) -> int | None:
    """
    Reads a public_id out of an uploaded value, whatever it was serialized as

    A hand-written or round-tripped upload can carry the id as a string (`"4712"`). CmdbType coerces
    it with `int()` when the instance is built, so everything downstream sees a number - anything
    comparing the raw value against a stored public_id has to coerce the same way or it silently
    never matches

    Args:
        value (Any): The raw `public_id` value of an uploaded entry

    Returns:
        int | None: The id as a number, or None when the value is not one
    """
    if isinstance(value, bool):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def type_name_conflict_error(
    type_entry: Any,
    types_manager: TypesManager,
    current_public_id: Any = None,
) -> str | None:
    """
    Reports an uploaded type whose name is already taken by a different CmdbType

    A type name must be unique across the installation. On the create path nothing is excluded, so any
    stored type with that name is a conflict. On the update path the type being replaced keeps its own
    name, so `current_public_id` excludes it from the check - coerced with `as_public_id`, since an
    upload may carry the id as a string and the stored one is always a number

    An entry with no name is not this check's business - building the CmdbType rejects it

    Args:
        type_entry (Any): A single entry of the uploaded payload
        types_manager (TypesManager): Manager used to look the name up
        current_public_id (Any): public_id of the type being updated, excluded from the conflict

    Returns:
        str | None: An error message if the name is taken, None when it is free
    """
    if not isinstance(type_entry, dict):
        return None

    name = type_entry.get(TypeSchemaKey.NAME.value)

    if not name:
        return None

    existing = types_manager.get_one_by({TypeSchemaKey.NAME.value: name})

    if not existing:
        return None

    if as_public_id(existing.get(TypeSchemaKey.PUBLIC_ID.value)) == as_public_id(current_public_id) \
            and current_public_id is not None:
        return None

    return TypeImportError.TYPE_NAME_EXISTS.format(name=name)


def normalize_boolean_flags(type_entry: Any) -> str | None:
    """
    Defaults and parses the optional boolean flags of an uploaded type, in place

    `active`, `selectable_as_parent` and `uses_ports` are optional: an entry that omits one (or
    leaves it empty) gets that flag's own default from `IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS` - True
    for the first two, which is the value every newly created type starts with, and False for
    `uses_ports`, which has to be opted into deliberately. A value that IS provided is parsed with
    the import's lenient boolean spellings (`parse_import_bool`, shared with the object import), so
    `"true"` / `1` / `"yes"` all work, and anything unusable is reported instead of being stored

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place

    Returns:
        str | None: The joined errors for the unusable values, or None when both flags are usable
    """
    if not isinstance(type_entry, dict):
        return None

    errors: list[str] = []

    for flag, default in IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS.items():
        value = type_entry.get(flag)

        if value is None or value == '':
            type_entry[flag] = default
            continue

        parsed = parse_import_bool(value)

        if parsed is None:
            errors.append(TypeImportError.INVALID_BOOLEAN_VALUE.format(field=flag, value=repr(value)))
        else:
            type_entry[flag] = parsed

    return STRUCTURE_ERROR_SEPARATOR.join(errors) if errors else None


def validate_create_entry(type_entry: Any, types_manager: TypesManager, ipam_locked: bool) -> str | None:
    """
    Runs every rule a CREATE entry can be judged by from the upload alone, first finding wins

    The order is deliberate: the cheap in-memory checks come before the two that query
    (`validate_create_special_type`'s uniqueness lookup and the name conflict), and `special_type` is
    settled first so a rejected entry never reaches the public_id assignment

    Note `normalize_boolean_flags` both defaults and validates, so it belongs in this sequence rather
    than with the repairs

    Args:
        type_entry (Any): A single entry of the uploaded payload
        types_manager (TypesManager): Manager used by the uniqueness rules
        ipam_locked (bool): Whether the IPAM feature is blocked for this request

    Returns:
        str | None: The first rule violation found, or None when the entry may be created
    """
    return (
        validate_create_special_type(type_entry, types_manager, ipam_locked)
        or validate_type_structure(type_entry)
        or normalize_boolean_flags(type_entry)
        # After normalisation, so the lenient spellings are already real booleans
        or uses_ports_license_error(type_entry, ipam_locked)
        or missing_type_name_error(type_entry)
        or type_name_conflict_error(type_entry, types_manager)
    )


def validate_update_entry(type_entry: Any, types_manager: TypesManager, ipam_locked: bool) -> str | None:
    """
    Runs every rule an UPDATE entry can be judged by from the upload alone, first finding wins

    The same sequence as the create path minus the rules that only make sense for a new type: the
    uploaded `special_type` is only licence-checked here (its value, uniqueness and immutability are
    decided against the stored type in `stored_type_update_blocker`), and the type keeps its own name
    in the uniqueness check

    Args:
        type_entry (Any): A single entry of the uploaded payload
        types_manager (TypesManager): Manager used by the name-uniqueness rule
        ipam_locked (bool): Whether the IPAM feature is blocked for this request

    Returns:
        str | None: The first rule violation found, or None when the entry may be applied
    """
    return (
        special_type_license_error(type_entry, ipam_locked)
        or validate_type_structure(type_entry)
        or normalize_boolean_flags(type_entry)
        # After normalisation, so the lenient spellings are already real booleans
        or uses_ports_license_error(type_entry, ipam_locked)
        or missing_type_name_error(type_entry)
        # The type being replaced keeps its own name, so it is excluded from the uniqueness check
        or type_name_conflict_error(type_entry, types_manager, type_entry.get(TypeSchemaKey.PUBLIC_ID.value))
    )


def stored_type_update_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
    ipam_locked: bool,
) -> str | None:
    """
    Applies the rules that can only be decided against the STORED CmdbType

    Everything else an import checks looks at the upload alone; these four need to know what the type
    currently is, so they run once the pre-update read is in hand:

    1. the license feature must be unlocked to touch a type that IS a license-gated special type
       here - the uploaded value alone is not enough, an upload that simply omits the marker would
       otherwise slip past. Every gated member currently maps to IPAM, RACK included
    2. `special_type` may not be changed by an update (the marker is immutable; an upload declaring a
       different one is refused rather than silently ignored)
    3. the location field may not be removed while CmdbObjects still hold a location value
    4. `selectable_as_parent` may not be turned off while CmdbObjects of the type are placed
    5. a section may not be removed (or renamed) while another CmdbType pulls its fields through a
       reference section
    6. a referenced section may not be left with none of the fields such a dependent shows
    7. `uses_ports` may not be turned off while Ports of the Type's Objects still exist

    Rules 3 to 7 delegate to the very blockers the normal update route aborts with, so the import and
    the route refuse the same edits with the same wording

    Args:
        request_user (CmdbUser): The user performing the import
        old_type (CmdbType): The stored CmdbType, as read before the update
        new_type (CmdbType): The CmdbType the upload would persist
        ipam_locked (bool): Whether the IPAM feature is currently blocked for this request

    Returns:
        str | None: The reason the update is refused, or None when it is allowed
    """
    if ipam_locked and SpecialType.is_license_gated(old_type.special_type):
        return TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type=old_type.special_type)

    # An exported ordinary type carries `special_type: ""` while a stored one may carry None, so both
    # sides are normalized to "no marker" before they are compared
    stored_marker: str | None = old_type.special_type or None
    uploaded_marker: str | None = new_type.special_type or None

    if not special_type_is_unchanged(stored_marker, uploaded_marker):
        return TypeImportError.SPECIAL_TYPE_IMMUTABLE.format(stored=stored_marker, uploaded=uploaded_marker)

    return (
        location_field_removal_blocker(request_user, old_type, new_type)
        or selectable_as_parent_change_blocker(request_user, old_type, new_type)
        or referenced_section_removal_blocker(request_user, old_type, new_type)
        or referenced_section_field_removal_blocker(request_user, old_type, new_type)
        or uses_ports_change_blocker(request_user, old_type, new_type)
    )
