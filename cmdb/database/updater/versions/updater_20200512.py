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
Database update 20200512: restructure the category system
"""
from logging import Logger, getLogger
<<<<<<< HEAD
=======
from typing import Any
>>>>>>> origin/version-3.2

from cmdb.models.category_model import CmdbCategory
from cmdb.models.type_model import CmdbType
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.manager.objects_manager import ObjectsManagerInsertError
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20200512 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20200512(BaseDatabaseUpdate):
    """
    Restructures the category system (DataGerry < 20200512 -> new structure)

    Rebuilds the categories collection: each legacy category is converted to the new meta/parent
    layout with its member type ids, then the obsolete 'category_id' field is removed from all types.
    """


    def creation_date(self) -> int:
        return 20200512


    def description(self) -> str:
        return 'Restructure category system'


    def start_update(self) -> None:
        """
        Converts every category to the new structure, rebuilds the collection and clears type links
        """
        try:
            collection = CmdbCategory.COLLECTION
            new_categories: list[CmdbCategory] = []
            raw_categories_old_structure: list[dict[str, Any]] = self.dbm.find_all(
                                                                collection=collection,
                                                                db_name=self.db_name,
                                                                filter={}
                                                        )
            for idx, old_raw_category in enumerate(raw_categories_old_structure):
                new_categories.append(self.__convert_category_to_new_structure(old_raw_category, index=idx))

            self.dbm.delete_collection(collection=CmdbCategory.COLLECTION, db_name=self.db_name)
            self.dbm.create_collection(CmdbCategory.COLLECTION, self.db_name)
            self.dbm.create_indexes(CmdbCategory.COLLECTION, self.db_name, CmdbCategory.get_index_keys())

            for category in new_categories:
                try:
                    self.categories_manager.insert_category(CmdbCategory.to_json(category))
                except ObjectsManagerInsertError:
                    continue

            self.__clear_up_types()

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def __convert_category_to_new_structure(self, old_raw_category: dict[str, Any], index: int) -> CmdbCategory:
        """
        Converts a single legacy (< 20200512) category dict into a CmdbCategory of the new structure

        Args:
            old_raw_category (dict[str, Any]): The stored legacy category document
            index (int): Position used as the new category 'order'

        Returns:
            CmdbCategory: The converted category, with its member type ids resolved
        """
        old_raw_category['meta'] = {
            'icon': old_raw_category.get('icon'),
            'order': index
        }
        parent = old_raw_category.get('parent_id')

        if parent == 0:
            parent = None

        old_raw_category['parent'] = parent
        category = CmdbCategory.from_data(old_raw_category)
        category.types = self.__get_types_in_category(old_raw_category.get('public_id'))

        return category


    def __get_types_in_category(self, category_id: int) -> list[int]:
        """
        Returns the public_ids of all types that referenced the given legacy category

        Reads the soon-to-be-removed 'category_id' field directly from the type documents.

        Args:
            category_id (int): public_id of the legacy category

        Returns:
            list[int]: public_ids of the types assigned to that category
        """
        return [type.get('public_id') for type in
                self.dbm.find_all(
                            collection=CmdbType.COLLECTION,
                            db_name=self.db_name,
                            filter={'category_id': category_id}
                        )]


    def __clear_up_types(self) -> None:
        """
        Removes the obsolete 'category_id' field from every type document
        """
        self.dbm.unset_update_many(
                    collection=CmdbType.COLLECTION,
                    db_name=self.db_name,
                    criteria={},
                    field='category_id'
                )
