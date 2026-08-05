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
Database update 20251203: backfill 'with_locations' on CI-Explorer profiles
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20251203 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20251203(BaseDatabaseUpdate):
    """
    Backfills the 'with_locations' property (True) onto every CI-Explorer profile that lacks it
    """
    def creation_date(self) -> int:
        return 20251203


    def description(self) -> str:
        return ("Adds the 'with_locations' property to CiExplorerProfiles to store whether the "
                "CI-Explorer should display locations")


    def start_update(self) -> None:
        """
        Adds 'with_locations' (defaulting to True) to every CI-Explorer profile that lacks it

        Applied as a single bulk update targeting only the profiles missing the property.
        """
        try:
            self.dbm.update_many_raw(
                collection=CmdbCiExplorerProfile.COLLECTION,
                db_name=self.db_name,
                filter_query={'with_locations': {'$exists': False}},
                update={'$set': {'with_locations': True}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
