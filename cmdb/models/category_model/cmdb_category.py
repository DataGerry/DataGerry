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

Categories are the tree the framework UI navigates types by. Each CmdbCategory holds the public_ids of
the CmdbTypes assigned to it in `types`, and points at its parent through `parent` - a null parent is a
root. The nesting rules are NOT enforced here: `CategoriesManager.validate_parent_assignment` owns both
the self-parent refusal and ancestor-cycle detection, because deciding them needs the other categories.
The `ValueError` this model raises for a direct self-parent is a last-resort backstop for a document
that reached it another way

`name` is the category's unique identifier (the collection's only unique index) and `label` is only
presentation - an unset label falls back to the title-cased name, computed rather than stored. Document
keys are named by `CategoryKey` and the nested meta keys by `CategoryMetaKey`; identity uses
`CmdbObjectKey.PUBLIC_ID`, the project-wide key for that
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

        A CmdbCategory may not be its own direct parent; that is refused here and surfaces as a
        `CmdbCategoryInitError`. It is a backstop only - `CategoriesManager.validate_parent_assignment`
        is what rejects a self-parent (and an ancestor cycle) before a write ever reaches this model

        Raises:
            CmdbCategoryInitError: If the CmdbCategory could not be initialised, including when
                `parent` equals `public_id`
        """
        try:
            self.name: str = name
            self.label: str | None = label
            self.meta: CategoryMeta = meta or CategoryMeta()

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
        Initialises a CmdbCategory from a stored document

        `public_id` and `name` are required - a document missing either fails here rather than
        producing a CmdbCategory that only breaks the next time something asks for its label. A
        `meta` sub-document that is absent or empty yields the empty default

        Args:
            data (dict): Data with which the CmdbCategory should be initialised

        Raises:
            CmdbCategoryInitFromDataError: If the initialisation with the given data fails, including
                a missing `public_id` or `name`

        Returns:
            CmdbCategory: The CmdbCategory built from the given data
        """
        try:
            raw_meta: Any = data.get(CategoryKey.META.value)
            meta: CategoryMeta | None = None

            # Anything other than a populated mapping means "no metadata" - `__init__` substitutes an
            # empty CategoryMeta, so the attribute is never left holding the raw value
            if isinstance(raw_meta, dict) and raw_meta:
                meta = CategoryMeta(
                    raw_meta.get(CategoryMetaKey.ICON.value, ''),
                    raw_meta.get(CategoryMetaKey.ORDER.value),
                )

            return cls(
                # public_id and name are required and indexed; reading them with [] means a document
                # that lacks one fails HERE, naming the missing key, instead of building a half-object
                # whose name is None and which only breaks later inside get_label()
                public_id=data[CmdbObjectKey.PUBLIC_ID.value],
                name=data[CategoryKey.NAME.value],
                label=data.get(CategoryKey.LABEL.value),
                meta=meta,
                parent=data.get(CategoryKey.PARENT.value),
                types=data.get(CategoryKey.TYPES.value, []),
            )
        except Exception as err:
            raise CmdbCategoryInitFromDataError(str(err)) from err


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
                CmdbObjectKey.PUBLIC_ID.value: instance.get_public_id(),
                CategoryKey.NAME.value: instance.name,
                CategoryKey.LABEL.value: instance.get_label(),
                CategoryKey.META.value: {
                    CategoryMetaKey.ICON.value: meta.get_icon(),
                    CategoryMetaKey.ORDER.value: meta.get_order()
                },
                CategoryKey.PARENT.value: instance.parent,
                CategoryKey.TYPES.value: instance.types
            }
        except Exception as err:
            raise CmdbCategoryToJsonError(str(err)) from err

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
        Returns the label of the CmdbCategory

        Falls back to the title-cased name when no label is set. The fallback is computed, never
        written back - a reader must not change the CmdbCategory it is reading

        Returns:
            str: The label of the CmdbCategory
        """
        return self.label or self.name.title()


    def get_meta(self) -> CategoryMeta:
        """
        Retrieves the metadata of the CmdbCategory

        Always a real `CategoryMeta`: `__init__` substitutes an empty one when the caller passes none,
        so this returns the instance's own object rather than minting a throw-away default per call -
        a caller that mutates the result is mutating the CmdbCategory's metadata, as it would expect

        Returns:
            CategoryMeta: The metadata associated with the CmdbCategory
        """
        return self.meta
