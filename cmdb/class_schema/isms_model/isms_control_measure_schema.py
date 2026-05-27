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
The schema of an IsmsControlMeasure
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_control_measure_schema() -> dict[str, Any]:
    """
    Returns the IsmsControlMeasureSchema

    Returns:
        dict: Schema of the IsmsControlMeasure
    """
    return {
        'public_id': {  # public_id of the IsmsControlMeasure
            'type': 'integer',
            'min': 1,
        },
        'title': {  # Title of the control measure
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'control_measure_type': {  # CONTROL / REQUIREMENT / MEASURE (a ControlMeasureType value)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'source': {  # public_id of the source the control originates from (e.g. a framework / standard)
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'implementation_state': {  # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'identifier': {  # External identifier / catalogue number of the control
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'chapter': {  # Chapter / section reference within the source framework
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'description': {  # Description of the control measure
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'is_applicable': {  # Whether the control is applicable (Statement of Applicability)
            'type': 'boolean',
            'required': True,
            'nullable': True,
        },
        'reason': {  # Justification for applicability or exclusion
            'type': 'string',
            'required': True,
            'nullable': True,
        },
    }
