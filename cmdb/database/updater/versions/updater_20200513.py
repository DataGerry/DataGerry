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
Implementation of Update20200513
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.models.type_model import CmdbType

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20200513 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20200513(BaseDatabaseUpdate):
    """
    Implementation of Update20200513
    """


    def creation_date(self) -> int:
        return 20200513


    def description(self) -> str:
        return "Adds the property 'global_template_ids' and 'selectable_as_parent' to all types"


    def start_update(self) -> None:
        try:
            collection = CmdbType.COLLECTION
            all_types: list[dict] = []

            all_types = self.dbm.find_all(collection, self.db_name)

            for cur_type in all_types:
                #Check if the type already has the 'global_template_ids' property, else create it
                cur_public_id: int = cur_type['public_id']
                global_template_ids: str = 'global_template_ids'
                selectable_as_parent: str = 'selectable_as_parent'

                if not global_template_ids in cur_type.keys():
                    cur_type[global_template_ids] = []
                    self.dbm.update(collection=collection,
                                    db_name=self.db_name,
                                    criteria={'public_id':cur_public_id},
                                    data=cur_type)
                    LOGGER.info("Updated 'global_template_ids' for type ID: %s", cur_public_id)

                if not selectable_as_parent in cur_type.keys():
                    cur_type[selectable_as_parent] = True
                    self.dbm.update(collection=collection,
                                    db_name=self.db_name,
                                    criteria={'public_id':cur_public_id},
                                    data=cur_type)
                    LOGGER.info("Updated 'selectable_as_parent' for type ID: %s", cur_public_id)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
