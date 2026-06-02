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
Database update 20260417: backfill the 'special_type' marker on types and objects
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260417 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260417(BaseDatabaseUpdate):
    """
    Backfills an empty 'special_type' marker onto every CmdbType and CmdbObject that lacks it
    """
    def creation_date(self) -> int:
        return 20260417


    def description(self) -> str:
        return ("Adds a 'special_type' property to Types and Objects to identify special CmdbTypes "
                "and the CmdbObjects of those types")


    def start_update(self) -> None:
        """
        Sets 'special_type' to '' on all types and objects that do not yet have the property
        """
        try:
            filter_query: dict[str, Any] = {
                    "special_type": {"$exists": False}
            }

            update_query: dict[str, Any] = {
                "$set": {
                    "special_type": ""
                }
            }

            # Update all CmdbTypes
            self.types_manager.update_many_raw(
                filter_query=filter_query,
                update=update_query
            )

            # Update all CmdbObjects
            self.objects_manager.update_many_raw(
                filter_query=filter_query,
                update=update_query
            )
            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
