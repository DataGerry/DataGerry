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
Database update 20240603: backfill 'multi_data_sections' on objects
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20240603 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20240603(BaseDatabaseUpdate):
    """
    Backfills the 'multi_data_sections' property ([]) onto every object that lacks it
    """


    def creation_date(self) -> int:
        return 20240603


    def description(self) -> str:
        return "Adds the property 'multi_data_sections' to all objects which don't have it"


    def start_update(self) -> None:
        """
        Adds an empty 'multi_data_sections' list to every object that does not already have it

        Applied as a single bulk update targeting only the objects missing the property.
        """
        try:
            self.objects_manager.update_many_raw(
                filter_query={'multi_data_sections': {'$exists': False}},
                update={'$set': {'multi_data_sections': []}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
