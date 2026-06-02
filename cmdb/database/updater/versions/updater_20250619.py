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
Database update 20250619: backfill CI-Explorer fields on objects and types
"""
import random
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20250619 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20250619(BaseDatabaseUpdate):
    """
    Backfills CI-Explorer fields: 'ci_explorer_tooltip' on objects, plus 'ci_explorer_color' and
    'ci_explorer_label' on types
    """

    def creation_date(self) -> int:
        return 20250619


    def description(self) -> str:
        return ("Adds 'ci_explorer_tooltip' to all CmdbObjects and 'ci_explorer_color' / "
                "'ci_explorer_label' to all CmdbTypes which don't have them")


    def start_update(self) -> None:
        """
        Adds the missing CI-Explorer fields to every object and type that does not already have them
        """
        try:
            #Update all CmdbObjects
            object_collection = CmdbObject.COLLECTION
            all_objects: list[dict[str, Any]] = []

            all_objects = self.dbm.find_all(object_collection, self.db_name)

            for cur_obj in all_objects:
                # Check if the object already has the property 'ci_explorer_tooltip', else create it
                if not 'ci_explorer_tooltip' in cur_obj.keys():
                    cur_public_id = cur_obj['public_id']
                    cur_obj['ci_explorer_tooltip'] = None

                    self.dbm.update(collection=object_collection,
                                    db_name=self.db_name,
                                    criteria={'public_id':cur_public_id},
                                    data=cur_obj)
                    LOGGER.info("Updated 'ci_explorer_tooltip' for Object-ID: %s", cur_public_id)

            # Update all CmdbTypes
            type_collection = CmdbType.COLLECTION
            all_types: list[dict[str, Any]] = []

            all_types = self.dbm.find_all(type_collection, self.db_name)

            for cur_type in all_types:
                update_fields: dict[str, Any] = {}
                cur_public_id = cur_type.get('public_id')

                if not cur_public_id:
                    continue  # Skip if no public_id

                # Check for missing fields
                if 'ci_explorer_label' not in cur_type:
                    update_fields['ci_explorer_label'] = None

                if 'ci_explorer_color' not in cur_type:
                    update_fields['ci_explorer_color'] = get_random_color()

                # Only update if something needs to be added
                if update_fields:
                    self.dbm.update(
                        collection=type_collection,
                        db_name=self.db_name,
                        criteria={'public_id': cur_public_id},
                        data={'$set': update_fields}
                    )
                    LOGGER.info("Updated fields %s for Type-ID: %s", list(update_fields.keys()), cur_public_id)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def get_random_color() -> str:
    """
    Generates a random hex color in the form #RRGGBB

    Returns:
        str: A random color string such as '#1A2B3C'
    """
    return f'#{random.randint(0, 0xFFFFFF):06X}'
