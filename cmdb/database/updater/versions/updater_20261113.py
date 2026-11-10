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
Database update 20261113: take the rights the catalogue no longer offers out of every stored group

Ten rights left the catalogue because no route or helper ever checked them: holding one changed nothing. A group
write accepts catalogue names only, so a stored group still holding one would be refused on its next save. This
update pulls the ten names from every group's ``rights`` in one write; every other right, and every other key of the
group, stays as it is. A wildcard a group holds is untouched - it still grants whatever the catalogue holds below it.

Re-run safe: a second run finds no group holding a removed name and writes nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
GROUPS_COLLECTION: str = 'management.groups'
RIGHTS_FIELD: str = 'rights'

# The rights removed from the catalogue with this version
REMOVED_RIGHTS: tuple[str, ...] = (
    'base.system.reload',
    'base.framework.type.activation',
    'base.framework.log.reload',
    'base.framework.ipam.add',
    'base.framework.ipam.delete',
    'base.framework.location.add',
    'base.framework.location.delete',
    'base.framework.rack.add',
    'base.framework.rack.delete',
    'base.license.activation.delete',
)

# The groups holding at least one removed right, and the write taking every one of them out
GROUPS_HOLDING_A_REMOVED_RIGHT: dict[str, Any] = {RIGHTS_FIELD: {'$in': list(REMOVED_RIGHTS)}}
PULL_REMOVED_RIGHTS: dict[str, Any] = {'$pull': {RIGHTS_FIELD: {'$in': list(REMOVED_RIGHTS)}}}

# ---------------------------------------------- Update20261113 - CLASS ---------------------------------------------- #

class Update20261113(BaseDatabaseUpdate):
    """
    Pulls the rights the catalogue no longer offers from every stored group

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261113


    def description(self) -> str:
        return "Removes the rights no route checks from the stored groups"


    def start_update(self) -> None:
        """
        Pulls the removed rights from every group holding one, in one write, then bumps the version

        Raises:
            UpdaterException: If the write fails
        """
        try:
            result = self.dbm.update_many_raw(
                GROUPS_COLLECTION, self.db_name, GROUPS_HOLDING_A_REMOVED_RIGHT, PULL_REMOVED_RIGHTS,
            )

            LOGGER.info("[updater_20261113] Removed the unchecked rights from %s group(s)", result.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
