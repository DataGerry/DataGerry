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
Unit tests for IterationResult

The container every `iterate` in the manager layer answers with: the page, its length, the total
number of matches, and an optional conversion of the raw documents into a `CmdbDAO` subtype.

The conversion guard was the one uncovered statement. It matters because `convert_to` is reachable
from the constructor - passing `c` converts eagerly - so a manager registering a class without
`from_data` gets a named `AttributeError` rather than the `AttributeError: 'X' object has no
attribute 'from_data'` it would otherwise hit one frame deeper, inside a list comprehension.
"""
from typing import Any

import pytest

from cmdb.framework.results import IterationResult
# -------------------------------------------------------------------------------------------------------------------- #

TOTAL: int = 17

DOCUMENTS: list[dict[str, Any]] = [{'public_id': 1}, {'public_id': 2}]


class _Convertible:
    """A minimal stand-in for a CmdbDAO subtype: all `convert_to` needs is `from_data`."""

    def __init__(self, public_id: int) -> None:
        self.public_id = public_id

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "_Convertible":
        """Builds one from a raw document."""
        return cls(data['public_id'])


class _NotConvertible:
    """A class with no `from_data` - what the guard exists to refuse."""


class TestTheContainer:
    """The page, its length and the total are three different numbers."""

    def test_keeps_the_documents_as_given(self) -> None:
        """Without a class to convert to, the raw documents are the results."""
        assert IterationResult(list(DOCUMENTS), TOTAL).results == DOCUMENTS

    def test_counts_the_page_not_the_total(self) -> None:
        """`count` is the page length; `total` is how many matched. A pager needs both."""
        result = IterationResult(list(DOCUMENTS), TOTAL)

        assert result.count == len(DOCUMENTS)
        assert result.total == TOTAL

    def test_an_empty_page_is_not_an_empty_match_set(self) -> None:
        """Paging past the end is a valid request: no results, but the total still reports."""
        result = IterationResult([], TOTAL)

        assert result.count == 0
        assert result.total == TOTAL


class TestConvertTo:
    """Turning raw documents into model instances."""

    def test_converts_every_document(self) -> None:
        """The caller iterates model instances, so every row has to be converted."""
        result: IterationResult = IterationResult(list(DOCUMENTS), TOTAL, _Convertible)

        assert all(isinstance(item, _Convertible) for item in result.results)
        assert [item.public_id for item in result.results] == [1, 2]

    def test_the_constructor_converts_eagerly(self) -> None:
        """Passing `c` is the usual path - every manager's `iterate` does exactly that."""
        result: IterationResult = IterationResult(list(DOCUMENTS), TOTAL)
        result.convert_to(_Convertible)

        assert all(isinstance(item, _Convertible) for item in result.results)

    def test_a_class_without_from_data_is_refused_by_name(self) -> None:
        """
        The guard names the offending class

        Without it the failure happens one frame deeper, inside the list comprehension, and reads as
        though an *instance* were missing the attribute.
        """
        with pytest.raises(AttributeError) as excinfo:
            IterationResult(list(DOCUMENTS), TOTAL, _NotConvertible)

        assert _NotConvertible.__name__ in str(excinfo.value)
        assert 'from_data' in str(excinfo.value)

    def test_nothing_is_converted_when_the_class_is_refused(self) -> None:
        """The check runs before the comprehension, so the results are not half-converted."""
        result: IterationResult = IterationResult(list(DOCUMENTS), TOTAL)

        with pytest.raises(AttributeError):
            result.convert_to(_NotConvertible)

        assert result.results == DOCUMENTS
