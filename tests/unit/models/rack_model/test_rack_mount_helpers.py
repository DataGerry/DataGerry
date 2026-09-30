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
Unit tests for cmdb.models.rack_model.rack_mount_helpers - the interval arithmetic

Pure, no database. A mount occupies the U range ``start_slot - height + 1 .. start_slot``, and the
helpers answer questions about that range from its two ends: how many U it holds, what two mounts
share, and how a set of ranges is named in a message. The last class pins the property the ranges are
used for: the overlap check and the overview tally never enumerate the U they cover, so their cost does
not grow with a mount's height.
"""
from typing import Any

import pytest

from cmdb.framework.rack.mount_validator import find_slot_conflicts
from cmdb.framework.rack.overview import build_occupants_legend
from cmdb.framework.rack.rack_constants import RackOverviewKey
from cmdb.models.rack_model import rack_mount_helpers
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey, RackMountKind
from cmdb.models.rack_model.rack_mount_helpers import (
    format_slot_ranges,
    merge_slot_ranges,
    occupied_slot_count,
    occupied_slots_of,
    overlapping_slot_range,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Far beyond any rack, so a helper that built one member per U would run out of memory instead of passing
VAST_HEIGHT: int = 10 ** 12


def _mount(start_slot: Any, height: Any, area: str = RackArea.FRONT.value, **extra: Any) -> dict[str, Any]:
    """A mount document with the given geometry."""
    return {
        RackMountKey.AREA.value: area,
        RackMountKey.START_SLOT.value: start_slot,
        RackMountKey.HEIGHT.value: height,
        **extra,
    }


class TestOccupiedSlotCount:
    """How many U a mount holds."""

    def test_counts_the_range(self) -> None:
        """A 3U mount at slot 25 holds 25, 24 and 23"""
        assert occupied_slot_count(_mount(25, 3)) == 3

    def test_agrees_with_the_enumerated_slots(self) -> None:
        """The count and the set describe the same range"""
        mount = _mount(10, 4)

        assert occupied_slot_count(mount) == len(occupied_slots_of(mount))

    @pytest.mark.parametrize('mount', [
        _mount(5, 2, area=RackArea.LEFT.value),
        _mount(5, 2, area=RackArea.UNASSIGNED.value),
        _mount(None, 2),
        _mount(5, 0),
        _mount(5, 'x'),
        {},
    ], ids=['side', 'unassigned', 'no-start', 'zero-height', 'garbage-height', 'empty'])
    def test_a_mount_without_geometry_holds_nothing(self, mount: dict[str, Any]) -> None:
        """A side, unassigned or drifted row blocks no U"""
        assert occupied_slot_count(mount) == 0


class TestOverlappingSlotRange:
    """What two mounts both occupy."""

    @pytest.mark.parametrize('first, second, expected', [
        (_mount(10, 3), _mount(9, 2), (8, 9)),      # partial overlap
        (_mount(10, 5), _mount(8, 1), (8, 8)),      # nested
        (_mount(10, 3), _mount(10, 3), (8, 10)),    # identical
        (_mount(10, 3), _mount(8, 1), (8, 8)),      # touching the bottom U
    ], ids=['partial', 'nested', 'identical', 'touching'])
    def test_colliding_mounts_share_a_range(
            self, first: dict[str, Any], second: dict[str, Any], expected: tuple[int, int],
    ) -> None:
        """The shared range is (the higher bottom, the lower top) - and it is symmetric"""
        assert overlapping_slot_range(first, second) == expected
        assert overlapping_slot_range(second, first) == expected

    @pytest.mark.parametrize('first, second', [
        (_mount(10, 3), _mount(7, 2)),              # adjacent: 8-10 and 6-7
        (_mount(10, 3), _mount(3, 1)),              # disjoint
    ], ids=['adjacent', 'disjoint'])
    def test_separate_mounts_share_nothing(self, first: dict[str, Any], second: dict[str, Any]) -> None:
        """Adjacent is not overlapping"""
        assert overlapping_slot_range(first, second) is None

    def test_a_mount_without_geometry_collides_with_nothing(self) -> None:
        """A drifted row must not make every placement in the rack impossible"""
        assert overlapping_slot_range(_mount(10, 3), _mount(None, 3)) is None


class TestNamingRanges:
    """How contested slots appear in a message."""

    def test_merges_overlapping_and_adjacent_ranges(self) -> None:
        """Touching or overlapping pieces become one range, ascending"""
        assert merge_slot_ranges([(8, 9), (1, 1), (10, 12), (9, 10)]) == [(1, 1), (8, 12)]

    def test_merging_nothing_is_nothing(self) -> None:
        """An empty input stays empty"""
        assert not merge_slot_ranges([])

    def test_formats_single_slots_and_ranges(self) -> None:
        """A one-U range is named as that U"""
        assert format_slot_ranges([(9, 10), (1, 1), (3, 3)]) == 'U1, U3, U9-U10'

    def test_the_text_does_not_grow_with_the_height(self) -> None:
        """A collision over a vast range is still one short range"""
        assert format_slot_ranges([(1, VAST_HEIGHT)]) == f'U1-U{VAST_HEIGHT}'


class TestNoRequestPathEnumeratesTheSlots:
    """
    The overlap check and the overview tally work on the ends of a range only

    `range` is replaced inside the helpers module, so any request path that still built one member per
    U would raise here rather than merely run slowly.
    """

    @pytest.fixture(autouse=True)
    def _forbid_enumeration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Makes enumerating a mount's slots fail loudly."""
        def _refuse(*_args: Any) -> None:
            raise AssertionError('a request path enumerated the slots of a mount')

        monkeypatch.setattr(rack_mount_helpers, 'range', _refuse, raising=False)

    def test_the_overlap_check_does_not_enumerate(self) -> None:
        """Two vast mounts collide, and the message names the shared range"""
        errors = find_slot_conflicts(
            _mount(VAST_HEIGHT, VAST_HEIGHT),
            [_mount(VAST_HEIGHT, VAST_HEIGHT, public_id=7)],
        )

        assert len(errors) == 1
        assert f'U1-U{VAST_HEIGHT}' in errors[0]

    def test_the_occupants_legend_does_not_enumerate(self) -> None:
        """The slot tally of a vast reservation is its height"""
        legend = build_occupants_legend([_mount(VAST_HEIGHT, VAST_HEIGHT, kind=RackMountKind.RESERVATION.value)])

        assert legend[0][RackOverviewKey.SLOTS.value] == VAST_HEIGHT
