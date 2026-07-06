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

from cmdb.models.category_model import CategoryKey, CmdbCategory, CategoryTree
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObjectKey

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
            CategoriesManagerUpdateError: When a child CmdbCategory could not be updated
        """
        try:
            self.update_many(
                criteria={CategoryKey.PARENT: public_id},
                update={CategoryKey.PARENT: None}
            )
        except BaseManagerUpdateError as err:
            raise CategoriesManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[remove_category_as_parent] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerUpdateError(str(err)) from err


    def remove_type_from_categories(self, type_id: int) -> None:
        """
        Removes a CmdbType's public_id from the 'types' array of every CmdbCategory

        Part of the CmdbType deletion cleanup chain: without it, deleted type ids linger in
        category documents forever (the tree view silently hides them, so the rot is
        invisible while the stored data degrades)

        Args:
            type_id (int): public_id of the deleted CmdbType

        Raises:
            CategoriesManagerUpdateError: When the cleanup update fails
        """
        try:
            self.update_many_pull(
                criteria={CategoryKey.TYPES: type_id},
                update={'$pull': {CategoryKey.TYPES: type_id}}
            )
        except BaseManagerUpdateError as err:
            raise CategoriesManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[remove_type_from_categories] Exception: %s. Type: %s", err, type(err))
            raise CategoriesManagerUpdateError(str(err)) from err


    def validate_parent_assignment(self, public_id: int | None, parent_id: int | None) -> str | None:
        """
        Validates that 'parent_id' may be assigned as the parent of the CmdbCategory 'public_id'

        Three rules, checked in order:
          1. The parent CmdbCategory must exist (rejects dangling references that would make
             the child silently vanish from the tree)
          2. A CmdbCategory cannot be its own parent (a stored self-parent breaks the tree)
          3. The assignment must not close an ancestor cycle: walking the parent chain
             upwards from 'parent_id' must not reach 'public_id' (A -> B -> A)

        'parent_id' = None (detaching / root category) is always valid. 'public_id' = None
        (insert: the id is not assigned yet) skips rules 2 and 3 - a fresh id can never be
        part of an existing chain

        Args:
            public_id (int | None): public_id of the CmdbCategory being written, or None on insert
            parent_id (int | None): The requested parent public_id, or None for a root category

        Raises:
            CategoriesManagerGetError: When a parent-chain lookup fails

        Returns:
            str | None: A human-readable rejection reason, or None when the assignment is valid
        """
        if parent_id is None:
            return None

        if public_id is not None and parent_id == public_id:
            return f"A Category cannot be its own parent (ID:{public_id})!"

        ancestor_ids: set[int] | None = self._get_ancestor_ids(parent_id)

        if ancestor_ids is None:
            return f"The parent Category with ID:{parent_id} does not exist!"

        if public_id is None:
            return None

        # Reaching the candidate among the parent's ancestors would close a cycle (A -> B -> A)
        if public_id in ancestor_ids:
            return (
                f"Assigning parent ID:{parent_id} would create a cycle: Category"
                f" ID:{public_id} is an ancestor of it!"
            )

        return None


    def _get_ancestor_ids(self, parent_id: int) -> set[int] | None:
        """
        Resolves the full ancestor chain of a CmdbCategory in a single ``$graphLookup`` query

        Replaces an upward walk that issued one ``get_category`` query per ancestor: ``$graphLookup``
        follows each category's ``parent`` link to another category's ``public_id``, collecting every
        ancestor of ``parent_id`` in one round-trip. Its built-in cycle handling means a pre-existing
        parent cycle in stored data cannot loop forever. ``$graphLookup`` is a MongoDB 3.4 feature

        Args:
            parent_id (int): public_id of the parent CmdbCategory whose ancestors are resolved

        Raises:
            CategoriesManagerGetError: When the lookup fails

        Returns:
            set[int] | None: public_ids of all ancestors of ``parent_id``, or None when no
                CmdbCategory with that public_id exists
        """
        pipeline: list[dict[str, Any]] = [
            {'$match': {CmdbObjectKey.PUBLIC_ID.value: parent_id}},
            {'$graphLookup': {
                'from': CmdbCategory.COLLECTION,
                'startWith': f'${CategoryKey.PARENT.value}',
                'connectFromField': CategoryKey.PARENT.value,
                'connectToField': CmdbObjectKey.PUBLIC_ID.value,
                'as': '_ancestors',
            }},
            {'$project': {'_ancestor_ids': f'$_ancestors.{CmdbObjectKey.PUBLIC_ID.value}'}},
        ]

        try:
            result: list[dict[str, Any]] = list(self.aggregate(pipeline))
        except BaseManagerIterationError as err:
            raise CategoriesManagerGetError(str(err)) from err

        if not result:
            return None

        return set(result[0].get('_ancestor_ids', []))
