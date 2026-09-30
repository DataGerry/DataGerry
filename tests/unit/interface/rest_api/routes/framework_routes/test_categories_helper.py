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
Unit tests for the CmdbCategory write guards (categories_helper)

A stub CategoriesManager answers the two lookups, so each check - and the order they are asked in - is
tested without a database
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import (
    CATEGORY_TYPES_CLAIMED_MSG,
    CATEGORY_TYPES_NOT_IDS_MSG,
    CATEGORY_TYPES_REPEATED_MSG,
    CATEGORY_TYPES_UNKNOWN_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_helper import (
    abort_if_category_types_unusable,
    find_repeated_type_ids,
    format_type_claims,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID: int = 5


def _manager(unknown: list[int] | None = None, claims: dict[int, list[int]] | None = None) -> MagicMock:
    """A stub CategoriesManager answering the existence and the claims lookup."""
    manager = MagicMock()
    manager.find_unknown_type_ids.return_value = unknown or []
    manager.find_type_claims.return_value = claims or {}
    return manager


def _refusal(manager: MagicMock, type_ids: Any, category_id: int | None = CATEGORY_ID) -> HTTPException:
    """The HTTPException a refused list raises."""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_category_types_unusable(manager, type_ids, category_id)

    assert exc_info.value.code == 400
    return exc_info.value


class TestHelpers:
    """The two pure pieces."""

    def test_repeated_ids_are_found_sorted(self) -> None:
        """Each repeated id once"""
        assert find_repeated_type_ids([3, 1, 3, 2, 1, 1]) == [1, 3]

    def test_no_repeat_is_empty(self) -> None:
        """The ordinary case"""
        assert find_repeated_type_ids([1, 2, 3]) == []

    def test_claims_are_spelled_by_type_id(self) -> None:
        """Deterministic, whatever order the lookup answered in"""
        assert format_type_claims({7: [4, 2], 3: [9]}) == 'Type 3 in Category [9], Type 7 in Category [2, 4]'


class TestTheGuard:
    """abort_if_category_types_unusable."""

    @pytest.mark.parametrize('type_ids', [None, []], ids=['none', 'empty'])
    def test_no_types_ask_nothing(self, type_ids: Any) -> None:
        """A category without types is legal and costs no read"""
        manager = _manager()

        abort_if_category_types_unusable(manager, type_ids, CATEGORY_ID)

        manager.find_unknown_type_ids.assert_not_called()
        manager.find_type_claims.assert_not_called()

    def test_a_boolean_is_refused_before_any_read(self) -> None:
        """It slips past the schema's integer rule"""
        manager = _manager()

        assert _refusal(manager, [1, True]).description == CATEGORY_TYPES_NOT_IDS_MSG.format(values=[True])
        manager.find_unknown_type_ids.assert_not_called()

    def test_a_repeat_is_refused_before_any_read(self) -> None:
        """The cheap check first"""
        manager = _manager()

        assert _refusal(manager, [1, 2, 1]).description == CATEGORY_TYPES_REPEATED_MSG.format(type_ids=[1])
        manager.find_unknown_type_ids.assert_not_called()

    def test_an_unknown_id_is_refused_before_the_claims(self) -> None:
        """Naming the ids no Type carries"""
        manager = _manager(unknown=[99])

        assert _refusal(manager, [1, 99]).description == CATEGORY_TYPES_UNKNOWN_MSG.format(type_ids=[99])
        manager.find_type_claims.assert_not_called()

    def test_a_type_held_elsewhere_is_refused(self) -> None:
        """A type sits in at most one category"""
        manager = _manager(claims={1: [8]})

        assert _refusal(manager, [1, 2]).description == CATEGORY_TYPES_CLAIMED_MSG.format(
            claims='Type 1 in Category [8]')
        manager.find_type_claims.assert_called_once_with([1, 2], CATEGORY_ID)

    def test_a_usable_list_passes(self) -> None:
        """Every id once, existing, unclaimed"""
        abort_if_category_types_unusable(_manager(), [1, 2], None)
