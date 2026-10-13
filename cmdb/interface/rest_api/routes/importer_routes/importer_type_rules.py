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

    * the upload-only rules, gathered per verb by `validate_create_entry` / `validate_update_entry` (a create's
      identifiers all pass the identifier rule there, `new_identifiers_error`, and its field patterns the pattern
      rule, `field_patterns_error`)
    * the structural rules, run together by `validate_type_structure` - one function per rule,
      registered in _STRUCTURE_RULES, all of them reported at once
    * `stored_type_update_blocker`, the rules an update can only answer against the STORED type

The repairs that quietly fix an upload instead of refusing it are the counterpart of this module and
live in `importer_type_repairs`
"""
from typing import Any
from logging import Logger, getLogger

from cerberus import Validator

from cmdb.framework.field_pattern_rule import find_field_pattern_errors
from cmdb.framework.object_field_value_constants import FIELD_DEFAULT_ERROR_SEPARATOR
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.type_identifier_rules import (
    identifier_error,
    payload_identifier_names,
    stored_identifier_names,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.type_constants import STRUCTURE_ERROR_SEPARATOR
from cmdb.models.type_model.type_structure_rules import validate_type_structure
from cmdb.class_schema.type_model.cmdb_type_schema import get_type_acl_schema
from cmdb.interface.blueprints.schema_error_format import ERRORS_SEPARATOR, flatten_schema_errors
from cmdb.utils import coerce_whole_number, parse_import_bool, is_non_blank_string
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    field_identifier_change_blocker,
    location_field_removal_blocker,
    mds_section_identifier_change_blocker,
    selectable_as_parent_change_blocker,
    uses_ports_change_blocker,
    special_type_is_unchanged,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    referenced_section_field_removal_blocker,
    referenced_section_removal_blocker,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS,
    TypeImportError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


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

    Delegates to the project-wide `coerce_whole_number`, which is the same question asked everywhere
    else ("is this a whole number?") and already handles the two traps: a boolean is refused, because
    bool is an int subclass in Python and `True` would otherwise pass as the id 1, and a fractional
    float is refused rather than silently truncated into a different object's id. This wrapper stays
    because `as_public_id` says WHY the coercion is happening at each of its call sites

    Args:
        value (Any): The raw `public_id` value of an uploaded entry

    Returns:
        int | None: The id as a number, or None when the value is not one
    """
    return coerce_whole_number(value)


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


def acl_shape_error(type_entry: Any) -> str | None:
    """
    Judges an uploaded type's ``acl`` block by the same rule ``POST`` / ``PUT /types`` apply

    The import never runs ``CmdbType.SCHEMA``, so without this a block the routes refuse - ``groups`` that is no
    object, a permission list sent as a string, a non-boolean ``activated`` - would be built into the type by the
    model: some of it raising, some of it stored scrambled. An entry without an ``acl`` (or with a null one) is
    left to the repair that writes the default block; an unknown key inside the block is purged, as on the routes

    Args:
        type_entry (Any): A single entry of the uploaded payload

    Returns:
        str | None: The schema errors of the block, or None when it is usable or absent
    """
    if not isinstance(type_entry, dict) or type_entry.get(TypeSchemaKey.ACL.value) is None:
        return None

    acl_key: str = TypeSchemaKey.ACL.value
    validator = Validator({acl_key: get_type_acl_schema()}, purge_unknown=True)

    if validator.validate({acl_key: type_entry[acl_key]}):
        return None

    return TypeImportError.INVALID_ACL.format(
        detail=ERRORS_SEPARATOR.join(flatten_schema_errors(validator.errors)),
    )


def new_identifiers_error(type_entry: Any) -> str | None:
    """
    Reports a CREATE entry whose field or section identifiers the identifier rule refuses

    Every identifier of a type the import creates is new, so all of them are judged - the same rule, and the same
    message, the type create route aborts with (``type_identifier_rules``). An update entry is judged against the
    stored type instead, in ``stored_type_update_blocker``

    Args:
        type_entry (Any): A single entry of the uploaded payload

    Returns:
        str | None: The first refused identifier's message, or None
    """
    if not isinstance(type_entry, dict):
        return None

    return identifier_error(*payload_identifier_names(type_entry))


def field_patterns_error(fields: Any, stored_fields: Any = None) -> str | None:
    """
    Reports the field patterns of an entry that the browser and the server would read differently

    The rule and the wording the type routes refuse with (``field_pattern_rule``). A CREATE entry has every pattern
    judged; an UPDATE entry only the ones it adds or changes against the stored type, as on the update route

    Args:
        fields (Any): The entry's field definitions
        stored_fields (Any): The stored type's field definitions on an update; None on a create

    Returns:
        str | None: Every refused pattern's message, joined; None when all pass
    """
    errors: list[str] = find_field_pattern_errors(fields, stored_fields)

    return FIELD_DEFAULT_ERROR_SEPARATOR.join(errors) if errors else None


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
        or new_identifiers_error(type_entry)
        or field_patterns_error(type_entry.get(TypeSchemaKey.FIELDS.value) if isinstance(type_entry, dict) else None)
        or acl_shape_error(type_entry)
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
        or acl_shape_error(type_entry)
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

    Everything else an import checks looks at the upload alone; these need to know what the type
    currently is, so they run once the pre-update read is in hand:

    1. the license feature must be unlocked to touch a type that IS a license-gated special type
       here - the uploaded value alone is not enough, an upload that simply omits the marker would
       otherwise slip past. Every gated member currently maps to IPAM, RACK included
    2. `special_type` may not be changed by an update (the marker is immutable; an upload declaring a
       different one is refused rather than silently ignored)
    2a. a field identifier, or a multi-data-section identifier, may not be renamed while the type has
       Objects - the name IS the key every Object stores its values and rows under; and an identifier the
       update ADDS must pass the identifier rule (``type_identifier_rules``), as on the update route; so must
       a field pattern the update adds or changes (``field_pattern_rule``)
    3. the location field may not be removed while CmdbObjects still hold a location value
    4. `selectable_as_parent` may not be turned off while CmdbObjects of the type are placed
    5. a section may not be removed (or renamed) while another CmdbType pulls its fields through a
       reference section
    6. a referenced section may not be left with none of the fields such a dependent shows
    7. `uses_ports` may not be turned off while Ports of the Type's Objects still exist

    Rules 2a to 7 delegate to the very blockers the normal update route aborts with, so the import and
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

    stored_fields, stored_sections = stored_identifier_names(old_type)
    new_fields, new_sections = stored_identifier_names(new_type)

    return (
        identifier_error(new_fields, new_sections, stored_fields, stored_sections)
        or field_patterns_error(new_type.get_fields(), old_type.get_fields())
        or field_identifier_change_blocker(request_user, old_type, new_type)
        or mds_section_identifier_change_blocker(request_user, old_type, new_type)
        or location_field_removal_blocker(request_user, old_type, new_type)
        or selectable_as_parent_change_blocker(request_user, old_type, new_type)
        or referenced_section_removal_blocker(request_user, old_type, new_type)
        or referenced_section_field_removal_blocker(request_user, old_type, new_type)
        or uses_ports_change_blocker(request_user, old_type, new_type)
    )
