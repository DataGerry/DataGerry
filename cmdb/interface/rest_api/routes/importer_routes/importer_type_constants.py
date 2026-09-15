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
Shared constants for the CmdbType import REST routes
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.type_model import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'IMPORT_UPDATE_PRESERVED_FIELDS',
    'STRUCTURE_ERROR_SEPARATOR',
    'LEGACY_EXTERNALS_KEY',
    'DEFAULT_TYPE_ICON',
    'DEFAULT_TYPE_ACL',
    'IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS',
    'TypeImporterFormField',
    'TypeImportError',
]

# A ref-section owns exactly one field of its own which is NOT listed in the section's own `fields`
# list (real ref-sections carry `fields: []`), so it is identified by its FIELD type -
# FieldType.REF_SECTION ('ref-section-field') - and exempted from "every field belongs to a section".
# NOTE the renderer resolves the same field by the naming convention `<section name>-field`
# (cmdb_multi_render._merge_reference_section); the type is what identifies it here

# A type can break several structural rules at once; an entry is reported with one message, so the
# individual findings are joined into that one message
STRUCTURE_ERROR_SEPARATOR: str = '; '

# Fields an import UPDATE must never write. `author_id` / `creation_time` / `version` describe how the
# type came to exist on THIS system, and `special_type` is immutable by design - it may only be set
# when the type is created. The uploaded values are dropped from the update payload; because the
# update is a `$set`, omitting a field leaves the stored value untouched
IMPORT_UPDATE_PRESERVED_FIELDS: tuple[str, ...] = (
    TypeSchemaKey.AUTHOR_ID.value,
    TypeSchemaKey.CREATION_TIME.value,
    TypeSchemaKey.SPECIAL_TYPE.value,
    TypeSchemaKey.VERSION.value,
)

# Older type documents spell the external-link list 'external' instead of 'externals'.
# TypeRenderMeta.from_data still falls back to it, so the import validates that spelling too
LEGACY_EXTERNALS_KEY: str = 'external'

# Free Font Awesome class stamped onto 'render_meta.icon' when the upload brings no icon. A type
# without one renders with no symbol at all in the type list, object tables and the CI explorer, so
# the import fills in a neutral placeholder the user can change later. 'fas fa-cube' is the same
# generic symbol the rest of the codebase uses for "some CI"
DEFAULT_TYPE_ICON: str = 'fas fa-cube'

# The boolean type flags an upload may omit, each with the value it defaults to when absent or empty.
# 'active' and 'selectable_as_parent' default to True - a type is usable and selectable as a location
# parent unless it says otherwise - while 'uses_ports' defaults to False, because opting a type into
# Port Connectivity has to be a deliberate choice (and is IPAM-licensed). All of them accept the
# lenient import spellings (true/yes/1) via parse_import_bool
IMPORT_BOOLEAN_TYPE_FIELD_DEFAULTS: dict[str, bool] = {
    TypeSchemaKey.ACTIVE.value: True,
    TypeSchemaKey.SELECTABLE_AS_PARENT.value: True,
    TypeSchemaKey.USES_PORTS.value: False,
}

# The "no access control" ACL every newly created CmdbType starts with (same shape the assistant's
# profile_type_constructor seeds and the one AccessControlList.from_data({}) produces): the ACL is
# switched off and no group is granted anything, so the type is governed by the normal rights alone
DEFAULT_TYPE_ACL: dict[str, Any] = {
    AclKey.ACTIVATED.value: False,
    AclKey.GROUPS.value: {
        AclKey.INCLUDES.value: {},
    },
}


class TypeImporterFormField(BaseStrEnum):
    """Multipart form-field names read from a type-import request"""
    UPLOAD_FILE = 'uploadFile'


