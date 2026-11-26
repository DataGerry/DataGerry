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
Constants of the access migration reports: the type ACL migration's (how the stored type ACLs became scope roles and
assignments) and the access rights migration's (which user groups were given which access rule right)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The collection holding the reports, and each report's ``_id`` - one of each at most
MIGRATION_REPORT_COLLECTION: str = 'access.migrationReport'
TYPE_ACL_MIGRATION_REPORT_ID: str = 'type_acl_migration'
ACCESS_RIGHTS_MIGRATION_REPORT_ID: str = 'access_rights_migration'


class MigrationReportStatus(BaseStrEnum):
    """
    How far the migration got

    Values:
        PENDING: Translated and checked; the planned roles and assignments may not all be stored yet
        COMPLETE: Every planned role and assignment is stored
    """
    PENDING = 'pending'
    COMPLETE = 'complete'


class MigrationReportKey(BaseStrEnum):
    """
    Keys of the report document

    Attributes:
        STATUS: A ``MigrationReportStatus`` value
        STARTED_AT: When the translation was checked and the report written (UTC)
        COMPLETED_AT: When the last planned document was stored (UTC); absent while pending
        EXISTING_GROUP_IDS: The user groups that existed - an ACL entry of another group was dropped
        TYPES: One ``MigrationReportTypeKey`` entry per Type whose ACL was activated, ascending by Type
        INACTIVE_TYPE_IDS: The Types whose ACL was absent or not activated - unrestricted before and after
        ROLES: The scope role documents made, as stored
        ASSIGNMENTS: The assignment documents made, as stored
    """
    STATUS = 'status'
    STARTED_AT = 'started_at'
    COMPLETED_AT = 'completed_at'
    EXISTING_GROUP_IDS = 'existing_group_ids'
    TYPES = 'types'
    INACTIVE_TYPE_IDS = 'inactive_type_ids'
    ROLES = 'roles'
    ASSIGNMENTS = 'assignments'


class MigrationReportTypeKey(BaseStrEnum):
    """
    Keys of one Type's entry in the report

    Attributes:
        TYPE_ID: The Type's public_id
        ACL: Its stored ``acl`` block, as it was read
        ROLE_IDS: The roles naming it
        ASSIGNMENT_IDS: The assignments of those roles
        DROPPED_GROUP_IDS: The groups its ACL named that did not exist - their entries were dropped
    """
    TYPE_ID = 'type_id'
    ACL = 'acl'
    ROLE_IDS = 'role_ids'
    ASSIGNMENT_IDS = 'assignment_ids'
    DROPPED_GROUP_IDS = 'dropped_group_ids'


class RightsMigrationReportKey(BaseStrEnum):
    """
    Keys of the access rights migration report (``updater_20261127``), answered under ``rights`` of the migration
    report route

    Attributes:
        STARTED_AT: When the first group was recorded (UTC)
        COMPLETED_AT: When the rights were written (UTC); absent when the run stopped before
        GROUPS: One entry per user group given rights: ``{group_id, granted}`` - the rights granted
    """
    STARTED_AT = 'started_at'
    COMPLETED_AT = 'completed_at'
    GROUPS = 'groups'
