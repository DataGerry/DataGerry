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
Validation schema for IsmsRisk

An IsmsRisk describes a risk through its threats, vulnerabilities and protection goals
(collection ``isms.risk``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsRisk.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_risk_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsRisk document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsRisk.SCHEMA
    """
    return {
        'public_id': {  # public_id of the IsmsRisk
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the risk
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'risk_type': {  # THREAT_X_VULNERABILITY / THREAT / EVENT (a RiskType value)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'protection_goals': {  # public_ids of the affected IsmsProtectionGoals
            'type': 'list',
        },
        'threats': {  # public_ids of the associated IsmsThreats
            'type': 'list',
        },
        'category_id': {  # public_id of the risk's category
            'type': 'integer',
            'required': True,
            'nullable': True,
            'empty': False,
        },
        'vulnerabilities': {  # public_ids of the associated IsmsVulnerabilities
            'type': 'list',
        },
        'identifier': {  # External identifier of the risk
            'type': 'string',
        },
        'consequences': {  # Description of the risk's consequences
            'type': 'string',
        },
        'description': {  # Description of the risk
            'type': 'string',
        },
    }
