# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of Update20251203
"""
import logging

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20251203 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20251203(BaseDatabaseUpdate):
    """
    Implementation of Update20251203
    """
    def creation_date(self) -> int:
        return 20251203


    def description(self) -> str:
        return """
               Adds CiExplorerProfiles a new property "with_locations" to be able to store if
               the CI-Explorer should display locations
               """


    def start_update(self) -> None:
        try:
            # Update all CmdbObjects
            ci_exp_profile_collection = CmdbCiExplorerProfile.COLLECTION
            all_profiles: list[dict] = []

            all_profiles = self.dbm.find_all(ci_exp_profile_collection, self.db_name)

            for cur_obj in all_profiles:
                # Check if the object already has the property 'ci_explorer_tooltip', else create it
                if not 'with_locations' in cur_obj.keys():
                    cur_public_id = cur_obj['public_id']
                    cur_obj['with_locations'] = True

                    self.dbm.update(collection=ci_exp_profile_collection,
                                    db_name=self.db_name,
                                    criteria={'public_id':cur_public_id},
                                    data=cur_obj)
                    LOGGER.info("Updated 'with_locations' for Profile-ID: %s", cur_public_id)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
