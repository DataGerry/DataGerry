# DATAGERRY - OpenSource Enterprise CMDB
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
Definition of required sections and fields for the SpecialTypes PERSON and PERSON_GROUP
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_constants import (
    PersonField,
    PersonGroupField,
    PersonGroupSection,
    PersonRefKind,
    PersonSection,
    SALUTATION_OPTIONS,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_person_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the PERSON SpecialType

    Holds no person field of its own: the groups a person belongs to are derived from the groups'
    MEMBERS field, so there is nothing to cross-wire after the insert

    Returns:
        dict[str, Any]: Blueprint with the PERSON section, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.PERSON,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: PersonSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    PersonField.DISPLAY_NAME,
                    PersonField.SALUTATION,
                    PersonField.FIRST_NAME,
                    PersonField.LAST_NAME,
                    PersonField.EMAIL,
                    PersonField.PHONE_NUMBER,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonField.DISPLAY_NAME,
                FieldKey.LABEL: 'Full name',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: FieldType.SELECT,
                FieldKey.NAME: PersonField.SALUTATION,
                FieldKey.LABEL: 'Salutation',
                FieldKey.OPTIONS: [
                    {FieldKey.NAME: name, FieldKey.LABEL: label}
                    for name, label in SALUTATION_OPTIONS
                ],
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonField.FIRST_NAME,
                FieldKey.LABEL: 'First name',
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonField.LAST_NAME,
                FieldKey.LABEL: 'Last name',
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonField.EMAIL,
                FieldKey.LABEL: 'Email',
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonField.PHONE_NUMBER,
                FieldKey.LABEL: 'Phone number',
            },
        ],
    }


def get_person_group_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the PERSON_GROUP SpecialType

    The MEMBERS field is a multiple person field restricted to PERSON objects. It is the one place a
    membership is stored, so adding a person to a group or removing them is an ordinary edit of the group

    Returns:
        dict[str, Any]: Blueprint with the PERSON_GROUP sections, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.PERSON_GROUP,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: PersonGroupSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    PersonGroupField.NAME,
                    PersonGroupField.EMAIL,
                ],
            },
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: PersonGroupSection.MEMBERS,
                SectionKey.LABEL: 'Members',
                SectionKey.FIELDS: [
                    PersonGroupField.MEMBERS,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonGroupField.NAME,
                FieldKey.LABEL: 'Name',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: PersonGroupField.EMAIL,
                FieldKey.LABEL: 'Email',
            },
            {
                FieldKey.TYPE: FieldType.PERSON,
                FieldKey.NAME: PersonGroupField.MEMBERS,
                FieldKey.LABEL: 'Members',
                FieldKey.PERSON_REF_KIND: PersonRefKind.PERSON,
                FieldKey.MULTIPLE: True,
            },
        ],
    }
