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
Validation schema for CmdbAccessAssignment

A CmdbAccessAssignment grants a user group a scope role within a scope (collection ``access.assignments``). The
scope is only the unconditional ``*`` - every object of the role's Types - until the scope compiler brings the
conditions; the same group, role and scope are stored once.

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbAccessAssignment.SCHEMA.
"""
from typing import Any

from cmdb.class_schema.id_schema_helper import get_id_rule
from cmdb.class_schema.access_model.access_schema_helper import check_unconditional_scope, get_description_rule
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_access_assignment_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbAccessAssignment document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbAccessAssignment.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.access_model.access_constants import AccessAssignmentKey

    return {
        AccessAssignmentKey.PUBLIC_ID.value: {  # public_id of the CmdbAccessAssignment
            'type': 'integer',
            'min': 1,
        },
        AccessAssignmentKey.GROUP_ID.value: get_id_rule(),  # public_id of the CmdbUserGroup it grants to
        AccessAssignmentKey.ROLE_ID.value: get_id_rule(),  # public_id of the CmdbScopeRole it grants
        AccessAssignmentKey.SCOPE.value: {  # The objects it applies to - only '*' (every object) for now
            'required': True,
            'check_with': check_unconditional_scope,
        },
        AccessAssignmentKey.DESCRIPTION.value: get_description_rule(),  # What the assignment is for
    }
