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
Database update 20261125: the type ACLs become scope roles and assignments

The access engine decides from scope roles and assignments only. Every Type whose stored ``acl`` is activated is
translated (``access_engine.translate_type_acls``): groups holding the same operations on the same Types share one
role, assigned to each; a Type granting no existing group anything keeps a role without operations for the
administrator group, so it stays restricted; an entry of a group that no longer exists is dropped. A role name an
administrator already stored is never taken - the translation's numbering continues past it. The stored ``acl``
blocks are left as they are.

The migration checks itself before it writes: the engine on the translation must answer every Type and permission
as the stored ACLs do, for each existing group alone and for a user in no group (``access_engine.acl_differences``) -
otherwise it raises naming the Types and writes nothing. Then, in order:

    1. the report (``access.migrationReport``, ``_id`` ``type_acl_migration``) is written PENDING, carrying the
       planned role and assignment documents with their reserved public_ids
    2. each planned document is stored where no document holds its public_id yet, and logged
    3. the report is marked COMPLETE

Re-run safe: a run finding the report COMPLETE writes nothing; one finding it PENDING (a run stopped after step 1)
stores the missing planned documents - never a second translation - and completes it. A database without a Type whose
ACL is activated - a freshly built one included - has nothing to translate: nothing is written, no report, no
public_id drawn, so stamping a new database loses nothing. A configuration import's staging database holds no user
group: its activated ACLs become one role without operations for the administrator group
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.framework.access_engine import (
    acl_differences,
    acl_is_activated,
    assignment_documents,
    pending_report,
    role_documents,
    translate_type_acls,
)
from cmdb.models.access_model import (
    MIGRATION_REPORT_COLLECTION,
    TYPE_ACL_MIGRATION_REPORT_ID,
    MigrationReportKey,
    MigrationReportStatus,
)

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPES: str = 'framework.types'
GROUPS: str = 'management.groups'
ROLES: str = 'access.scopeRoles'
ASSIGNMENTS: str = 'access.assignments'
PUBLIC_ID: str = 'public_id'
NAME: str = 'name'
ACL: str = 'acl'
MONGO_ID: str = '_id'
ADMIN_GROUP_ID: int = 1

TRANSLATION_DIFFERS_MSG: str = (
    "The type ACL migration stopped before writing anything: the translated access rules would decide otherwise than "
    "the stored ACLs of Types {type_ids} - repair their acl and restart"
)

# ---------------------------------------------- Update20261125 - CLASS ---------------------------------------------- #

