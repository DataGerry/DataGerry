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
The permission data model: field classes, scope roles and assignments - which user group may perform which
operation and write which field class on which objects - and the history of their changes
"""
from .scope_operation_enum import ScopeOperation
from .access_constants import (
    FieldClassKey,
    FieldRuleKey,
    MAX_RULE_SET_FIELDS,
    ScopeRoleKey,
    AccessAssignmentKey,
    SYSTEM_FIELD_CLASS,
    FIELD_CLASS_NAME_PATTERN,
    ALL_TYPES,
    UNCONDITIONAL_SCOPE,
    ASSIGNMENT_GROUP_INDEX_NAME,
    ASSIGNMENT_ROLE_INDEX_NAME,
    ASSIGNMENT_UNIQUE_INDEX_NAME,
    NAME_MAX_LENGTH,
    LABEL_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    MAX_ROLE_TYPES,
    MAX_ROLE_FIELD_CLASSES,
    RESERVED_FIELD_CLASS_MSG,
    NOT_BLANK_MSG,
    VALUES_NOT_UNIQUE_MSG,
    ROLE_TYPES_SHAPE_MSG,
    ROLE_TYPES_TOO_MANY_MSG,
    SCOPE_SHAPE_MSG,
)
from .migration_report_constants import (
    MIGRATION_REPORT_COLLECTION,
    TYPE_ACL_MIGRATION_REPORT_ID,
    ACCESS_RIGHTS_MIGRATION_REPORT_ID,
    MigrationReportStatus,
    MigrationReportKey,
    MigrationReportTypeKey,
    RightsMigrationReportKey,
)
from .cmdb_field_class import CmdbFieldClass
from .cmdb_scope_role import CmdbScopeRole
from .cmdb_access_assignment import CmdbAccessAssignment
from .cmdb_field_rule import CmdbFieldRule
from .access_history_constants import (
    AccessHistoryKey,
    HistoryAction,
    HistoryKind,
    HistorySource,
    MAX_HISTORY_COMMENT_LENGTH,
    HISTORY_TTL_INDEX_NAME,
    HISTORY_COMMENT_KEY,
    HISTORY_SETTINGS_SECTION,
    MAX_RETENTION_DAYS,
    HistorySettingsKey,
)
from .cmdb_access_history import CmdbAccessHistory
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AccessHistoryKey',
    'HistoryAction',
    'HistoryKind',
    'HistorySource',
    'MAX_HISTORY_COMMENT_LENGTH',
    'HISTORY_TTL_INDEX_NAME',
    'HISTORY_COMMENT_KEY',
    'HISTORY_SETTINGS_SECTION',
    'MAX_RETENTION_DAYS',
    'HistorySettingsKey',
    'CmdbAccessHistory',
    'ScopeOperation',
    'CmdbFieldClass',
    'CmdbFieldRule',
    'FieldRuleKey',
    'MAX_RULE_SET_FIELDS',
    'CmdbScopeRole',
    'CmdbAccessAssignment',
    'FieldClassKey',
    'ScopeRoleKey',
    'AccessAssignmentKey',
    'SYSTEM_FIELD_CLASS',
    'FIELD_CLASS_NAME_PATTERN',
    'ALL_TYPES',
    'UNCONDITIONAL_SCOPE',
    'ASSIGNMENT_GROUP_INDEX_NAME',
    'ASSIGNMENT_ROLE_INDEX_NAME',
    'ASSIGNMENT_UNIQUE_INDEX_NAME',
    'NAME_MAX_LENGTH',
    'LABEL_MAX_LENGTH',
    'DESCRIPTION_MAX_LENGTH',
    'MAX_ROLE_TYPES',
    'MAX_ROLE_FIELD_CLASSES',
    'RESERVED_FIELD_CLASS_MSG',
    'NOT_BLANK_MSG',
    'VALUES_NOT_UNIQUE_MSG',
    'ROLE_TYPES_SHAPE_MSG',
    'ROLE_TYPES_TOO_MANY_MSG',
    'SCOPE_SHAPE_MSG',
    'MIGRATION_REPORT_COLLECTION',
    'TYPE_ACL_MIGRATION_REPORT_ID',
    'MigrationReportStatus',
    'MigrationReportKey',
    'MigrationReportTypeKey',
    'ACCESS_RIGHTS_MIGRATION_REPORT_ID',
    'RightsMigrationReportKey',
]
