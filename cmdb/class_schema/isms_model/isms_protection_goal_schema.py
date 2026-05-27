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
The schema of an IsmsProtectionGoal
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_protection_goal_schema() -> dict[str, Any]:
    """
    Returns the IsmsProtectionGoalSchema

    Returns:
        dict: Schema of the IsmsProtectionGoal
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
