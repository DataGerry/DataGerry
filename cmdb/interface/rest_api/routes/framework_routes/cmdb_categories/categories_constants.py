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
String constants used by the CmdbCategory REST routes

The ``CategoryListView`` enum captures the ``?view=`` query-string values understood by
the list endpoint - ``list`` for the standard paginated flat listing, ``tree`` for the
nested CategoryTree representation. Extends BaseStrEnum so members compare equal to and
serialize as their raw string values
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class CategoryListView(BaseStrEnum):
    """
    ``?view=`` query-string values accepted by ``GET /rest/categories/``
    """
    LIST = 'list'
    TREE = 'tree'


# Name of the optional ?view= query parameter as parsed into CollectionParameters.optional
CATEGORY_VIEW_PARAM: str = 'view'


class CategoryRight(BaseStrEnum):
    """
    ACL rights guarding the CmdbCategory REST routes (``base.framework.category.*``)
    """
    ADD = 'base.framework.category.add'
    VIEW = 'base.framework.category.view'
    EDIT = 'base.framework.category.edit'
    DELETE = 'base.framework.category.delete'


# Why a category write's ``types`` list is refused - a CmdbType sits in at most one category, once
CATEGORY_TYPES_NOT_IDS_MSG: str = "A Category's types are Type IDs - positive whole numbers. Not one: {values}!"
CATEGORY_TYPES_REPEATED_MSG: str = "A Category may name a Type only once. Named more than once: {type_ids}!"
CATEGORY_TYPES_UNKNOWN_MSG: str = "No Type exists with the ID(s): {type_ids}!"
CATEGORY_TYPES_CLAIMED_MSG: str = (
    "A Type belongs to at most one Category. Already assigned elsewhere: {claims}!"
)
# One "type -> category ids" pair of CATEGORY_TYPES_CLAIMED_MSG
CATEGORY_TYPE_CLAIM_TEMPLATE: str = "Type {type_id} in Category {category_ids}"
