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
Database update 20261120: the person and person group rights leave every user group

Step 8 of the persons plan. The persons and person groups are objects since ``updater_20261119``, which turned the old
``base.user-management.person.*`` / ``personGroup.*`` rights of every user group into ACL entries of the default
person Types; the routes ask the object rights since. The rights left the catalogue, so a group still listing one
would carry a right nothing knows - this update pulls the ten names (the two wildcards and the four actions of each)
from every group. A wider wildcard (``base.user-management.*``, ``base.*``) is left alone: it names more than persons.

Re-run safe: a ``$pull`` of names no group holds any more changes nothing
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
USER_GROUPS: str = 'management.groups'
RIGHTS: str = 'rights'
RETIRED_RIGHTS: list[str] = [
    f'base.user-management.{entity}.{action}'
    for entity in ('person', 'personGroup') for action in ('*', 'view', 'add', 'edit', 'delete')
]

# ---------------------------------------------- Update20261120 - CLASS ---------------------------------------------- #

class Update20261120(BaseDatabaseUpdate):
    """
    Removes the retired person and person group rights from every user group

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261120


    def description(self) -> str:
        return "Removes the person and person group rights from every user group"


    def start_update(self) -> None:
        """
        Pulls the retired rights from every group holding one, then bumps the version

        Raises:
            UpdaterException: If the update or the version write fails
        """
        try:
            result = self.dbm.get_collection(USER_GROUPS, self.db_name).update_many(
                {RIGHTS: {'$in': RETIRED_RIGHTS}}, {'$pull': {RIGHTS: {'$in': RETIRED_RIGHTS}}},
            )

            if result.modified_count:
                LOGGER.info("[updater_20261120] Removed the person rights from %s group(s)", result.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
