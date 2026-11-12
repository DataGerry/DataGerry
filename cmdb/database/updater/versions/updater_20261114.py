# DATAGERRY - OpenSource Enterprise CMDB
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
Database update 20261114: drop the two log indexes their longer successors replace

``framework.logs`` declared ``object_id_log_time`` = ``(object_id, log_time)`` and ``log_type_action`` =
``(log_type, action)``. Every list sort now ends on ``public_id`` (the query builder's tie-break), and the date-ordered
pages of the delete-log list and of the exists / notexists split filter on ``action``, so neither index could hand a
page out in order any more: ``log_type_action`` never could, it sorted every matching log in memory. Their successors
``object_id_log_time_public_id`` and ``log_type_action_log_time_public_id`` carry the same leading keys plus the order
a page asks for, so they serve every query the predecessors served and the sort as well.

The startup index reconciliation only adds a declared index whose NAME is missing; it never drops one. The
successors therefore carry new names and are added by the reconciliation, and this update drops the predecessors,
which would otherwise stay behind as two more indexes every log insert pays for.

Re-run safe: a second run finds neither index and drops nothing. A database that never had them (a new install) is
the same no-op
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
LOGS_COLLECTION: str = 'framework.logs'
REPLACED_INDEXES: tuple[str, ...] = ('object_id_log_time', 'log_type_action')

# ---------------------------------------------- Update20261114 - CLASS ---------------------------------------------- #

class Update20261114(BaseDatabaseUpdate):
    """
    Drops the logs collection's ``object_id_log_time`` and ``log_type_action`` indexes, replaced by successors that
    end on ``log_time`` and ``public_id``

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261114


    def description(self) -> str:
        return "Drops the two log indexes the date-ordered log pages could not use"


    def start_update(self) -> None:
        """
        Drops each replaced index of the logs collection that is present, then bumps the version

        Raises:
            UpdaterException: If an index exists but cannot be dropped, or the version cannot be written
        """
        try:
            for index_name in REPLACED_INDEXES:
                if self.dbm.drop_index(LOGS_COLLECTION, self.db_name, index_name):
                    LOGGER.info("[updater_20261114] Dropped the '%s' index of %s", index_name, LOGS_COLLECTION)
                else:
                    LOGGER.info("[updater_20261114] No '%s' index on %s - nothing to drop", index_name, LOGS_COLLECTION)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