class TypeImportError(BaseStrEnum):
    """
    Messages reported for a type import

    NO_UPLOAD_FILE, INVALID_UPLOAD_PAYLOAD and MALFORMED_JSON describe an unusable upload and are
    raised as an HTTP 400 for the whole request; every other member is a per-entry message reported in
    the `failed_imports` of the partial report. Members with a `{...}` placeholder are filled via
    `format()`
    """
    NO_UPLOAD_FILE = 'No upload file was provided!'
    INVALID_UPLOAD_PAYLOAD = 'The uploaded data must be a JSON list of Types!'
    MALFORMED_JSON = 'The uploaded data is not valid JSON: {detail}'
    MISSING_TYPE_NAME = 'The Type data does not contain a name!'
    INVALID_BOOLEAN_VALUE = "Invalid value for '{field}': {value}"
    SPECIAL_TYPE_NOT_LICENSED = 'The IPAM feature is not licensed, so the special Type "{special_type}" ' \
                                'can not be imported!'
    USES_PORTS_NOT_LICENSED = 'The IPAM feature is not licensed, so the Type "{name}" can not be ' \
                              'imported with "uses_ports" enabled!'
    INVALID_SPECIAL_TYPE = '"{special_type}" is not a valid special Type. Allowed: {allowed}'
    SPECIAL_TYPE_EXISTS = 'A Type with the special Type "{special_type}" already exists - a special ' \
                          'Type can only exist once!'
    TYPE_NAME_EXISTS = 'A Type with the name "{name}" already exists - the name must be unique!'
    SPECIAL_TYPE_IMMUTABLE = 'The special Type of a stored Type can not be changed by an import ' \
                             '(stored: {stored}, uploaded: {uploaded})!'
    NOT_A_TYPE_ENTRY = 'This entry is not a Type object!'
    INVALID_FIELD_TYPES = 'Field(s) with an unknown type: {fields}. Allowed types: {allowed}'
    SECTION_FIELD_NOT_DEFINED = 'Section(s) reference field(s) the Type does not define: {names}'
    DUPLICATE_FIELD_NAMES = 'Duplicate field name(s): {names}'
    DUPLICATE_SECTION_NAMES = 'Duplicate section name(s): {names}'
    FIELD_IN_MULTIPLE_SECTIONS = 'Field(s) assigned to more than one section: {names}'
    FIELD_WITHOUT_SECTION = 'Field(s) not assigned to any section: {names}'
    MISSING_FIELD_NAMES = 'Field(s) without a name at position(s): {positions}'
    MISSING_FIELD_LABELS = 'Field(s) without a label: {names}'
    MISSING_SECTION_LABELS = 'Section(s) without a label: {names}'
    MISSING_FIELD_OPTIONS = 'Field(s) of type select/radio without usable options: {names}'
    MULTIPLE_LOCATION_FIELDS = 'A Type may declare at most one location field, found: {names}'
    RESERVED_LOCATION_FIELD_NAME = "The name '{reserved}' is reserved for the location field: " \
                                   '{names} must either use the location type or another name'
    MISSING_SECTION_NAMES = 'Section(s) without a name at position(s): {positions}'
    INVALID_SECTION_TYPES = 'Section(s) with an unknown type: {sections}. Allowed types: {allowed}'
    EMPTY_SECTION = 'Section(s) without any field: {names}'
    SUMMARY_FIELD_NOT_DEFINED = 'The summary references field(s) the Type does not define: {names}'
    EXTERNAL_FIELD_NOT_DEFINED = 'External link(s) reference field(s) the Type does not define: {names}'
    NORMALIZATION_FAILED = 'Failed to prepare this Type for import: {detail}'
    REPAIRED_TYPE_INVALID = 'Completing this Type from its global section template(s) made it ' \
                            'invalid: {detail}'
    CREATE_SIDE_EFFECTS_FAILED = 'The Type was imported, but wiring up its SpecialType failed: {detail}'
    UPDATE_SIDE_EFFECTS_FAILED = 'The Type was updated, but applying the follow-up changes to its ' \
                                 'Objects, Locations and section templates failed: {detail}'
    PUBLIC_ID_ASSIGNMENT_FAILED = 'Failed to assign a public_id to this Type: {detail}'
    INVALID_TYPE_DATA = 'Failed to create a Type instance from the provided data: {detail}'
    IMPORT_FAILED = 'Failed to import this Type: {detail}'
    TYPE_NOT_FOUND = 'No Type with public_id {public_id} exists, it can not be updated!'
    UPDATE_FAILED = 'Failed to update this Type: {detail}'
    # Reported for an entry whose import failed with an error the import itself did not anticipate. The
    # batch keeps running and the entry lands in failed_imports like any other rejection, so a defect
    # in one Type can never discard the Types around it
    UNEXPECTED_IMPORT_ERROR = 'Unexpected error while importing this Type: {detail}'
