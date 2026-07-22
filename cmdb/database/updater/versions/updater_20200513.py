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
Database update 20200513: backfill 'global_template_ids' and 'selectable_as_parent' on types
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20200513 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20200513(BaseDatabaseUpdate):
    """
    Backfills 'global_template_ids' and 'selectable_as_parent' onto every type that lacks them
    """


    def creation_date(self) -> int:
        return 20200513


    def description(self) -> str:
        return "Adds the property 'global_template_ids' and 'selectable_as_parent' to all types"


    def start_update(self) -> None:
        """
        Adds the missing 'global_template_ids' ([]) and 'selectable_as_parent' (True) to each type

        Both fields are added in a single bulk update each, targeting only the types that do not yet
        have the respective property.
        """
        try:
            self.types_manager.update_many_raw(
                filter_query={'global_template_ids': {'$exists': False}},
                update={'$set': {'global_template_ids': []}},
            )

            self.types_manager.update_many_raw(
                filter_query={'selectable_as_parent': {'$exists': False}},
                update={'$set': {'selectable_as_parent': True}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
