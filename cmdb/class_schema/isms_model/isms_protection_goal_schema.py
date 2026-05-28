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
    return {
        'public_id': {  # public_id of the IsmsProtectionGoal
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the protection goal (e.g. Confidentiality, Integrity, Availability)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'predefined': {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'required': True,
            'empty': False,
        },
    }
