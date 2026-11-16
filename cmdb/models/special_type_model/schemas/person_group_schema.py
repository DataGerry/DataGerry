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
Definition of required sections and fields for the SpecialType PERSON_GROUP
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import (
    LOCKED_BASE_FIELDS,
    LOCKED_BASE_FIELD_SETTINGS,
    PERSON_EMAIL_PATTERN,
    PersonGroupField,
    PersonTypeSection,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_person_group_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the PERSON_GROUP SpecialType

    Every field is a base field (``LOCKED_BASE_FIELDS``). ``members`` is a person selector with the settings a
    group's members keep (``LOCKED_BASE_FIELD_SETTINGS``: persons only, several) - membership is stored on the group
    side only

    Returns:
        dict[str, Any]: Blueprint with the PERSON_GROUP section, fields and 'special_type' marker
    """
    kinds: dict[str, FieldType] = LOCKED_BASE_FIELDS[SpecialType.PERSON_GROUP]
    members_settings: dict[str, Any] = LOCKED_BASE_FIELD_SETTINGS[SpecialType.PERSON_GROUP][PersonGroupField.MEMBERS]

    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.PERSON_GROUP,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: PersonTypeSection.PERSON_GROUP_INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [field.value for field in PersonGroupField],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: kinds[PersonGroupField.NAME],
                FieldKey.NAME: PersonGroupField.NAME,
                FieldKey.LABEL: 'Name',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: kinds[PersonGroupField.EMAIL],
                FieldKey.NAME: PersonGroupField.EMAIL,
                FieldKey.LABEL: 'Email',
                FieldKey.REGEX: PERSON_EMAIL_PATTERN,
            },
            {
                FieldKey.TYPE: kinds[PersonGroupField.MEMBERS],
                FieldKey.NAME: PersonGroupField.MEMBERS,
                FieldKey.LABEL: 'Members',
                FieldKey.SELECTABLE: list(members_settings[FieldKey.SELECTABLE.value]),
                FieldKey.MULTIPLE: members_settings[FieldKey.MULTIPLE.value],
            },
        ],
    }
