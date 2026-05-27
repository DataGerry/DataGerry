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
The schema of an IsmsRiskClass
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_risk_class_schema() -> dict[str, Any]:
    """
    Returns the IsmsRiskClassSchema

    Returns:
        dict: Schema of the IsmsRiskClass
    """
    return {
        'public_id': {  # public_id of the IsmsRiskClass
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the risk class (e.g. Low / Medium / High)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'description': {  # Optional description of the risk class
            'type': 'string',
        },
        'color': {  # Display colour of the risk class (hex / css value)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'sort': {  # Sort order of the risk class
            'type': 'integer',
        },
    }
