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
existing CmdbType, names it once, and a CmdbType sits in **at most one** category
"""
from collections import Counter
from typing import Any

from flask import abort

from cmdb.manager import CategoriesManager
from cmdb.models.category_model import is_type_id
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import (
    CATEGORY_TYPE_CLAIM_TEMPLATE,
    CATEGORY_TYPES_CLAIMED_MSG,
    CATEGORY_TYPES_NOT_IDS_MSG,
    CATEGORY_TYPES_REPEATED_MSG,
    CATEGORY_TYPES_UNKNOWN_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['abort_if_category_types_unusable', 'find_repeated_type_ids', 'format_type_claims']


def find_repeated_type_ids(type_ids: list[int]) -> list[int]:
    """
    Answers the ids a ``types`` list names more than once

    Args:
        type_ids (list[int]): The validated ``types`` list

    Returns:
        list[int]: The repeated ids, sorted; empty when every id appears once
    """
    return sorted(type_id for type_id, count in Counter(type_ids).items() if count > 1)


def format_type_claims(claims: dict[int, list[int]]) -> str:
    """
    Spells the "already assigned elsewhere" pairs for the refusal message

    Args:
        claims (dict[int, list[int]]): ``{type id: [ids of the categories holding it]}``

    Returns:
        str: One "Type <id> in Category [<ids>]" part per claimed type, by type id
    """
    return ', '.join(
        CATEGORY_TYPE_CLAIM_TEMPLATE.format(type_id=type_id, category_ids=sorted(category_ids))
        for type_id, category_ids in sorted(claims.items())
    )


def abort_if_category_types_unusable(
        categories_manager: CategoriesManager,
        type_ids: Any,
        category_public_id: int | None) -> None:
    """
    Refuses a category write whose ``types`` list names a Type twice, an unknown Type, or a Type another
    category already holds

    Runs before anything is written. An entry that is no positive integer (a boolean slips past the schema's
    integer rule) is refused first; then the three checks are asked in that order - the cheap one first, then
    one projected read over the types, then one over the other categories - and the first that fires
    answers

    Args:
        categories_manager (CategoriesManager): Manager used for the two lookups
        type_ids (Any): The validated ``types`` list (None or absent means an empty list)
        category_public_id (int | None): public_id of the category an update writes; None on a create

    Raises:
        HTTPException: 400 naming the offending ids
    """
    ids: list[Any] = list(type_ids or [])

    if not ids:
        return

    # The schema already refuses most non-ids; a boolean passes Cerberus' integer rule, so it is caught here
    not_ids: list[Any] = [value for value in ids if not is_type_id(value)]

    if not_ids:
        abort(400, CATEGORY_TYPES_NOT_IDS_MSG.format(values=not_ids))

    repeated: list[int] = find_repeated_type_ids(ids)

    if repeated:
        abort(400, CATEGORY_TYPES_REPEATED_MSG.format(type_ids=repeated))

    unknown: list[int] = categories_manager.find_unknown_type_ids(ids)

    if unknown:
        abort(400, CATEGORY_TYPES_UNKNOWN_MSG.format(type_ids=unknown))

    claims: dict[int, list[int]] = categories_manager.find_type_claims(ids, category_public_id)

    if claims:
        abort(400, CATEGORY_TYPES_CLAIMED_MSG.format(claims=format_type_claims(claims)))
