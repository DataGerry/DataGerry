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
The base fields of the PERSON and PERSON_GROUP SpecialTypes

Several Types may carry PERSON or PERSON_GROUP, and every one of them keeps the same base fields: the ISMS
references, the later user sync and the access scopes read a person by these names, whichever Type it belongs to.
A Type with the marker may add fields of its own, but it may neither drop a base field nor change its kind, nor
move it into a multi-data section (``type_structure_rules``). A base field that is a person selector keeps its
settings too: a group's ``members`` select persons, several of them (``LOCKED_BASE_FIELD_SETTINGS``)
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonField',
    'PersonGroupField',
    'LOCKED_BASE_FIELDS',
    'LOCKED_BASE_FIELD_SETTINGS',
]


class PersonField(BaseStrEnum):
    """
    The base field names of a Type carrying PERSON. USER holds the public_id of the user account the person is
    linked to; it stays empty until the user sync fills it
    """
    DISPLAY_NAME = 'display_name'
    FIRST_NAME = 'first_name'
    LAST_NAME = 'last_name'
    PHONE_NUMBER = 'phone_number'
    EMAIL = 'email'
    USER = 'user'


class PersonGroupField(BaseStrEnum):
    """
    The base field names of a Type carrying PERSON_GROUP. MEMBERS is a person selector holding the group's persons
    """
    NAME = 'name'
    EMAIL = 'email'
    MEMBERS = 'members'


# Per SpecialType: the base fields every Type with that marker keeps, each with the kind it keeps
LOCKED_BASE_FIELDS: dict[SpecialType, dict[str, FieldType]] = {
    SpecialType.PERSON: {
        PersonField.DISPLAY_NAME.value: FieldType.TEXT,
        PersonField.FIRST_NAME.value: FieldType.TEXT,
        PersonField.LAST_NAME.value: FieldType.TEXT,
        PersonField.PHONE_NUMBER.value: FieldType.TEXT,
        PersonField.EMAIL.value: FieldType.TEXT,
        PersonField.USER.value: FieldType.NUMBER,
    },
    SpecialType.PERSON_GROUP: {
        PersonGroupField.NAME.value: FieldType.TEXT,
        PersonGroupField.EMAIL.value: FieldType.TEXT,
        PersonGroupField.MEMBERS.value: FieldType.PERSON,
    },
}

# Per SpecialType: the settings a base person selector keeps, by field name - a group's members are persons, several
LOCKED_BASE_FIELD_SETTINGS: dict[SpecialType, dict[str, dict[str, object]]] = {
    SpecialType.PERSON_GROUP: {
        PersonGroupField.MEMBERS.value: {
            FieldKey.SELECTABLE.value: [SpecialType.PERSON.value],
            FieldKey.MULTIPLE.value: True,
        },
    },
}
