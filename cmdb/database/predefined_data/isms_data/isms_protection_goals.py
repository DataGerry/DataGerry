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
This module provides the predefined IsmsProtectionGoals
"""
from typing import Any

from cmdb.database.predefined_data.predefined_data_constants import ProtectionGoalKey
# -------------------------------------------------------------------------------------------------------------------- #

def get_default_protection_goals() -> list[dict[str, Any]]:
    """
    Returns the default IsmsProtectionGoals (Confidentiality, Integrity, Availability), inserted at setup

    Returns:
        list[dict[str, Any]]: The default IsmsProtectionGoals as documents
    """
    return [
        {
            ProtectionGoalKey.PUBLIC_ID: 1,
            ProtectionGoalKey.NAME: 'Confidentiality',
            ProtectionGoalKey.PREDEFINED: True,
        },
        {
            ProtectionGoalKey.PUBLIC_ID: 2,
            ProtectionGoalKey.NAME: 'Integrity',
            ProtectionGoalKey.PREDEFINED: True,
        },
        {
            ProtectionGoalKey.PUBLIC_ID: 3,
            ProtectionGoalKey.NAME: 'Availability',
            ProtectionGoalKey.PREDEFINED: True,
        }
    ]
