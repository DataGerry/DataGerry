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
Represents a CmdbCategory in DataGerry
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.class_schema.category_model.cmdb_category_schema import get_cmdb_category_schema

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.category_model.category_meta import CategoryMeta
from cmdb.models.object_model import CmdbObjectKey

from cmdb.errors.models.cmdb_category import (
    CmdbCategoryInitError,
    CmdbCategoryInitFromDataError,
    CmdbCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbCategory - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbCategory(CmdbDAO):
    """
    Implementation of a CmdbCategory in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.categories'
    SCHEMA: dict[str, Any] = get_cmdb_category_schema()

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True},
        {'keys': [('parent', CmdbDAO.DAO_ASCENDING)], 'name': 'parent', 'unique': False},
        {'keys': [('types', CmdbDAO.DAO_ASCENDING)], 'name': 'types', 'unique': False}
    ]

    #pylint: disable=too-many-arguments
    def __init__(
        self,
        public_id: int,
        name: str,
        label: str | None = None,
        meta: CategoryMeta | None = None,
        parent: int | None = None,
        types: list[int] | None = None
    ) -> None:
        """
        Initialises a CmdbCategory

        Args:
            public_id (int): public_id of the CmdbCategory
            name (str): The name of the CmdbCategory
            label (str | None, optional): The Label of the CmdbCategory. Defaults to None
            meta (CategoryMeta | None, optional): The CategoryMeta of the CmdbCategory. Defaults to None
            parent (int | None, optional): The public_id of the parent CmdbCategory. Defaults to None
            types (list[int] | None, optional): public_ids of CmdbTypes assigned to this CmdbCategory.
                                                Defaults to None

        Raises:
            CmdbCategoryInitError: if the CmdbCategory could not be initialised
        """
        try:
            self.name: str = name
            self.label: str | None = label
            self.meta: CategoryMeta | None = meta

            if parent == public_id and (parent is not None):
                raise ValueError(f'Category {name} has his own ID as Parent')

            self.parent: int | None = parent
            self.types: list[int] = types or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbCategoryInitError(str(err)) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbCategory":
        """
        Initialises a CmdbCategory from a dict

        Args:
            data (dict): Data with which the CmdbCategory should be initialised

        Raises:
            CmdbCategoryInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbCategory: CmdbRelation with the given data
        """
        try:
            raw_meta: dict[str, Any] | None = data.get(CategoryKey.META, None)

            if raw_meta:
                meta = CategoryMeta(raw_meta.get(CategoryMetaKey.ICON, ''), raw_meta.get(CategoryMetaKey.ORDER, None))
            else:
                meta = raw_meta

            return cls(
                public_id = data.get(CmdbObjectKey.PUBLIC_ID),
                name = data.get(CategoryKey.NAME),
                label = data.get(CategoryKey.LABEL, None),
                meta = meta,
                parent = data.get(CategoryKey.PARENT),
                types = data.get(CategoryKey.TYPES, [])
            )
        except Exception as err:
            raise CmdbCategoryInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbCategory") -> dict[str, Any]:
        """
        Converts a CmdbCategory into a json compatible dict

        Args:
            instance (CmdbCategory): The CmdbCategory which should be converted

        Raises:
            CmdbCategoryToJsonError: If the CmdbCategory could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbCategory values
        """
        try:
            meta: CategoryMeta = instance.get_meta()

            return {
                CmdbObjectKey.PUBLIC_ID: instance.get_public_id(),
                CategoryKey.NAME: instance.name,
                CategoryKey.LABEL: instance.get_label(),
                CategoryKey.META: {
                    CategoryMetaKey.ICON: meta.get_icon(),
                    CategoryMetaKey.ORDER: meta.get_order()
                },
                CategoryKey.PARENT: instance.parent,
                CategoryKey.TYPES: instance.types
            }
        except Exception as err:
            raise CmdbCategoryToJsonError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_name(self) -> str:
        """
        Returns the name of the CmdbCategory

        Returns:
            str: The name of the CmdbCategory
        """
        return self.name


    def get_label(self) -> str:
        """
        Returns the label of the CmdbCategory. If the label is not set, it returns 
        the title-cased name without modifying the instance attribute

        Returns:
            str: The label of the CmdbCategory
        """
        return self.label or self.name.title()


    def get_meta(self) -> CategoryMeta:
        """
        Retrieves the metadata for the CmdbCategory

        Returns:
            CategoryMeta: The metadata associated with the CmdbCategory. If no metadata 
            is set, a new `CategoryMeta` instance is returned as a default.
        """
        return self.meta or CategoryMeta()
