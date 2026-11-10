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
    place an unknown type is refused, rather than the insert and update routes re-checking it with
    ``RiskType.is_valid`` after this schema had already passed anything
  - which fields a given risk_type actually uses (threats / vulnerabilities / consequences) is NOT
    expressed: it is a cross-field rule, checked by the frontend and by the CSV importer's
    ``risk_row_is_valid``

The three text fields are ``nullable``, because that is what the model produces: an unset identifier,
consequences or description round-trips as null, and the frontend patches that null straight back into
the form it later saves, so this schema must not answer it with 'null value not allowed'

Every item of ``threats``, ``vulnerabilities`` and ``protection_goals``, the Risk's own ``public_id`` and its
``category_id`` are held to the shared ``get_id_rule`` (a whole number from 1, never a boolean; the category may be
null). That each list item names a stored document, once, is the write routes' check
(``isms_id_reference_helper.guard_risk_references``), and so is that the category is an option of the RISK list
(``isms_routes_helper.abort_on_unknown_options``)
"""
from typing import Any

from cmdb.class_schema.id_schema_helper import get_id_rule
# -------------------------------------------------------------------------------------------------------------------- #
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
        # public_id of the IsmsRisk
        RiskKey.PUBLIC_ID.value: get_id_rule(required=False),
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
            'schema': get_id_rule(required=False),
        },
        RiskKey.THREATS.value: {  # public_ids of the associated IsmsThreats
            'type': 'list',
            'schema': get_id_rule(required=False),
        },
        # public_id of the CmdbExtendableOption (RISK list) holding the risk's category
        RiskKey.CATEGORY_ID.value: get_id_rule(nullable=True),
        RiskKey.VULNERABILITIES.value: {  # public_ids of the associated IsmsVulnerabilities
            'type': 'list',
            'schema': get_id_rule(required=False),
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
