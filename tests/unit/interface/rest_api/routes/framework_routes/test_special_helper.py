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
Unit tests for the special (DataGerry Assistant) route helper.

Covers has_framework_data: False only when every collection is empty, True as soon as one is
non-empty, and the short-circuit (later managers are not counted once an earlier one is non-empty).
"""
from cmdb.interface.rest_api.routes.framework_routes.special_helper import has_framework_data
# -------------------------------------------------------------------------------------------------------------------- #


class _CountingManager:
    """Minimal stand-in exposing count_documents() and recording how many times it was called."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.calls = 0

    def count_documents(self) -> int:
        """Returns the configured count and records the call."""
        self.calls += 1
        return self._count


def test_returns_false_when_all_empty() -> None:
    """No categories, types, or objects -> False."""
    categories, types, objects = _CountingManager(0), _CountingManager(0), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is False
    # every collection had to be counted to conclude 'empty'
    assert (categories.calls, types.calls, objects.calls) == (1, 1, 1)


def test_true_when_categories_present_short_circuits() -> None:
    """A non-empty categories collection returns True without counting types/objects."""
    categories, types, objects = _CountingManager(1), _CountingManager(0), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is True
    assert (types.calls, objects.calls) == (0, 0)


def test_true_when_types_present_short_circuits() -> None:
    """A non-empty types collection returns True without counting objects."""
    categories, types, objects = _CountingManager(0), _CountingManager(2), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is True
    assert objects.calls == 0


def test_true_when_objects_present() -> None:
    """A non-empty objects collection returns True."""
    categories, types, objects = _CountingManager(0), _CountingManager(0), _CountingManager(3)

    assert has_framework_data(categories, types, objects) is True