class Update20261125(BaseDatabaseUpdate):
    """
    Translates the stored type ACLs into scope roles and assignments, checked and reported

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261125


    def description(self) -> str:
        return "The type ACLs become scope roles and assignments"


    def start_update(self) -> None:
        """
        Plans and checks the translation (or reads the pending plan), stores it, completes the report, bumps the
        version

        Raises:
            UpdaterException: When the translation would decide otherwise than the ACLs, or a read or write fails
        """
        try:
            report: dict[str, Any] | None = self.read_report()

            if report is None:
                report = self.plan()

                if report is not None:
                    self.collection(MIGRATION_REPORT_COLLECTION).insert_one(
                        {MONGO_ID: TYPE_ACL_MIGRATION_REPORT_ID, **report})

            if report is not None and (report.get(MigrationReportKey.STATUS.value)
                                       != MigrationReportStatus.COMPLETE.value):
                self.store_planned(ROLES, report.get(MigrationReportKey.ROLES.value) or [])
                self.store_planned(ASSIGNMENTS, report.get(MigrationReportKey.ASSIGNMENTS.value) or [])
                self.complete_report()

            self.increase_updater_version(self.creation_date())
        except UpdaterException:
            raise
        except Exception as err:
            raise UpdaterException(err) from err


    def collection(self, name: str) -> Any:
        """
        A collection of the migrated database

        Args:
            name (str): The collection's name

        Returns:
            Any: The pymongo collection
        """
        return self.dbm.get_collection(name, self.db_name)


    def read_report(self) -> dict[str, Any] | None:
        """
        The stored report, without its ``_id``

        Returns:
            dict[str, Any] | None: The report; None when no run wrote one
        """
        return self.collection(MIGRATION_REPORT_COLLECTION).find_one(
            {MONGO_ID: TYPE_ACL_MIGRATION_REPORT_ID}, {MONGO_ID: 0})


    def plan(self) -> dict[str, Any] | None:
        """
        Translates the stored ACLs, reserves the public_ids and checks the translation decides alike

        Raises:
            UpdaterException: When it would decide otherwise on some Type - nothing is written

        Returns:
            dict[str, Any] | None: The pending report carrying the planned documents; None when no Type's ACL is
                activated - nothing to translate
        """
        type_documents: list[dict[str, Any]] = list(
            self.collection(TYPES).find({}, {MONGO_ID: 0, PUBLIC_ID: 1, ACL: 1}))

        if not any(acl_is_activated(document) for document in type_documents):
            LOGGER.info("[updater_20261125] No type ACL is activated - nothing to translate")
            return None
        group_ids: list[int] = [group[PUBLIC_ID] for group in self.collection(GROUPS).find({}, {PUBLIC_ID: 1})]
        taken_names: set[str] = {role[NAME] for role in self.collection(ROLES).find({}, {NAME: 1}) if NAME in role}
        roles = translate_type_acls(type_documents, group_ids, ADMIN_GROUP_ID, taken_names)
        role_count: int = len(roles)
        assignment_count: int = sum(len(role.group_ids) for role in roles)
        first_role_id: int = self.reserve(ROLES, role_count)
        first_assignment_id: int = self.reserve(ASSIGNMENTS, assignment_count)
        role_docs: list[dict[str, Any]] = role_documents(roles, first_role_id)
        assignment_docs: list[dict[str, Any]] = assignment_documents(roles, first_role_id, first_assignment_id)
        differing: list[int] = acl_differences(type_documents, group_ids, role_docs, assignment_docs)

        if differing:
            raise UpdaterException(TRANSLATION_DIFFERS_MSG.format(type_ids=differing))

        return pending_report(type_documents, group_ids, (role_docs, assignment_docs), datetime.now(timezone.utc))


    def reserve(self, collection: str, amount: int) -> int:
        """
        Reserves consecutive public_ids for the planned documents of a collection

        Args:
            collection (str): The collection
            amount (int): How many; none reserves nothing

        Returns:
            int: The first reserved id - unused when nothing was reserved
        """
        if not amount:
            return 1

        return self.dbm.reserve_public_ids(collection, self.db_name, amount)[0]


    def store_planned(self, collection: str, documents: list[dict[str, Any]]) -> None:
        """
        Stores each planned document no document holds the public_id of yet, logging what is written

        Args:
            collection (str): The collection
            documents (list[dict[str, Any]]): The planned documents
        """
        target: Any = self.collection(collection)

        for document in documents:
            result: Any = target.update_one({PUBLIC_ID: document[PUBLIC_ID]}, {'$setOnInsert': dict(document)},
                                            upsert=True)

            if result.upserted_id is not None:
                LOGGER.info("[updater_20261125] %s %s written: %s", collection, document[PUBLIC_ID], document)


    def complete_report(self) -> None:
        """
        Marks the report COMPLETE, with the time
        """
        self.collection(MIGRATION_REPORT_COLLECTION).update_one(
            {MONGO_ID: TYPE_ACL_MIGRATION_REPORT_ID},
            {'$set': {MigrationReportKey.STATUS.value: MigrationReportStatus.COMPLETE.value,
                      MigrationReportKey.COMPLETED_AT.value: datetime.now(timezone.utc)}},
        )
        LOGGER.info("[updater_20261125] The type ACLs are translated - report '%s' in %s",
                    TYPE_ACL_MIGRATION_REPORT_ID, MIGRATION_REPORT_COLLECTION)
