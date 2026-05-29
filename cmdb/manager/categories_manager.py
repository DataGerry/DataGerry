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
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.category_model import CmdbCategory, CategoryTree
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType

from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.categories_manager import (
    CATEGORIES_MANAGER_ERRORS,
    CategoriesManagerGetError,
    CategoriesManagerIterationError,
    CategoriesManagerUpdateError,
    CategoriesManagerTreeInitError,
)
from cmdb.errors.models.cmdb_category import CmdbCategoryInitFromDataError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CategoriesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoriesManager(GenericManager):
    """
    The CategoriesManager handles the interaction between the CmdbCategories-API and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the CategoriesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            CategoriesManagerInitError: If the CategoriesManager could not be initialised
        """
        super().__init__(dbm, CmdbCategory, CATEGORIES_MANAGER_ERRORS, database)


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

            return CategoryTree(categories, cmdb_types)
        except Exception as err:
            raise CategoriesManagerTreeInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_category(self, category: CmdbCategory | dict[str, Any]) -> int:
        """
        Insert a CmdbCategory into the database

        Args:
            category (CmdbCategory | dict[str, Any]): Model instance or raw data of the CmdbCategory

        Raises:
            CategoriesManagerInsertError: When a CmdbCategory could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbCategory
        """
        return self.insert_item(category)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_category(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbCategory from the database

        Args:
            public_id (int): public_id of the CmdbCategory

        Raises:
            CategoriesManagerGetError: When the retrieval failed

        Returns:
            dict[str, Any] | None: Raw data of the CmdbCategory, or None if no document matches
        """
        return self.get_item(public_id, as_dict=True)


    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser | None = None,
                permission: AccessControlPermission | None = None) -> IterationResult[CmdbCategory]:
        """
        Retrieves multiple CmdbCategories

        Args:
            builder_params (BuilderParameters): Filter for which CmdbCategories should be retrieved
            user (CmdbUser | None, optional): CmdbUser requesting this operation. Defaults to None
            permission (AccessControlPermission | None, optional): Required permission for the operation.
                Defaults to None

        Raises:
            CategoriesManagerIterationError: When the iteration failed or initialising the IterationResult

        Returns:
            IterationResult[CmdbCategory]: All CmdbCategories matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            return IterationResult(aggregation_result, total, CmdbCategory)
        except BaseManagerIterationError as err:
            raise CategoriesManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerIterationError(err) from err


    def get_categories_by(self, sort: str = 'public_id', **requirements: Any) -> list[CmdbCategory]:
        """
        Retrieves a list of CmdbCategories matching the given requirements

        Args:
            sort (str, optional): Key by which the results should be sorted. Defaults to 'public_id'
            **requirements (Any): Key-value pairs used as filters for the query

        Raises:
            CategoriesManagerGetError: When the CmdbCategories could not be retrieved

        Returns:
            list[CmdbCategory]: List of CmdbCategories matching the requirements
        """
        try:
            raw_categories = self.get_many(sort=sort, **requirements)

            return [CmdbCategory.from_data(category) for category in raw_categories]
        except (BaseManagerGetError, CmdbCategoryInitFromDataError) as err:
            raise CategoriesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_categories_by] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_category(self, public_id: int, data: CmdbCategory | dict[str, Any]) -> None:
        """
        Updates a CmdbCategory in the database

        Args:
            public_id (int): public_id of the CmdbCategory which should be updated
            data (CmdbCategory | dict[str, Any]): Model instance or raw data with new values for the CmdbCategory

        Raises:
            CategoriesManagerUpdateError: When the update operation fails
        """
        self.update_item(public_id, data)

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
        return self.delete_item(public_id)

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
            LOGGER.error("[remove_category_as_parent] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerUpdateError(str(err)) from err
