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
    CATEGORY_TYPES_NOT_IDS_MSG,
    CATEGORY_TYPES_REPEATED_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_helper import (
    drop_type_ids,
    find_repeated_type_ids,
    usable_category_types,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID: int = 5
OTHER_CATEGORY_ID: int = 8


def _manager(unknown: list[int] | None = None, claims: dict[int, list[int]] | None = None) -> MagicMock:
    """A stub CategoriesManager answering the existence and the claims lookup."""
    manager = MagicMock()
    manager.find_unknown_type_ids.return_value = unknown or []
    manager.find_type_claims.return_value = claims or {}
    return manager


def _refusal(manager: MagicMock, type_ids: Any, category_id: int | None = CATEGORY_ID) -> HTTPException:
    """The HTTPException a refused list raises."""
    with pytest.raises(HTTPException) as exc_info:
        usable_category_types(manager, type_ids, category_id)

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

    def test_dropping_keeps_the_order_of_the_rest(self) -> None:
        """The sidebar order the write named survives"""
        assert drop_type_ids([7, 3, 9, 1], {9, 3}) == [7, 1]

    def test_dropping_nothing_keeps_everything(self) -> None:
        """The ordinary case"""
        assert drop_type_ids([2, 1], set()) == [2, 1]


class TestTheGuard:
    """usable_category_types."""

    @pytest.mark.parametrize('type_ids', [None, []], ids=['none', 'empty'])
    def test_no_types_ask_nothing(self, type_ids: Any) -> None:
        """A category without types is legal and costs no read"""
        manager = _manager()

        assert usable_category_types(manager, type_ids, CATEGORY_ID) == []
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

    def test_an_unknown_id_is_dropped_and_not_asked_about_claims(self) -> None:
        """A deleted type no longer blocks the save"""
        manager = _manager(unknown=[99])

        assert usable_category_types(manager, [3, 99, 1], CATEGORY_ID) == [3, 1]
        manager.find_type_claims.assert_called_once_with([3, 1], CATEGORY_ID)

    def test_a_type_held_elsewhere_is_dropped(self) -> None:
        """The other category keeps it"""
        manager = _manager(claims={1: [OTHER_CATEGORY_ID]})

        assert usable_category_types(manager, [2, 1, 4], CATEGORY_ID) == [2, 4]
        manager.find_type_claims.assert_called_once_with([2, 1, 4], CATEGORY_ID)

    def test_unknown_and_claimed_are_both_dropped(self) -> None:
        """Each lookup removes its own ids"""
        manager = _manager(unknown=[6], claims={2: [OTHER_CATEGORY_ID]})

        assert usable_category_types(manager, [6, 2, 5], None) == [5]

    def test_a_usable_list_is_kept_as_named(self) -> None:
        """Every id once, existing, unclaimed"""
        assert usable_category_types(_manager(), [2, 1], None) == [2, 1]
