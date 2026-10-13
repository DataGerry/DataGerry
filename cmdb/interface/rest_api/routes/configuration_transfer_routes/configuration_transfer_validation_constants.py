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
The problem messages of the import checks (`configuration_transfer_validation`)

Every problem of an entry is reported as `ENTRY_PROBLEM`, naming the component and the entry (its public_id, or its
position when it carries no usable one), so a refused file says where each problem sits
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ENTRY_PROBLEM',
    'ENTRY_POSITION',
    'COMPONENT_PROBLEM',
    'PUBLIC_ID_NOT_A_NUMBER',
    'PUBLIC_ID_REPEATED',
    'VALUE_REPEATED',
    'PREDEFINED_TEMPLATE_IN_FILE',
    'TEMPLATE_NAME_IS_PREDEFINED',
    'TEMPLATE_FIELDS_NOT_A_LIST',
    'TEMPLATE_FIELD_NOT_AN_OBJECT',
    'TYPE_REFERENCES_UNKNOWN_TYPES',
    'SPECIAL_TYPE_REPEATED',
    'CATEGORY_TYPES_NOT_IDS',
    'CATEGORY_TYPES_REPEATED',
    'CATEGORY_TYPES_UNKNOWN',
    'CATEGORY_PARENT_UNKNOWN',
    'TYPE_IN_SEVERAL_CATEGORIES',
    'RELATION_TYPES_UNKNOWN',
    'TEMPLATE_COPY_CONFLICT',
]

# One entry's problem: '<component> <entry>: <problem>'
ENTRY_PROBLEM: str = "{component} {entry}: {problem}"
# How an entry without a usable public_id is named
ENTRY_POSITION: str = "entry #{index}"
# A problem of a component as a whole (two entries sharing a value): '<component>: <problem>'
COMPONENT_PROBLEM: str = "{component}: {problem}"

PUBLIC_ID_NOT_A_NUMBER: str = "the 'public_id' must be a positive whole number"
PUBLIC_ID_REPEATED: str = "the public_id(s) {values} are used by more than one entry"
VALUE_REPEATED: str = "the '{key}' value(s) {values} are used by more than one entry"

PREDEFINED_TEMPLATE_IN_FILE: str = (
    "a predefined section template cannot be imported - DataGerry seeds its own on every system"
)
TEMPLATE_NAME_IS_PREDEFINED: str = "the name '{name}' belongs to a predefined section template"
TEMPLATE_FIELDS_NOT_A_LIST: str = "the 'fields' must be a list"
TEMPLATE_FIELD_NOT_AN_OBJECT: str = "every entry of 'fields' must be an object"

TYPE_REFERENCES_UNKNOWN_TYPES: str = "references the type(s) {type_ids}, which the file does not contain"
SPECIAL_TYPE_REPEATED: str = "the special type(s) {values} are claimed by more than one type"

CATEGORY_TYPES_NOT_IDS: str = "the 'types' entries {values} are no type ids"
CATEGORY_TYPES_REPEATED: str = "the 'types' name the type(s) {type_ids} more than once"
CATEGORY_TYPES_UNKNOWN: str = "the 'types' name the type(s) {type_ids}, which the file does not contain"
CATEGORY_PARENT_UNKNOWN: str = "the 'parent' {parent} is no other category of the file"
TYPE_IN_SEVERAL_CATEGORIES: str = "the type(s) {type_ids} are held by more than one category"

RELATION_TYPES_UNKNOWN: str = "the '{key}' name the type(s) {type_ids}, which the file does not contain"

TEMPLATE_COPY_CONFLICT: str = (
    "the field '{field}' sits in the section of the global section template '{template}', which does not own it"
)
