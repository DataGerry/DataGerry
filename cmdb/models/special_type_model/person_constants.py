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
Constants of the PERSON and PERSON_GROUP SpecialTypes and of the person field (FieldType.PERSON)

Persons and person groups are ordinary CmdbObjects whose CmdbType carries the PERSON or PERSON_GROUP
marker. Anything else points at them through a person field: a field of FieldType.PERSON whose value is a
``{'ref_type': ..., 'id': ...}`` pair - or a list of those pairs when the field's 'multiple' flag is set.
'ref_type' names the SpecialType of the referenced object (the same tokens as PersonReferenceType, so the
ISMS references and the person fields speak one vocabulary), 'id' its public_id.

Group membership is stored once, on the group: the MEMBERS person field of a PERSON_GROUP object lists its
persons. A person's memberships are derived from it, never stored on the person.

A field's 'name' is its immutable identifier, so the field and section values below are a stored-data
contract and must not be changed once such a type exists in any installation
"""
from cmdb.utils import BaseStrEnum

__all__: list[str] = [
    'PersonField',
    'PersonGroupField',
    'PersonSection',
    'PersonGroupSection',
    'PersonRefKind',
    'PersonValueKey',
    'SALUTATION_OPTIONS',
]


class PersonField(BaseStrEnum):
    """
    Field names of the PERSON SpecialType

    DISPLAY_NAME is the full name shown wherever the person is referenced and the only required field
    """
    DISPLAY_NAME = 'dg-person-display-name'
    SALUTATION = 'dg-person-salutation'
    FIRST_NAME = 'dg-person-first-name'
    LAST_NAME = 'dg-person-last-name'
    EMAIL = 'dg-person-email'
    PHONE_NUMBER = 'dg-person-phone-number'


class PersonGroupField(BaseStrEnum):
    """
    Field names of the PERSON_GROUP SpecialType

    MEMBERS is a multiple person field restricted to PERSON objects - the one place a membership is stored
    """
    NAME = 'dg-person-group-name'
    EMAIL = 'dg-person-group-email'
    MEMBERS = 'dg-person-group-members'


class PersonSection(BaseStrEnum):
    """
    Section names of the PERSON SpecialType
    """
    INFORMATION = 'dg-person-information'


class PersonGroupSection(BaseStrEnum):
    """
    Section names of the PERSON_GROUP SpecialType
    """
    INFORMATION = 'dg-person-group-information'
    MEMBERS = 'dg-person-group-members-section'


class PersonRefKind(BaseStrEnum):
    """
    What a person field may select - the value of its 'person_ref_kind' key

    PERSON and PERSON_GROUP restrict it to objects of that SpecialType, BOTH allows either
    """
    PERSON = 'PERSON'
    PERSON_GROUP = 'PERSON_GROUP'
    BOTH = 'BOTH'


class PersonValueKey(BaseStrEnum):
    """
    Keys of one selection stored in a person field's value
    """
    REF_TYPE = 'ref_type'
    ID = 'id'


# (name, label) of the salutation select of the PERSON SpecialType
SALUTATION_OPTIONS: tuple[tuple[str, str], ...] = (
    ('mr', 'Mr.'),
    ('ms', 'Ms.'),
    ('mx', 'Mx.'),
    ('dr', 'Dr.'),
)
