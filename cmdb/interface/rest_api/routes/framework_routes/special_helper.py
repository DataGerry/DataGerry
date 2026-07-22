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
Helper functions for the DataGerry Assistant (special) REST routes
"""
from cmdb.manager import CategoriesManager, ObjectsManager
from cmdb.manager.types_manager import TypesManager
# -------------------------------------------------------------------------------------------------------------------- #


def has_framework_data(
        categories_manager: CategoriesManager,
        types_manager: TypesManager,
        objects_manager: ObjectsManager) -> bool:
    """
    Checks whether any framework data (categories, types, or objects) already exists

    The collections are counted in order and the check returns as soon as one of them is non-empty,
    so a populated database is detected without counting every collection. Used by the DataGerry
    Assistant to decide whether to offer the intro and to guard the initial profile creation.

    Args:
        categories_manager (CategoriesManager): Manager used to count CmdbCategories
        types_manager (TypesManager): Manager used to count CmdbTypes
        objects_manager (ObjectsManager): Manager used to count CmdbObjects

    Returns:
        bool: True if at least one category, type, or object exists, otherwise False
    """
    if categories_manager.count_documents() > 0:
        return True

    if types_manager.count_documents() > 0:
        return True

    return objects_manager.count_documents() > 0
