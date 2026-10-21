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
Guards shared by the CmdbCategory write routes

A category's ``types`` names the CmdbTypes shown under it in the sidebar. The schema holds every entry to a
positive integer; these guards hold the list to what the frontend already assumes: every id names an
existing CmdbType, names it once, and a CmdbType sits in **at most one** category. A malformed list is
refused; an id that names no CmdbType or a CmdbType another category holds is dropped, so a category that
still carries a deleted type can always be saved again
"""
from collections import Counter
from typing import Any

from flask import abort

from cmdb.manager import CategoriesManager
from cmdb.models.category_model import is_type_id
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import (
    CATEGORY_TYPES_NOT_IDS_MSG,
    CATEGORY_TYPES_REPEATED_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['drop_type_ids', 'find_repeated_type_ids', 'usable_category_types']


def find_repeated_type_ids(type_ids: list[int]) -> list[int]:
    """
    Answers the ids a ``types`` list names more than once

    Args:
        type_ids (list[int]): The validated ``types`` list

    Returns:
        list[int]: The repeated ids, sorted; empty when every id appears once
    """
    return sorted(type_id for type_id, count in Counter(type_ids).items() if count > 1)


def drop_type_ids(type_ids: list[int], dropped: set[int]) -> list[int]:
    """
    Answers a ``types`` list without the given ids, keeping the order of the rest

    Args:
        type_ids (list[int]): The validated ``types`` list
        dropped (set[int]): The ids to leave out

    Returns:
        list[int]: The remaining ids, in their original order
    """
    return [type_id for type_id in type_ids if type_id not in dropped]


def usable_category_types(
        categories_manager: CategoriesManager,
        type_ids: Any,
        category_public_id: int | None) -> list[int]:
    """
    Answers the ``types`` list a category write stores: refuses a malformed list, drops the unusable ids

    Runs before anything is written. An entry that is no positive integer (a boolean slips past the schema's
    integer rule) and an id named twice are refused. Of the rest, an id no CmdbType carries and a CmdbType
    another category already holds are dropped - one projected read over the types, then one over the other
    categories for the ids that exist. The other category keeps its type

    Args:
        categories_manager (CategoriesManager): Manager used for the two lookups
        type_ids (Any): The validated ``types`` list (None or absent means an empty list)
        category_public_id (int | None): public_id of the category an update writes; None on a create

    Raises:
        HTTPException: 400 naming the entries that are no id or the ids named twice

    Returns:
        list[int]: The ids to store, in the order the write named them
    """
    ids: list[Any] = list(type_ids or [])

    if not ids:
        return ids

    # The schema already refuses most non-ids; a boolean passes Cerberus' integer rule, so it is caught here
    not_ids: list[Any] = [value for value in ids if not is_type_id(value)]

    if not_ids:
        abort(400, CATEGORY_TYPES_NOT_IDS_MSG.format(values=not_ids))

    repeated: list[int] = find_repeated_type_ids(ids)

    if repeated:
        abort(400, CATEGORY_TYPES_REPEATED_MSG.format(type_ids=repeated))

    known: list[int] = drop_type_ids(ids, set(categories_manager.find_unknown_type_ids(ids)))
    claimed: set[int] = set(categories_manager.find_type_claims(known, category_public_id))

    return drop_type_ids(known, claimed)
