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
Per-object normalization and validation for the object import workflows

Applied to each generated object before it is imported: forces the server-owned lifecycle fields,
derives ``special_type`` from the target type, defaults the optional fields and validates ``active``,
the multi-data sections and the field values against the target type.
Returns a list of human-readable error strings (empty when the object is valid) so the caller can
report a rejected object without aborting the whole import.

An unknown value of a select field normally extends that field's options on the target type, which is
recorded in the ``ImportTypeContext`` and persisted once per batch. The exception is a select field a
predefined section template owns: those definitions are immutable, so the value is rejected instead
(see ``cmdb.framework.section_templates.predefined_section_guard``).

The lenient boolean parser both imports apply to an uploaded flag lives in `cmdb.utils.helpers`
(`parse_import_bool`) - the type import defaults its own flags with it.
"""
from typing import Any
from collections import namedtuple
from datetime import datetime, timezone

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import DG_LOCATION_FIELD_NAME
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.utils.helpers import duplicate_names, parse_import_bool
from cmdb.framework.rack import normalize_rack_object, validate_rack_field_values
from cmdb.framework.importer.importer_constants import DEFAULT_OBJECT_VERSION
from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.section_templates import PREDEFINED_SELECT_OPTION_REJECTED
# -------------------------------------------------------------------------------------------------------------------- #

# The type-derived inputs the per-object normalization needs, computed once per import from the target
# type (see build_import_type_context):
#   clearable_reference_fields    - ref / ref-section / location field names whose value is cleared
#   field_type_map                - {field name: field type} used to stamp types + reject unknown fields
#   required_top_level            - names of required (non-cleared) top-level fields that must have a value
#   required_mds_by_section       - {section_id: {required field names}} for required (non-cleared) MDS fields
#   top_level_field_defaults      - {name: default value} of every top-level field (used to backfill)
#   mds_field_defaults_by_section - {section_id: {name: default value}} of each MDS section's fields
#   field_options                 - {name: set(option names)} for select + radio fields (select's set is
#                                   extended live as unknown values are accepted)
#   predefined_select_fields      - {name: owning template name} for the select fields a predefined
#                                   section template owns; their options must not be extended, so an
#                                   unknown value rejects the object instead
#   new_select_options            - {name: [added values]} accumulator of select options to persist to
#                                   the type after the batch (mutated during validation)
ImportTypeContext = namedtuple(
    'ImportTypeContext',
    [
        'clearable_reference_fields',
        'field_type_map',
        'required_top_level',
        'required_mds_by_section',
        'top_level_field_defaults',
        'mds_field_defaults_by_section',
        'field_options',
        'predefined_select_fields',
        'new_select_options',
    ],
)

# Field types whose value cannot be resolved on import yet (foreign object / location ids), so the value
# is cleared on every import instead of being stored as an unresolved id
_CLEARABLE_FIELD_TYPES: frozenset[str] = frozenset({
    FieldType.REFERENCE.value,
    FieldType.REF_SECTION.value,
    FieldType.LOCATION.value,
})


def normalize_and_validate_object(
        working_object: dict,
        special_type: SpecialType | None,
        author_id: int,
        type_context: ImportTypeContext | None = None) -> list[str]:
    """
    Normalizes an imported object's schema fields in place and validates the ones with rules

    Forces the server-owned fields (``author_id``, ``version``, ``creation_time``, ``last_edit_time``,
    ``editor_id``) regardless of any provided value, derives ``special_type`` from the target type
    (user input ignored), defaults ``ci_explorer_tooltip`` and ``active`` when absent, and validates
    ``active`` + the location placement + field-name uniqueness. When a ``type_context`` is given it
    additionally stamps each field's ``type`` (rejecting fields the type does not define), rejects a
    required field left without a value, and clears the values of reference / ref-section / location
    fields (their foreign ids cannot be resolved on import yet).

    ``author_id`` is never something the import file has to carry: it is neither required of nor read
    from the upload, and a value that reaches this point - including one a property mapping wrote onto
    the object - is replaced by the importing user

    Finally the feature invariants no field type can express are applied (currently the Rack value
    rules), on values the steps above have already coerced

    Args:
        working_object (dict): The generated object to normalize (mutated in place)
        special_type (SpecialType | None): The target type's special type (assigned to the object)
        author_id (int): public_id of the CmdbUser performing the import, forced onto every object
        type_context (ImportTypeContext | None): The target type's derived inputs (see
                                                 ``build_import_type_context``); None skips the
                                                 type-driven stamping / required / clearing steps

    Returns:
        list[str]: The validation errors; an empty list means the object is valid
    """
    errors: list[str] = []

    # Server-owned lifecycle fields are always forced, ignoring any provided value
    working_object[CmdbObjectKey.AUTHOR_ID.value] = author_id
    working_object[CmdbObjectKey.VERSION.value] = DEFAULT_OBJECT_VERSION
    working_object[CmdbObjectKey.CREATION_TIME.value] = datetime.now(timezone.utc)
    working_object[CmdbObjectKey.LAST_EDIT_TIME.value] = None
    working_object[CmdbObjectKey.EDITOR_ID.value] = None

    # special_type mirrors the target type; a provided value is ignored
    working_object[CmdbObjectKey.SPECIAL_TYPE.value] = special_type

    # Optional fields default when absent, otherwise keep the provided value
    working_object.setdefault(CmdbObjectKey.CI_EXPLORER_TOOLTIP.value, None)

    _validate_active(working_object, errors)
    _validate_location_field(working_object, errors)
    _validate_unique_field_names(working_object, errors)

    if type_context is not None:
        # A section the type does not define can hold nothing the type knows -> reject before
        # anything is backfilled into it
        _validate_mds_sections(working_object, type_context, errors)

        # Complete the object with the type's non-provided fields (defaults) before the type-driven checks
        _backfill_from_type(working_object, type_context)

        # Stamp each field's type from the target type (and reject any field the type does not define)
        if type_context.field_type_map:
            _stamp_and_validate_field_types(working_object, type_context.field_type_map, errors)

        # Validate / coerce each value against its field type (unknown select values extend the type)
        _validate_and_coerce_field_values(working_object, type_context, errors)

        # A required field must carry a value (cleared reference/location fields are exempt)
        _validate_required_fields(working_object, type_context, errors)

        # References/locations can't be resolved on import yet -> clear their values (keep the entries)
        clear_reference_values(working_object, type_context.clearable_reference_fields)

    # Feature invariants no field type can express. Runs last, on values already coerced above
    _validate_rack_values(working_object, special_type, errors)

    return errors


def _validate_rack_values(working_object: dict, special_type: SpecialType | None, errors: list[str]) -> None:
    """
    Applies the Rack value rules to an imported Rack object, and canonicalises its height

    Only the VALUE rules run here: the generic pipeline above already rejects a missing required
    value, so running the Rack presence rules too would report the same problem twice. What it does
    NOT catch is what this adds - `_coerce_number` happily accepts 0, -1 and 3.5 as a number, none of
    which is a rack height, and a Rackname of '   ' counts as present.

    Note the presence half therefore relies on the Rack type still marking both fields required; the
    object REST routes enforce presence unconditionally (see cmdb.framework.rack.enforcement)

    Args:
        working_object (dict): The generated object to validate (height canonicalised in place)
        special_type (SpecialType | None): The target type's special type
        errors (list[str]): The error accumulator to append to
    """
    if special_type != SpecialType.RACK:
        return

    normalize_rack_object(working_object)
    errors.extend(validate_rack_field_values(working_object))


def _validate_mds_sections(working_object: dict, type_context: ImportTypeContext, errors: list[str]) -> None:
    """
    Validates that every multi-data section of the object is one the target type defines

    A section id the type does not know is not just unusable - it is invisible: the renderer places an
    object's MDS rows by looking the section up on the type, so the rows would be stored and never
    shown again. The field-level check only catches this when the row's field names are unknown too,
    which they are not when a section was renamed or copied from another type

    Args:
        working_object (dict): The object being validated
        type_context (ImportTypeContext): The target type's derived inputs
        errors (list[str]): The error accumulator to append to on an unknown section
    """
    known_sections = set(type_context.mds_field_defaults_by_section)
    unknown = sorted({
        str(section.get(CmdbObjectMdsKey.SECTION_ID.value))
        for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []
        if section.get(CmdbObjectMdsKey.SECTION_ID.value) not in known_sections
    })

    if unknown:
        errors.append(f"Multi-data section(s) not defined on the type: {unknown}")


def _validate_active(working_object: dict, errors: list[str]) -> None:
    """
    Defaults / validates the ``active`` flag of an imported object (mutates the object / errors list)

    An absent or empty value defaults to True; any other value must parse as a boolean via
    ``parse_import_bool`` - if it does not, an error is appended and the object is left unchanged.

    Args:
        working_object (dict): The object being validated (its ``active`` value may be replaced)
        errors (list[str]): The error accumulator to append to on an invalid value
    """
    active_value = working_object.get(CmdbObjectKey.ACTIVE.value)

    if active_value is None or active_value == '':
        working_object[CmdbObjectKey.ACTIVE.value] = True
        return

    parsed = parse_import_bool(active_value)

    if parsed is None:
        errors.append(f"Invalid value for 'active': {active_value!r}")
    else:
        working_object[CmdbObjectKey.ACTIVE.value] = parsed


def _validate_location_field(working_object: dict, errors: list[str]) -> None:
    """
    Validates the placement of the special location field (``dg_location``)

    The location field may be assigned to the object at most once and must never appear inside a
    multi-data section (it is always a top-level field). Violations append an error; the object is
    left unchanged.

    Args:
        working_object (dict): The object being validated
        errors (list[str]): The error accumulator to append to on a violation
    """
    top_level_fields = working_object.get(CmdbObjectKey.FIELDS.value) or []

    location_count = sum(
        1 for field in top_level_fields
        if field.get(CmdbObjectFieldKey.NAME.value) == DG_LOCATION_FIELD_NAME
    )

    if location_count > 1:
        errors.append(f"The location field '{DG_LOCATION_FIELD_NAME}' can only be assigned once")

    if _location_field_in_mds(working_object):
        errors.append(
            f"The location field '{DG_LOCATION_FIELD_NAME}' is not allowed inside a multi-data section"
        )


def _location_field_in_mds(working_object: dict) -> bool:
    """
    Reports whether the location field (``dg_location``) appears inside any multi-data section

    Args:
        working_object (dict): The object being validated

    Returns:
        bool: True if a multi-data-section row carries the location field
    """
    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            for entry in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                if entry.get(CmdbObjectFieldKey.NAME.value) == DG_LOCATION_FIELD_NAME:
                    return True

    return False


def _validate_unique_field_names(working_object: dict, errors: list[str]) -> None:
    """
    Validates that field names (identifiers) are unique where they must be

    Each name in the top-level ``fields`` list must be unique, and each name within a single
    multi-data-section row must be unique. The same names repeating across different MDS rows is
    expected (every row of a section shares the section's field names) and is allowed.

    Args:
        working_object (dict): The object being validated
        errors (list[str]): The error accumulator to append to on a duplicate
    """
    top_level_names = [
        field.get(CmdbObjectFieldKey.NAME.value)
        for field in working_object.get(CmdbObjectKey.FIELDS.value) or []
    ]
    top_level_duplicates = duplicate_names(top_level_names)

    if top_level_duplicates:
        errors.append(f"Duplicate field name(s) in the object fields: {top_level_duplicates}")

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        section_id = section.get(CmdbObjectMdsKey.SECTION_ID.value)

        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            row_names = [
                entry.get(CmdbObjectFieldKey.NAME.value)
                for entry in row.get(CmdbObjectMdsRowKey.DATA.value, [])
            ]
            row_duplicates = duplicate_names(row_names)

            if row_duplicates:
                errors.append(
                    f"Duplicate field name(s) in multi-data section '{section_id}': {row_duplicates}"
                )


def build_field_type_map(type_fields: list[dict]) -> dict[str, str]:
    """
    Builds a ``{field name: field type}`` map from a type's field definitions

    Covers regular and multi-data-section fields (both live in the type's flat field list). Used to
    stamp each imported field's ``type`` and to detect fields the type does not define.

    Args:
        type_fields (list[dict]): The target type's field definitions

    Returns:
        dict[str, str]: The field-name-to-type map
    """
    return {
        field.get(FieldKey.NAME.value): field.get(FieldKey.TYPE.value)
        for field in type_fields or []
    }


def _mds_section_fields(type_instance) -> dict[str, list]:
    """
    Returns each multi-data-section's ordered field names, keyed by section id

    Args:
        type_instance: The target ``CmdbType``

    Returns:
        dict[str, list]: ``{section_id: [field name, …]}`` for every multi-data-section
    """
    sections: dict[str, list] = {}

    for section in type_instance.get_sections():
        if getattr(section, 'type', None) == SectionType.MDS_SECTION.value:
            sections[section.name] = list(section.get_fields())

    return sections


def _field_options(type_fields: list[dict]) -> dict[str, set]:
    """
    Returns the allowed option names of each select / radio field, keyed by field name

    A stored CmdbType keeps a choice field's options directly on the field, as
    ``options: [{'name': ..., 'label': ...}]`` - the option VALUE is its ``name``. (The assistant's
    profile format nests them one level deeper, under ``extras``, but ``profile_type_constructor``
    lifts them onto the field before the type is persisted, so no stored type carries that shape.)

    Args:
        type_fields (list[dict]): The target type's field definitions

    Returns:
        dict[str, set]: ``{field name: {option name, …}}`` for select and radio fields
    """
    options: dict[str, set] = {}

    for field in type_fields or []:
        if field.get(FieldKey.TYPE.value) in (FieldType.SELECT.value, FieldType.RADIO.value):
            field_options = field.get(FieldKey.OPTIONS.value) or []
            options[field.get(FieldKey.NAME.value)] = {
                option.get(FieldKey.NAME.value)
                for option in field_options
                if isinstance(option, dict)
            }

    return options


def build_import_type_context(
        type_instance,
        predefined_select_fields: dict[str, str] | None = None) -> ImportTypeContext:
    """
    Builds the per-import ``ImportTypeContext`` from the target type

    Derives, once per import: the clearable reference/location field names, the field-name-to-type map,
    the required (non-cleared) field names split into top-level and per-MDS-section, and the field
    defaults used to backfill non-provided fields (top-level and per MDS section). A required reference /
    ref-section / location field is excluded from the required sets (its value is cleared on import, so
    it cannot satisfy a required check).

    Args:
        type_instance: The target ``CmdbType`` being imported into
        predefined_select_fields (dict[str, str] | None): {select field name: owning predefined section
            template name} whose options the import must not extend (see
            ``cmdb.framework.section_templates.resolve_predefined_select_fields``); None means none

    Returns:
        ImportTypeContext: The derived inputs for ``normalize_and_validate_object``
    """
    type_fields = type_instance.get_fields()
    field_defaults = {field.get(FieldKey.NAME.value): field.get(FieldKey.VALUE.value) for field in type_fields or []}

    required_field_names = {
        field.get(FieldKey.NAME.value)
        for field in type_fields or []
        if field.get(FieldKey.REQUIRED.value) and field.get(FieldKey.TYPE.value) not in _CLEARABLE_FIELD_TYPES
    }

    section_fields = _mds_section_fields(type_instance)
    mds_field_names = set().union(*(set(names) for names in section_fields.values())) if section_fields else set()

    required_mds_by_section = {
        section_id: required_field_names.intersection(names)
        for section_id, names in section_fields.items()
        if required_field_names.intersection(names)
    }
    mds_required = set().union(*required_mds_by_section.values()) if required_mds_by_section else set()

    return ImportTypeContext(
        clearable_reference_fields=reference_field_names(type_fields),
        field_type_map=build_field_type_map(type_fields),
        required_top_level=required_field_names - mds_required,
        required_mds_by_section=required_mds_by_section,
        top_level_field_defaults={
            name: default for name, default in field_defaults.items() if name not in mds_field_names
        },
        mds_field_defaults_by_section={
            section_id: {name: field_defaults.get(name) for name in names}
            for section_id, names in section_fields.items()
        },
        field_options=_field_options(type_fields),
        predefined_select_fields=predefined_select_fields or {},
        new_select_options={},
    )


def apply_new_select_options(type_instance, new_select_options: dict) -> None:
    """
    Adds newly-seen select values as options on the target type's select fields (mutates the type)

    For each ``{field name: [values]}`` entry, appends ``{name, label}=value`` to that select field's
    ``options`` - the same list the type builder, the renderer and the frontend read (skipping any
    value already present). The caller is responsible for persisting the mutated type.

    A select field owned by a predefined section template can never appear here: validation rejects an
    unknown value for such a field instead of recording it (see ``_apply_value_suitability``).

    Args:
        type_instance: The target ``CmdbType`` (its select fields' options are extended in place)
        new_select_options (dict): ``{field name: [added option values]}`` collected during the import
    """
    for field in type_instance.get_fields():
        added_values = new_select_options.get(field.get(FieldKey.NAME.value))
        if not added_values:
            continue

        options = field.setdefault(FieldKey.OPTIONS.value, [])

        if not isinstance(options, list):
            continue

        existing = {option.get(FieldKey.NAME.value) for option in options if isinstance(option, dict)}

        for value in added_values:
            if value not in existing:
                options.append({FieldKey.NAME.value: value, FieldKey.LABEL.value: value})
                existing.add(value)


def _backfill_from_type(working_object: dict, type_context: ImportTypeContext) -> None:
    """
    Adds the type's fields the object did not provide, using each field's default value

    Top-level: every top-level type field absent from the object's ``fields`` is appended with its
    default. MDS: for every section instance the object carries, each row is completed with the section's
    fields it is missing (from the type default). Field ``type`` is stamped separately afterwards.

    Args:
        working_object (dict): The object to complete (mutated in place)
        type_context (ImportTypeContext): The target type's field defaults
    """
    top_level_fields = working_object.setdefault(CmdbObjectKey.FIELDS.value, [])
    present = {field.get(CmdbObjectFieldKey.NAME.value) for field in top_level_fields}

    for name, default in type_context.top_level_field_defaults.items():
        if name not in present:
            top_level_fields.append({CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: default})

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        defaults = type_context.mds_field_defaults_by_section.get(section.get(CmdbObjectMdsKey.SECTION_ID.value))
        if not defaults:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            row_data = row.setdefault(CmdbObjectMdsRowKey.DATA.value, [])
            row_present = {entry.get(CmdbObjectFieldKey.NAME.value) for entry in row_data}

            for name, default in defaults.items():
                if name not in row_present:
                    row_data.append({CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: default})


def _is_value_missing(value: Any) -> bool:
    """
    Reports whether a field value counts as "no value" for the required-field check

    Only None and the empty string are treated as missing; 0, False and other falsy-but-present values
    are considered valid values.

    Args:
        value (Any): The field value to test

    Returns:
        bool: True when the value is None or an empty string
    """
    return value is None or value == ''


def _validate_required_fields(working_object: dict, type_context: ImportTypeContext, errors: list[str]) -> None:
    """
    Rejects the object when a required field is left without a value (top-level or in an MDS row)

    A required top-level field must be present with a non-missing value. For each MDS section the object
    carries, every row must have a non-missing value for each of that section's required fields.
    Reference / ref-section / location fields are not required-checked (they are excluded from the
    context's required sets because their values are cleared on import).

    Args:
        working_object (dict): The object being validated
        type_context (ImportTypeContext): The target type's required-field sets
        errors (list[str]): The error accumulator to append to on a missing required value
    """
    top_level_values = {
        field.get(CmdbObjectFieldKey.NAME.value): field.get(CmdbObjectFieldKey.VALUE.value)
        for field in working_object.get(CmdbObjectKey.FIELDS.value) or []
    }
    missing_top_level = [
        name for name in type_context.required_top_level
        if name not in top_level_values or _is_value_missing(top_level_values[name])
    ]
    if missing_top_level:
        errors.append(f"Missing value for required field(s): {sorted(missing_top_level)}")

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        required_here = type_context.required_mds_by_section.get(section.get(CmdbObjectMdsKey.SECTION_ID.value))
        if not required_here:
            continue

        missing_in_section: set = set()
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            row_values = {
                entry.get(CmdbObjectFieldKey.NAME.value): entry.get(CmdbObjectFieldKey.VALUE.value)
                for entry in row.get(CmdbObjectMdsRowKey.DATA.value, [])
            }
            missing_in_section.update(
                name for name in required_here
                if name not in row_values or _is_value_missing(row_values[name])
            )

        if missing_in_section:
            section_id = section.get(CmdbObjectMdsKey.SECTION_ID.value)
            errors.append(
                f"Missing value for required field(s) {sorted(missing_in_section)} "
                f"in multi-data section '{section_id}'"
            )


def _stamp_and_validate_field_types(working_object: dict, field_type_map: dict, errors: list[str]) -> None:
    """
    Stamps each field's ``type`` from the target type and rejects fields the type does not define

    Applies to the top-level ``fields`` list and to every multi-data-section row. A field whose name is
    in the map has its ``type`` set from the map (overwriting any provided type); a field whose name is
    not defined on the type is collected and reported as an error (the object is rejected).

    Args:
        working_object (dict): The object being validated (field types stamped in place)
        field_type_map (dict): The target type's ``{field name: field type}`` map
        errors (list[str]): The error accumulator to append the unknown-field error to
    """
    unknown_names: list = []

    def _apply(entry: dict) -> None:
        name = entry.get(CmdbObjectFieldKey.NAME.value)
        if name in field_type_map:
            entry[CmdbObjectFieldKey.TYPE.value] = field_type_map[name]
        elif name not in unknown_names:
            unknown_names.append(name)

    for field in working_object.get(CmdbObjectKey.FIELDS.value) or []:
        _apply(field)

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            for entry in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                _apply(entry)

    if unknown_names:
        errors.append(f"Field name(s) not defined on the type: {unknown_names}")


def _coerce_number(value: Any) -> int | float | None:
    """
    Coerces a value to a number (int or float), or returns None when it is not numeric

    Booleans are rejected (they are not numbers); numeric strings are parsed (`'42'` -> 42,
    `'3.14'` -> 3.14).

    Args:
        value (Any): The value to coerce

    Returns:
        int | float | None: The number, or None when the value is not a valid number
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _coerce_reference_id(value: Any) -> int | None:
    """
    Coerces a reference / location value to an integer public_id, or returns None when it is not one

    Booleans and non-integer numbers/strings (e.g. `'3.14'`) are rejected; a whole numeric string
    (`'42'`) is parsed to an int.

    Args:
        value (Any): The value to coerce

    Returns:
        int | None: The integer id, or None when the value is not a valid reference id
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_scalar_value(field_type: str, value: Any) -> tuple[Any, str | None]:
    """
    Coerces / validates a non-empty value for a scalar field type

    Returns ``(coerced_value, error)``: on success ``error`` is None and ``coerced_value`` is the value
    to store (unchanged for text-like or unknown types); on failure ``coerced_value`` is None and
    ``error`` describes why the value is unsuitable. Select / radio are handled by the caller (they need
    the type's option list).

    Args:
        field_type (str): The field's type
        value (Any): The non-empty value to coerce

    Returns:
        tuple[Any, str | None]: (coerced value, error message or None)
    """
    if field_type == FieldType.NUMBER.value:
        number = _coerce_number(value)
        return (number, None) if number is not None else (None, f"'{value}' is not a valid number")

    if field_type in _CLEARABLE_FIELD_TYPES:  # ref / ref-section / location (value is cleared afterwards)
        reference_id = _coerce_reference_id(value)
        return (reference_id, None) if reference_id is not None else (None, f"'{value}' is not a valid reference id")

    if field_type == FieldType.CHECKBOX.value:
        boolean = parse_import_bool(value)
        return (boolean, None) if boolean is not None else (None, f"'{value}' is not a valid boolean")

    if field_type == FieldType.DATE.value:
        date_value = ImproveObject.improve_date(value)
        return (date_value, None) if isinstance(date_value, datetime) else (None, f"'{value}' is not a valid date")

    return value, None  # text / textarea / password / unknown -> unchanged


def _apply_value_suitability(entry: dict, type_context: ImportTypeContext, errors: list[str]) -> None:
    """
    Validates / coerces one field entry's value against its field type (empty values are skipped)

    Coerces number / reference / checkbox / date values in place; validates radio against its options;
    for an unknown select value adds a new option to the type (recorded for persistence) unless the field
    belongs to a predefined section template - such a field definition is immutable, so the unknown value
    is rejected instead. An unsuitable value appends an error (rejecting the object). text / textarea /
    password accept any value.

    Args:
        entry (dict): The field entry ({name, value, ...}) to check (value coerced in place)
        type_context (ImportTypeContext): The target type's derived inputs
        errors (list[str]): The error accumulator to append to on an unsuitable value
    """
    name = entry.get(CmdbObjectFieldKey.NAME.value)
    value = entry.get(CmdbObjectFieldKey.VALUE.value)

    if value is None or value == '':
        return

    field_type = type_context.field_type_map.get(name)

    if field_type == FieldType.SELECT.value:
        options = type_context.field_options.get(name, set())
        if value not in options:
            owning_template: str | None = type_context.predefined_select_fields.get(name)

            if owning_template:
                # Adding the option would edit a predefined section template's field definition
                errors.append(
                    f"Field '{name}': "
                    f"{PREDEFINED_SELECT_OPTION_REJECTED.format(value=value, template=owning_template)}"
                )
                return

            options.add(value)  # recognised for the rest of the batch
            type_context.new_select_options.setdefault(name, []).append(value)
        return

    if field_type == FieldType.RADIO.value:
        if value not in type_context.field_options.get(name, set()):
            errors.append(f"Field '{name}': '{value}' is not an allowed option")
        return

    coerced, error = _coerce_scalar_value(field_type, value)
    if error:
        errors.append(f"Field '{name}': {error}")
    else:
        entry[CmdbObjectFieldKey.VALUE.value] = coerced


def _validate_and_coerce_field_values(working_object: dict, type_context: ImportTypeContext,
                                      errors: list[str]) -> None:
    """
    Applies the value-suitability check to every field, top-level and inside MDS rows

    Args:
        working_object (dict): The object being validated (field values coerced in place)
        type_context (ImportTypeContext): The target type's derived inputs
        errors (list[str]): The error accumulator to append to on an unsuitable value
    """
    for field in working_object.get(CmdbObjectKey.FIELDS.value) or []:
        _apply_value_suitability(field, type_context, errors)

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            for entry in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                _apply_value_suitability(entry, type_context, errors)


def reference_field_names(type_fields: list[dict]) -> set[str]:
    """
    Collects the names of a type's fields whose value must be cleared on import

    These are the reference (``ref``), reference-section (``ref-section-field``) and location
    (``location``) fields - their foreign object / location ids cannot currently be resolved on import,
    so the values are cleared instead of stored unresolved.

    Args:
        type_fields (list[dict]): The target type's field definitions

    Returns:
        set[str]: The names of the fields whose value must be cleared
    """
    return {
        field.get(FieldKey.NAME.value)
        for field in type_fields or []
        if field.get(FieldKey.TYPE.value) in _CLEARABLE_FIELD_TYPES
    }


def clear_reference_values(working_object: dict, clearable_field_names: set) -> None:
    """
    Clears (sets ``None``) the value of every reference / ref-section / location field on the object

    Applies both to the top-level ``fields`` list and to multi-data-section rows, so no unresolved
    foreign id is imported. The field entries are kept; only their value is emptied.

    Args:
        working_object (dict): The object to clear (mutated in place)
        clearable_field_names (set): The field names whose value must be cleared
    """
    if not clearable_field_names:
        return

    for field in working_object.get(CmdbObjectKey.FIELDS.value) or []:
        if field.get(CmdbObjectFieldKey.NAME.value) in clearable_field_names:
            field[CmdbObjectFieldKey.VALUE.value] = None

    for section in working_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            for entry in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                if entry.get(CmdbObjectFieldKey.NAME.value) in clearable_field_names:
                    entry[CmdbObjectFieldKey.VALUE.value] = None
