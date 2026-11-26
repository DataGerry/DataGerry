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
Database update 20261127: the user groups that could set a type ACL may view the access rules

Before the access rules, a holder of ``base.framework.type.edit`` set a Type's ACL in the type builder. That ACL decides
nothing any more, and access is managed under the access rules, which need ``base.access.*``. Such a group - holding
``base.framework.type.edit``, ``base.framework.type.*`` or ``base.framework.*`` - is given ``base.access.view`` only:
the edit rights reach every Type and every group, more than the old per-Type ACL did, so an administrator grants them
deliberately. A group holding ``base.*``, ``base.access.*`` or the view right already is left alone.

Each group given the right is recorded in the access rights migration report (``access.migrationReport``, ``_id``
``access_rights_migration``) BEFORE the right is written, so the report never misses a granted group.

Re-run safe: a group given the right is no longer selected; a run stopped between the report and the grant selects the
same groups again and records the same entries (``$addToSet``). A database where no group qualifies - a fresh one
included - gets no report, only the version stamp
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Iterable

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
GROUPS: str = 'management.groups'
REPORTS: str = 'access.migrationReport'
REPORT_ID: str = 'access_rights_migration'
MONGO_ID: str = '_id'
PUBLIC_ID: str = 'public_id'
RIGHTS: str = 'rights'

# A group holding one of these could set a type ACL
TYPE_ACL_EDITOR_RIGHTS: tuple[str, ...] = ('base.framework.type.edit', 'base.framework.type.*', 'base.framework.*')
# A group holding one of these may view the access rules already
ACCESS_VIEW_HOLDING_RIGHTS: tuple[str, ...] = ('base.*', 'base.access.*', 'base.access.view')
GRANTED_RIGHTS: list[str] = ['base.access.view']

# The report's keys
REPORT_GROUPS: str = 'groups'
REPORT_GROUP_ID: str = 'group_id'
REPORT_GRANTED: str = 'granted'
REPORT_STARTED_AT: str = 'started_at'
REPORT_COMPLETED_AT: str = 'completed_at'


def qualifies(rights: Any) -> bool:
    """
    Whether a group's stored rights could set a type ACL and do not let it view the access rules yet

    Args:
        rights (Any): The group's stored ``rights`` - a list of right names; anything else qualifies for nothing

    Returns:
        bool: True when the group is to be given ``base.access.view``
    """
    if not isinstance(rights, list):
        return False

    held: set[str] = {right for right in rights if isinstance(right, str)}

    return bool(held.intersection(TYPE_ACL_EDITOR_RIGHTS)) and not held.intersection(ACCESS_VIEW_HOLDING_RIGHTS)


def qualifying_group_ids(groups: Iterable[dict[str, Any]]) -> list[int]:
    """
    The groups to be given ``base.access.view``

    Args:
        groups (Iterable[dict[str, Any]]): The stored groups, each with ``public_id`` and ``rights``

    Returns:
        list[int]: Their public_ids, ascending
    """
    return sorted(group[PUBLIC_ID] for group in groups if qualifies(group.get(RIGHTS)))


# --------------------------------------------- Update20261127 - CLASS ---------------------------------------------- #

class Update20261127(BaseDatabaseUpdate):
    """
    Gives the user groups that could set a type ACL the right to view the access rules

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261127


    def description(self) -> str:
        return "The user groups that could set a type ACL may view the access rules"


    def start_update(self) -> None:
        """
        Records the qualifying groups in the report, gives them the right, completes the report, bumps the version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            groups: Any = self.dbm.get_collection(GROUPS, self.db_name)
            group_ids: list[int] = qualifying_group_ids(
                groups.find({RIGHTS: {'$in': list(TYPE_ACL_EDITOR_RIGHTS)}}, {MONGO_ID: 0, PUBLIC_ID: 1, RIGHTS: 1})
            )

            if group_ids:
                self.record(group_ids)
                groups.update_many({PUBLIC_ID: {'$in': group_ids}},
                                   {'$addToSet': {RIGHTS: {'$each': GRANTED_RIGHTS}}})
                self.dbm.get_collection(REPORTS, self.db_name).update_one(
                    {MONGO_ID: REPORT_ID}, {'$set': {REPORT_COMPLETED_AT: datetime.now(timezone.utc)}})
                LOGGER.info("[updater_20261127] %s given to the user groups %s", GRANTED_RIGHTS, group_ids)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def record(self, group_ids: list[int]) -> None:
        """
        Records the groups about to be given the right in the report, before the right is written

        Args:
            group_ids (list[int]): The qualifying groups
        """
        entries: list[dict[str, Any]] = [{REPORT_GROUP_ID: group_id, REPORT_GRANTED: list(GRANTED_RIGHTS)}
                                         for group_id in group_ids]
        self.dbm.get_collection(REPORTS, self.db_name).update_one(
            {MONGO_ID: REPORT_ID},
            {'$setOnInsert': {REPORT_STARTED_AT: datetime.now(timezone.utc)},
             '$addToSet': {REPORT_GROUPS: {'$each': entries}}},
            upsert=True,
        )
