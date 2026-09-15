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

This module is the single source of the document's Cerberus validation schema, consumed as
IsmsRisk.SCHEMA. Two things it deliberately does or does not express:

  - ``risk_type`` is pinned to the RiskType values here, which makes validation - not the route - the
    place an unknown type is refused. The insert and update routes used to re-check it with
    ``RiskType.is_valid`` after this schema had already passed anything
  - which fields a given risk_type actually uses (threats / vulnerabilities / consequences) is NOT
    expressed: it is a cross-field rule, checked by the frontend and by the CSV importer's
    ``risk_row_is_valid``

The three text fields are ``nullable``, because that is what the model produces: an unset identifier,
consequences or description round-trips as null, and the frontend patches that null straight back into
the form it later saves - which this schema used to answer with 'null value not allowed'
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
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.isms_risk_constants import RiskKey
    from cmdb.models.isms_model.risk_type_enum import RiskType

    return {
        RiskKey.PUBLIC_ID.value: {  # public_id of the IsmsRisk
            'type': 'integer',
            'min': 1,
        },
        RiskKey.NAME.value: {  # Name of the risk
            'type': 'string',
            'required': True,
            'empty': False,
        },
        RiskKey.RISK_TYPE.value: {  # Decides which of the fields below the risk uses
            'type': 'string',
            'required': True,
            'empty': False,
            'allowed': [risk_type.value for risk_type in RiskType],
        },
        RiskKey.PROTECTION_GOALS.value: {  # public_ids of the affected IsmsProtectionGoals
            'type': 'list',
        },
        RiskKey.THREATS.value: {  # public_ids of the associated IsmsThreats
            'type': 'list',
        },
        RiskKey.CATEGORY_ID.value: {  # public_id of the CmdbExtendableOption holding the risk's category
            'type': 'integer',
            'required': True,
            'nullable': True,
            'empty': False,
        },
        RiskKey.VULNERABILITIES.value: {  # public_ids of the associated IsmsVulnerabilities
            'type': 'list',
        },
        RiskKey.IDENTIFIER.value: {  # External identifier of the risk. Null when unset - see above
            'type': 'string',
            'nullable': True,
        },
        RiskKey.CONSEQUENCES.value: {  # Consequences of the risk, used by an EVENT risk
            'type': 'string',
            'nullable': True,
        },
        RiskKey.DESCRIPTION.value: {  # Description of the risk
            'type': 'string',
            'nullable': True,
        },
    }
