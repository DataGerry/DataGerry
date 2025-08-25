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
Implementation of Update20240603
"""
import logging

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.object_model import CmdbObject

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20240603 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20240603(BaseDatabaseUpdate):
    """
    Implementation of Update20240603
    """


    def creation_date(self) -> int:
        return 20240603


    def description(self) -> str:
        return """
               Add the property 'multi_data_sections' to all objects which don't have it
               """


    def start_update(self) -> None:
        try:
            collection = CmdbObject.COLLECTION
            all_objects: list[dict] = []

            all_objects = self.dbm.find_all(collection, self.db_name)

            for cur_obj in all_objects:
                # Check if the object already has the property 'multi_data_sections', else create it
                if not 'multi_data_sections' in cur_obj.keys():
                    cur_public_id = cur_obj['public_id']
                    cur_obj['multi_data_sections'] = []

                    self.dbm.update(collection=collection,
                                    db_name=self.db_name,
                                    criteria={'public_id':cur_public_id},
                                    data=cur_obj)
                    LOGGER.info("Updated 'multi_data_sections' for object ID: %s", cur_public_id)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
