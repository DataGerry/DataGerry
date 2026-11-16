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
Constants of the default person Types
"""
from dataclasses import dataclass

from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import DefaultPersonType, PersonField, PersonGroupField
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DefaultTypeSpec',
    'DEFAULT_TYPE_SPECS',
    'SYSTEM_AUTHOR_ID',
    'FREE_NAME_SEPARATOR',
    'FIRST_FREE_NAME_SUFFIX',
    'SEED_PROJECTION',
    'SYSTEM_TYPES_CRITERIA',
    'DEFAULT_TYPES_SEED_RACE_WARNING',
    'RISK_OWNER_OBJECT_DELETE_MESSAGE',
    'RISK_OWNER_OBJECT_CHECK_FAILED_MESSAGE',
]


@dataclass(frozen=True)
class DefaultTypeSpec:
    """
    How the default Type of one marker is presented

    Attributes:
        name (str): The name it is created with when free
        label (str): Its label
        icon (str): Its icon
        summary_field (str): The base field its summary line and its CI Explorer label show
    """
    name: str
    label: str
    icon: str
    summary_field: str


# Per marker with a default Type: how that Type is presented. The order is the seeding order
DEFAULT_TYPE_SPECS: dict[SpecialType, DefaultTypeSpec] = {
    SpecialType.PERSON: DefaultTypeSpec(
        name=DefaultPersonType.PERSON_NAME.value,
        label=DefaultPersonType.PERSON_LABEL.value,
        icon=DefaultPersonType.PERSON_ICON.value,
        summary_field=PersonField.DISPLAY_NAME.value,
    ),
    SpecialType.PERSON_GROUP: DefaultTypeSpec(
        name=DefaultPersonType.PERSON_GROUP_NAME.value,
        label=DefaultPersonType.PERSON_GROUP_LABEL.value,
        icon=DefaultPersonType.PERSON_GROUP_ICON.value,
        summary_field=PersonGroupField.NAME.value,
    ),
}

# The author of what the system creates itself: no user account has this public_id
SYSTEM_AUTHOR_ID: int = 0

# A taken default name is replaced by '<name>_<n>', counting up from 2
FREE_NAME_SEPARATOR: str = '_'
FIRST_FREE_NAME_SUFFIX: int = 2

# What the seeding reads of every stored Type: enough to know the taken names and the existing default Types
SEED_PROJECTION: dict[str, int] = {
    TypeSchemaKey.NAME.value: 1,
    TypeSchemaKey.SPECIAL_TYPE.value: 1,
    TypeSchemaKey.SYSTEM_TYPE.value: 1,
    '_id': 0,
}

# The system Types - the default person Types - which the configuration import replaces rather than refuses
SYSTEM_TYPES_CRITERIA: dict[str, bool] = {TypeSchemaKey.SYSTEM_TYPE.value: True}

# Logged when another process stored a default person Type first; formatted with the database name and the error
DEFAULT_TYPES_SEED_RACE_WARNING: str = (
    "Default person Types of database %s were seeded by another process meanwhile: %s"
)

# Refusal (HTTP 400) of an object delete whose persons / groups still own risk assessments. Formatted with the ids
# and the count
RISK_OWNER_OBJECT_DELETE_MESSAGE: str = (
    "The person / person group object(s) {ids} are the risk owner of {count} RiskAssessment(s) - assign another owner "
    "to them first!"
)

# Refusal (HTTP 400) when the owned risk assessments could not be counted. Formatted with the ids
RISK_OWNER_OBJECT_CHECK_FAILED_MESSAGE: str = "Failed to check whether the object(s) {ids} own a RiskAssessment!"
