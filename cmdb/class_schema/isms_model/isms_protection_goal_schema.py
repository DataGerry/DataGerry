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
Validation schema for IsmsProtectionGoal

An IsmsProtectionGoal is a protection goal such as Confidentiality, Integrity or Availability
(collection ``isms.protectionGoal``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsProtectionGoal.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_protection_goal_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsProtectionGoal document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsProtectionGoal.SCHEMA
    """
    # Imported inside the builder: the model imports this schema, so a module-level import of the
    # model's constants would close a cycle (see the class_schema convention)
    # pylint: disable=import-outside-toplevel
    from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey

    return {
        ProtectionGoalKey.PUBLIC_ID.value: {  # public_id of the IsmsProtectionGoal
            'type': 'integer',
            'min': 1,
        },
        # Name of the protection goal (e.g. Confidentiality, Integrity, Availability)
        ProtectionGoalKey.NAME.value: {
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ProtectionGoalKey.PREDEFINED.value: {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'required': True,
            'empty': False,
        },
    }
