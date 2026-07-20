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
Database update 20260720: drop the deprecated 'base.framework.type.clean' right from all user groups
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The right removed with the type clean/unclean feature (object reconciliation is now automatic on
# type update). Group rights are stored as their name strings, so it lingers as a dangling entry in
# any group that was explicitly granted it until pulled out here.
REMOVED_RIGHT: str = 'base.framework.type.clean'
# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260720 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260720(BaseDatabaseUpdate):
    """
    Removes the deprecated 'base.framework.type.clean' right from every CmdbUserGroup
    """
    def creation_date(self) -> int:
        return 20260720


    def description(self) -> str:
        return "Removes the deprecated 'base.framework.type.clean' right from all user groups"


    def start_update(self) -> None:
        """
        Pulls the removed 'base.framework.type.clean' right name from every group's ``rights`` array

        Group rights persist as name strings, so a group granted the now-removed right keeps a
        dangling entry. A single ``$pull`` over the groups whose ``rights`` still contain the name
        strips it; groups that never held it are not matched. Idempotent - a re-run matches nothing
        """
        try:
            self.dbm.update_many_raw(
                collection=CmdbUserGroup.COLLECTION,
                db_name=self.db_name,
                filter_query={'rights': REMOVED_RIGHT},
                update={'$pull': {'rights': REMOVED_RIGHT}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
