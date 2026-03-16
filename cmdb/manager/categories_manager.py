# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of the CategoriesManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.category_model import CmdbCategory, CategoryTree
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType

from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.categories_manager import (
    CategoriesManagerInitError,
    CategoriesManagerInsertError,
    CategoriesManagerGetError,
    CategoriesManagerUpdateError,
    CategoriesManagerDeleteError,
    CategoriesManagerIterationError,
    CategoriesManagerTreeInitError,
)
from cmdb.errors.models.cmdb_category import (
    CmdbCategoryToJsonError,
    CmdbCategoryInitFromDataError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CategoriesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoriesManager(BaseManager):
    """
    The CategoriesManager handles the interaction between the CmdbCategories-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database:str = None) -> None:
        """
        Set the database connection for the CategoriesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises: If the CategoriesManager could not be initialised
        """
        try:
            super().__init__(CmdbCategory.COLLECTION, dbm, database)
        except Exception as err:
            raise CategoriesManagerInitError(err) from err


    @property
    def tree(self) -> CategoryTree:
        """
        Get the CmdbCategories as a nested tree

        Raises:
            CategoriesManagerTreeInitError: When the CategoryTree initialisation failed

        Returns:
            CategoryTree: CmdbCategories as a tree structure
        """
        try:

            types = self.get_many_from_other_collection(CmdbType.COLLECTION)
            cmdb_types: list[CmdbType] = [CmdbType.from_data(a_type) for a_type in types]

            build_params = BuilderParameters({})
            categories = self.iterate(build_params).results

            category_tree = CategoryTree(categories, cmdb_types)

            return category_tree
        except Exception as err:
            raise CategoriesManagerTreeInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_category(self, category: dict) -> int:
        """
        Insert a CmdbCategory into the database

        Args:
            category (dict): Raw data of the CmdbCategory

        Raises:
            CategoriesManagerInsertError: When a CmdbCategory could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbCategory
        """
        try:
            if isinstance(category, CmdbCategory):
                category = CmdbCategory.to_json(category)

            return self.insert(category)
        except (BaseManagerInsertError, CmdbCategoryToJsonError)  as err:
            raise CategoriesManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_category] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerIterationError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_category(self, public_id: int) -> dict[str, Any]:
        """
        Retrieves a CmdbCategory from the database

        Args:
            public_id (int): public_id of the CmdbCategory

        Raises:
            CategoriesManagerGetError: When a CmdbCategory could not be retrieved

        Returns:
            dict: Raw data of the CmdbCategory
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise CategoriesManagerGetError(err) from err


    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser = None,
                permission: AccessControlPermission = None) -> IterationResult[CmdbCategory]:
        """
        Retrieves multiple CmdbCategories

        Args:
            builder_params (BuilderParameters): Filter for which CmdbCategories should be retrieved
            user (CmdbUser, optional): CmdbUser requestion this operation. Defaults to None
            permission (AccessControlPermission, optional): Required permission for the operation. Defaults to None

        Raises:
            CategoriesManagerIterationError: When the iteration failed or initialising the IterationResult

        Returns:
            IterationResult[CmdbCategory]: All CmdbCategories matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbCategory] = IterationResult(aggregation_result,
                                                                              total,
                                                                              CmdbCategory)

            return iteration_result
        except BaseManagerIterationError as err:
            raise CategoriesManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerIterationError(err) from err


    def get_categories_by(self, sort='public_id', **requirements: dict) -> list[CmdbCategory]:
        """
        Retrieves a list of CmdbCategories according to the 'requirements'

        Args:
            sort (str, optional): key be which the results should be sorted. Defaults to 'public_id'

        Raises:
            CategoriesManagerGetError: When the CmdbCategories could not be retrieved

        Returns:
            list[CmdbCategory]: list of CmdbCategories match the requirements
        """
        try:
            raw_categories = self.get_many_from_other_collection(collection=CmdbCategory.COLLECTION,
                                                                 sort=sort,
                                                                 **requirements)

            return [CmdbCategory.from_data(category) for category in raw_categories]
        except (BaseManagerGetError, CmdbCategoryInitFromDataError) as err:
            raise CategoriesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_categories_by] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_category(self, public_id:int, data: dict) -> None:
        """
        Updates a CmdbCategory in the database

        Args:
            public_id (int): public_id of the CmdbCategory which should be updated
            data (dict): The data with new values for the CmdbCategory

        Raises:
            CategoriesManagerUpdateError: When the update operation fails
        """
        try:
            self.update({'public_id':public_id}, CmdbCategory.to_json(data))
        except (BaseManagerUpdateError, CmdbCategoryToJsonError) as err:
            raise CategoriesManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_category(self, public_id: int) -> bool:
        """
        Deletes a CmdbCategory from the database

        Args:
            public_id (int): public_id of the CmdbCategory which should be deleted

        Raises:
            CategoriesManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete({'public_id':public_id})
        except BaseManagerDeleteError as err:
            raise CategoriesManagerDeleteError(err) from err

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def remove_category_as_parent(self, public_id: int) -> None:
        """
        Sets the parent attribute to null for all children of a CmdbCategory

        Args:
            public_id (int): public_id of the parent category

        Raises:
            CategoriesManagerGetError: When the child CmdbCategories could not be retrieved
            CategoriesManagerUpdateError: When a child CmdbCategory could not be updated
        """
        try:
            self.update_many(
                criteria={'parent': public_id},
                update={'parent': None}
            )
        except BaseManagerGetError as err:
            raise CategoriesManagerGetError(str(err)) from err
        except BaseManagerUpdateError as err:
            raise CategoriesManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[reset_children_categories] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerUpdateError(str(err)) from err
