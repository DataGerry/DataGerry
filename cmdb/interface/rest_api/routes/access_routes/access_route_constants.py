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
Constants of the access rule routes: the rights they check, the request schemas, the searchable columns and the
messages
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.class_schema.write_schema_helper import build_update_schema, build_write_schema
from cmdb.models.access_model import (
    AccessAssignmentKey,
    CmdbAccessAssignment,
    CmdbFieldClass,
    CmdbScopeRole,
    FieldClassKey,
    ScopeRoleKey,
)
# -------------------------------------------------------------------------------------------------------------------- #


class AccessRightName(BaseStrEnum):
    """
    The rights the access rule routes check - every read asks VIEW, each kind's writes its own edit right; the
    assignment writes also admit ASSIGNMENT_DELEGATE (within the caller's own access)
    """
    VIEW = 'base.access.view'
    FIELD_CLASS_EDIT = 'base.access.fieldclass.edit'
    SCOPE_ROLE_EDIT = 'base.access.scoperole.edit'
    ASSIGNMENT_EDIT = 'base.access.assignment.edit'
    ASSIGNMENT_DELEGATE = 'base.access.assignment.delegate'


# The request bodies: a create sends the whole document but its public_id, an update what it changes - the stored
# document fills what an update leaves out
FIELD_CLASS_CREATE_SCHEMA: dict[str, Any] = build_write_schema(CmdbFieldClass.SCHEMA)
FIELD_CLASS_UPDATE_SCHEMA: dict[str, Any] = build_update_schema(CmdbFieldClass.SCHEMA, all_optional=True)
SCOPE_ROLE_CREATE_SCHEMA: dict[str, Any] = build_write_schema(CmdbScopeRole.SCHEMA)
SCOPE_ROLE_UPDATE_SCHEMA: dict[str, Any] = build_update_schema(CmdbScopeRole.SCHEMA, all_optional=True)
ASSIGNMENT_CREATE_SCHEMA: dict[str, Any] = build_write_schema(CmdbAccessAssignment.SCHEMA)
# The dry run of a scope (POST /access/assignments/check): the role and the scope, both required
ASSIGNMENT_CHECK_SCHEMA: dict[str, Any] = {key: ASSIGNMENT_CREATE_SCHEMA[key] for key in (
    AccessAssignmentKey.ROLE_ID.value, AccessAssignmentKey.SCOPE.value)}
ASSIGNMENT_UPDATE_SCHEMA: dict[str, Any] = build_update_schema(CmdbAccessAssignment.SCHEMA, all_optional=True)
# The simulation of an assignment (POST /access/assignments/simulate, phase 11): group, role and scope required, and
# the stored assignment a change is simulated against
SIMULATION_ASSIGNMENT_ID: str = 'assignment_id'
ASSIGNMENT_SIMULATE_SCHEMA: dict[str, Any] = {
    **{key: ASSIGNMENT_CREATE_SCHEMA[key] for key in (AccessAssignmentKey.GROUP_ID.value,
                                                      AccessAssignmentKey.ROLE_ID.value,
                                                      AccessAssignmentKey.SCOPE.value)},
    SIMULATION_ASSIGNMENT_ID: {**ASSIGNMENT_CREATE_SCHEMA[AccessAssignmentKey.GROUP_ID.value], 'required': False},
}

# The columns each list's search box looks in
FIELD_CLASS_SEARCHABLE_FIELDS: tuple[str, ...] = (
    FieldClassKey.PUBLIC_ID.value, FieldClassKey.NAME.value, FieldClassKey.LABEL.value,
)
SCOPE_ROLE_SEARCHABLE_FIELDS: tuple[str, ...] = (ScopeRoleKey.PUBLIC_ID.value, ScopeRoleKey.NAME.value)
ASSIGNMENT_SEARCHABLE_FIELDS: tuple[str, ...] = (
    AccessAssignmentKey.PUBLIC_ID.value, AccessAssignmentKey.DESCRIPTION.value,
)

class AccessUsageKey(BaseStrEnum):
    """
    The keys of a usage answer: what holds the document and keeps it from being deleted
    """
    SCOPE_ROLES = 'scope_roles'
    ASSIGNMENTS = 'assignments'
    LOCKED_TYPE_IDS = 'locked_type_ids'
    OPENED_TYPE_IDS = 'opened_type_ids'


class TypeAssignmentsKey(BaseStrEnum):
    """
    The keys of ``GET /access/types/<id>/assignments``: the Type and the assignments whose role covers it, each with
    its role
    """
    TYPE_ID = 'type_id'
    ASSIGNMENTS = 'assignments'
    ROLE = 'role'


# What a Type is called in the 404 of the routes about one Type
TYPE_LABEL: str = 'Type'

# The query flag confirming a change that opens Types to every user group
UNRESTRICT_PARAM: str = 'unrestrict'

# The scope role list's flag answering only the roles the caller may hand out
WITHIN_REACH_PARAM: str = 'within_reach'

# The key of the migration report answer holding the access rights migration's report
MIGRATION_RIGHTS_KEY: str = 'rights'


class AccessRouteMessage(BaseStrEnum):
    """
    The access rule routes' messages - format strings where they carry a placeholder
    """
    NOT_FOUND = "{label} {public_id} does not exist!"
    NO_MIGRATION_REPORT = "No access migration ran on this database - there is no migration report!"
