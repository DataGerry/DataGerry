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
Definition of required sections and fields for the SpecialType PERSON
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import (
    LOCKED_BASE_FIELDS,
    PERSON_EMAIL_PATTERN,
    PersonField,
    PersonTypeSection,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_person_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the PERSON SpecialType

    Every field is a base field (``LOCKED_BASE_FIELDS``): a Type carrying PERSON keeps them with these kinds. Only the
    display name is required: a person mirrored from a user by the user sync may carry no first or last name, and its
    display name always has a value

    Returns:
        dict[str, Any]: Blueprint with the PERSON section, fields and 'special_type' marker
    """
    kinds: dict[str, FieldType] = LOCKED_BASE_FIELDS[SpecialType.PERSON]

    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.PERSON,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: PersonTypeSection.PERSON_INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [field.value for field in PersonField],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: kinds[PersonField.DISPLAY_NAME],
                FieldKey.NAME: PersonField.DISPLAY_NAME,
                FieldKey.LABEL: 'Display name',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: kinds[PersonField.FIRST_NAME],
                FieldKey.NAME: PersonField.FIRST_NAME,
                FieldKey.LABEL: 'First name',
            },
            {
                FieldKey.TYPE: kinds[PersonField.LAST_NAME],
                FieldKey.NAME: PersonField.LAST_NAME,
                FieldKey.LABEL: 'Last name',
            },
            {
                FieldKey.TYPE: kinds[PersonField.PHONE_NUMBER],
                FieldKey.NAME: PersonField.PHONE_NUMBER,
                FieldKey.LABEL: 'Phone number',
            },
            {
                FieldKey.TYPE: kinds[PersonField.EMAIL],
                FieldKey.NAME: PersonField.EMAIL,
                FieldKey.LABEL: 'Email',
                FieldKey.REGEX: PERSON_EMAIL_PATTERN,
            },
        ],
    }
