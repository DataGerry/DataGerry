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
from cmdb.framework.access_rules.field_protection_view import FieldProtectionKey, FieldSource
from cmdb.models.access_model import (
    HISTORY_COMMENT_KEY,
    MAX_HISTORY_COMMENT_LENGTH,
    AccessAssignmentKey,
    AccessHistoryKey,
    HistorySettingsKey,
    MAX_RETENTION_DAYS,
    CmdbAccessAssignment,
    CmdbFieldClass,
    CmdbFieldRule,
    CmdbScopeRole,
    FieldClassKey,
    FieldRuleKey,
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
    FIELD_EDIT = 'base.access.field.edit'
    FIELD_RULE_EDIT = 'base.access.fieldrule.edit'
    HISTORY_EXPORT = 'base.access.history.export'
    SCOPE_ROLE_EDIT = 'base.access.scoperole.edit'
    ASSIGNMENT_EDIT = 'base.access.assignment.edit'
    ASSIGNMENT_DELEGATE = 'base.access.assignment.delegate'


# The searchable columns of the access history, and its settings' update body
HISTORY_SEARCHABLE_FIELDS: tuple[str, ...] = (
    AccessHistoryKey.PUBLIC_ID.value, AccessHistoryKey.USER_NAME.value, AccessHistoryKey.COMMENT.value,
)
# The comment a write may leave in the access change history - never stored on the document
HISTORY_COMMENT_RULE: dict[str, dict[str, Any]] = {
    HISTORY_COMMENT_KEY: {'type': 'string', 'required': False, 'nullable': True,
                          'maxlength': MAX_HISTORY_COMMENT_LENGTH},
}
HISTORY_SETTINGS_SCHEMA: dict[str, Any] = {
    HistorySettingsKey.RETENTION_DAYS.value: {'type': 'integer', 'required': True, 'min': 0,
                                              'max': MAX_RETENTION_DAYS},
    **HISTORY_COMMENT_RULE,
}
# The request bodies: a create sends the whole document but its public_id, an update what it changes - the stored
# document fills what an update leaves out
FIELD_CLASS_CREATE_SCHEMA: dict[str, Any] = {**build_write_schema(CmdbFieldClass.SCHEMA), **HISTORY_COMMENT_RULE}
FIELD_CLASS_UPDATE_SCHEMA: dict[str, Any] = {
    **build_update_schema(CmdbFieldClass.SCHEMA, all_optional=True),
    **HISTORY_COMMENT_RULE,
}
SCOPE_ROLE_CREATE_SCHEMA: dict[str, Any] = {**build_write_schema(CmdbScopeRole.SCHEMA), **HISTORY_COMMENT_RULE}
SCOPE_ROLE_UPDATE_SCHEMA: dict[str, Any] = {
    **build_update_schema(CmdbScopeRole.SCHEMA, all_optional=True),
    **HISTORY_COMMENT_RULE,
}
ASSIGNMENT_CREATE_SCHEMA: dict[str, Any] = {**build_write_schema(CmdbAccessAssignment.SCHEMA), **HISTORY_COMMENT_RULE}
# The dry run of a scope (POST /access/assignments/check): the role and the scope, both required
ASSIGNMENT_CHECK_SCHEMA: dict[str, Any] = {key: ASSIGNMENT_CREATE_SCHEMA[key] for key in (
    AccessAssignmentKey.ROLE_ID.value, AccessAssignmentKey.SCOPE.value)}
ASSIGNMENT_UPDATE_SCHEMA: dict[str, Any] = {
    **build_update_schema(CmdbAccessAssignment.SCHEMA, all_optional=True),
    **HISTORY_COMMENT_RULE,
}
FIELD_RULE_CREATE_SCHEMA: dict[str, Any] = {**build_write_schema(CmdbFieldRule.SCHEMA), **HISTORY_COMMENT_RULE}
FIELD_RULE_UPDATE_SCHEMA: dict[str, Any] = {
    **build_update_schema(CmdbFieldRule.SCHEMA, all_optional=True),
    **HISTORY_COMMENT_RULE,
}
# The check of a rule before it is stored: the rule, and the stored rule an edit is checked as (left out of the overlap)
FIELD_RULE_CHECK_SCHEMA: dict[str, Any] = {
    **FIELD_RULE_CREATE_SCHEMA,
    FieldRuleKey.PUBLIC_ID.value: {'type': 'integer', 'required': False, 'min': 1},
}
# The Field Rules list narrowed to the rules a user group's own changes can trigger
FIELD_RULE_QUERY_GROUP_ID: str = 'group_id'
# The explanation of one user's access to one object: its two query parameters
EXPLAIN_QUERY_USER_ID: str = 'user_id'
EXPLAIN_QUERY_OBJECT_ID: str = 'object_id'
# The Field Protection routes (phase 12): the list's query parameters, the update and the pattern test bodies
FIELD_PROTECTION_QUERY_TYPE_ID: str = 'type_id'
FIELD_PROTECTION_QUERY_GROUP_ID: str = 'group_id'
MAX_PATTERN_SAMPLES: int = 50
MAX_PATTERN_SAMPLE_LENGTH: int = 1000


class PatternTestBodyKey(BaseStrEnum):
    """The keys of a pattern test body"""
    REGEX = 'regex'
    SAMPLES = 'samples'


FIELD_PROTECTION_UPDATE_SCHEMA: dict[str, Any] = {
    FieldProtectionKey.SOURCE.value: {'type': 'string', 'required': True,
                                      'allowed': [source.value for source in FieldSource]},
    FieldProtectionKey.SOURCE_ID.value: {'type': 'integer', 'required': True, 'min': 1},
    FieldProtectionKey.NAME.value: {'type': 'string', 'required': True, 'empty': False},
    FieldProtectionKey.PROTECTION.value: {'type': 'string', 'required': False, 'nullable': True, 'empty': False},
    FieldProtectionKey.AUDIT_RELEVANT.value: {'type': 'boolean', 'required': False},
    FieldProtectionKey.REQUIRED.value: {'type': 'boolean', 'required': False},
    FieldProtectionKey.REGEX.value: {'type': 'string', 'required': False, 'nullable': True},
    **HISTORY_COMMENT_RULE,
}
FIELD_PROTECTION_PATTERN_TEST_SCHEMA: dict[str, Any] = {
    PatternTestBodyKey.REGEX.value: {'type': 'string', 'required': True, 'empty': False},
    PatternTestBodyKey.SAMPLES.value: {'type': 'list', 'required': True, 'maxlength': MAX_PATTERN_SAMPLES,
                                       'schema': {'type': 'string', 'maxlength': MAX_PATTERN_SAMPLE_LENGTH}},
}
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
FIELD_RULE_SEARCHABLE_FIELDS: tuple[str, ...] = (
    FieldRuleKey.PUBLIC_ID.value, FieldRuleKey.NAME.value, FieldRuleKey.DESCRIPTION.value,
)
SCOPE_ROLE_SEARCHABLE_FIELDS: tuple[str, ...] = (ScopeRoleKey.PUBLIC_ID.value, ScopeRoleKey.NAME.value)
ASSIGNMENT_SEARCHABLE_FIELDS: tuple[str, ...] = (
    AccessAssignmentKey.PUBLIC_ID.value, AccessAssignmentKey.DESCRIPTION.value,
)

class FieldRuleCheckKey(BaseStrEnum):
    """
    The keys of a Field Rule check (``POST /access/field_rules/check``): the rule as it would be stored, and what it
    reaches - per Type its object count, and the total
    """
    RULE = 'rule'
    TYPES = 'types'
    TYPE_ID = 'type_id'
    OBJECTS = 'objects'


class AccessUsageKey(BaseStrEnum):
    """
    The keys of a usage answer: what holds the document and keeps it from being deleted
    """
    SCOPE_ROLES = 'scope_roles'
    FIELDS = 'fields'
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
    EXPLAIN_PARAMETERS = "An explanation needs the user_id and the object_id - both whole numbers from 1!"
