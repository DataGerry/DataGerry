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
Validation schema for IsmsThreat

An IsmsThreat is a threat catalogue entry in the ISMS (collection ``isms.threat``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsThreat.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_threat_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsThreat document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsThreat.SCHEMA
    """
    return {
        'public_id': {  # public_id of the IsmsThreat
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the threat
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'source': {  # public_id of the source the threat originates from (e.g. a catalogue)
            'type': 'integer',
            'nullable': True,
        },
        'identifier': {  # External identifier / catalogue number of the threat
            'type': 'string',
            'nullable': True,
        },
        'description': {  # Description of the threat
            'type': 'string',
            'nullable': True,
        },
    }
