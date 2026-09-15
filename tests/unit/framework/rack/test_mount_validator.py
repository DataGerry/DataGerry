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
Unit tests for cmdb.framework.rack.mount_validator

Pure, no database. **A mount is anchored at its start_slot and extends DOWNWARD** - slot 1 is the bottom
of the rack, so a 3U mount at 25 occupies 25, 24 and 23. Covers the area check, the per-area shape rules
(a main area needs geometry, a side does not), the fit inside the rack at BOTH ends, and the overlap rules - including the two that are easy to
get wrong: a FULL_DEPTH mount blocks the front AND the back because it occupies the same U range in
both views, and the mount being moved must be excluded from its own comparison or re-slotting would
always collide with where it currently is
"""
from typing import Any

import pytest

from cmdb.models.rack_model.rack_mount_constants import RackArea
from cmdb.framework.rack.rack_constants import RackMountLimits
from cmdb.models.rack_model.rack_mount_helpers import occupied_slots_of
from cmdb.framework.rack.mount_validator import (
    coerce_slot_value,
    find_slot_conflicts,
    validate_area,
    validate_mount_fits_rack,
    validate_mount_placement,
    validate_mount_shape,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_HEIGHT: int = 42


def _mount(area: Any, start_slot: Any = None, height: Any = None,
           position: Any = None, public_id: int | None = None) -> dict[str, Any]:
    """Builds a mount document with only the keys the validators read"""
    mount: dict[str, Any] = {
        'area': area,
        'start_slot': start_slot,
        'height': height,
        'position': position,
    }

    if public_id is not None:
        mount['public_id'] = public_id

    return mount

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 coerce_slot_value                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [(3, 3), (3.0, 3), ('3', 3), (' 12 ', 12), (0, 0), (-1, -1)], ids=str)
def test_coerce_slot_value_accepts_whole_numbers(value: Any, expected: int) -> None:
    """Whole numbers in any of the shapes a client can send are coerced; range is checked elsewhere"""
    assert coerce_slot_value(value) == expected


@pytest.mark.parametrize('value', [3.5, '3.5', 'abc', None, '', True, False, [], {}], ids=str)
def test_coerce_slot_value_rejects_anything_else(value: Any) -> None:
    """A fractional slot is not a slot, and bool must not slip through as an int subclass"""
    assert coerce_slot_value(value) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   validate_area                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('area', list(RackArea), ids=str)
def test_validate_area_accepts_every_member(area: RackArea) -> None:
    """Every declared area is valid, so a new member does not need a validator change"""
    assert validate_area(area.value) == []


@pytest.mark.parametrize('area', ['NOPE', '', None, 'front', 1], ids=str)
def test_validate_area_rejects_anything_else(area: Any) -> None:
    """An unknown area is reported with the allowed set, and the check is case-sensitive"""
    errors = validate_area(area)

    assert len(errors) == 1
    assert 'FRONT' in errors[0]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_mount_shape                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('area', sorted(a.value for a in RackArea.get_main_areas()))
def test_shape_requires_geometry_in_a_main_area(area: str) -> None:
    """A placement without a start slot or a height is not a placement"""
    errors = validate_mount_shape(_mount(area))

    assert len(errors) == 2
    assert any('start slot' in error for error in errors)
    assert any('height' in error for error in errors)


@pytest.mark.parametrize('area', sorted(a.value for a in RackArea.get_main_areas()))
def test_shape_accepts_complete_main_geometry(area: str) -> None:
    """A start slot and a height are all a main-area mount needs"""
    assert validate_mount_shape(_mount(area, start_slot=1, height=2)) == []


@pytest.mark.parametrize('area', [RackArea.LEFT.value, RackArea.RIGHT.value, RackArea.UNASSIGNED.value])
def test_shape_requires_no_geometry_outside_the_main_areas(area: str) -> None:
    """Side lists and the unassigned bucket carry no geometry at all"""
    assert validate_mount_shape(_mount(area)) == []


@pytest.mark.parametrize('start_slot', [0, -1, 3.5, 'abc'], ids=str)
def test_shape_rejects_an_unusable_start_slot(start_slot: Any) -> None:
    """U numbering starts at 1, and a slot is always a whole number"""
    errors = validate_mount_shape(_mount(RackArea.FRONT.value, start_slot=start_slot, height=1))

    assert any('start slot' in error for error in errors)


@pytest.mark.parametrize('height', [0, -2, 1.5, 'abc'], ids=str)
def test_shape_rejects_an_unusable_height(height: Any) -> None:
    """A mount occupies at least one whole U"""
    errors = validate_mount_shape(_mount(RackArea.FRONT.value, start_slot=1, height=height))

    assert any('height of a mount' in error for error in errors)


def test_shape_range_checks_a_height_kept_on_an_unplaced_mount() -> None:
    """
    The height retained as a re-placing hint is still validated

    An unplaced mount keeps its height so re-placing can pre-fill it - but a nonsense hint would then
    be pre-filled, so it is checked even where it is not required.
    """
    errors = validate_mount_shape(_mount(RackArea.UNASSIGNED.value, height=0))

    assert any('height of a mount' in error for error in errors)


@pytest.mark.parametrize('position', [-1, 2.5, 'abc'], ids=str)
def test_shape_rejects_an_unusable_position(position: Any) -> None:
    """The order index of an ordered area is a whole number from zero up"""
    errors = validate_mount_shape(_mount(RackArea.LEFT.value, position=position))

    assert any('position' in error for error in errors)


def test_shape_accepts_the_lowest_position() -> None:
    """The ordering is zero-based, so 0 is a valid position"""
    assert validate_mount_shape(_mount(RackArea.LEFT.value, position=RackMountLimits.MIN_POSITION)) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_mount_fits_rack                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_mount_anchored_at_the_very_top_fits() -> None:
    """The topmost slot is usable, and the mount grows downward from it into the rack"""
    assert validate_mount_fits_rack(_mount(RackArea.FRONT.value, start_slot=42, height=2), RACK_HEIGHT) == []


def test_a_mount_anchored_above_the_top_does_not_fit() -> None:
    """The anchor itself may not sit above the rack, and the message names the rack height"""
    errors = validate_mount_fits_rack(_mount(RackArea.FRONT.value, start_slot=43, height=1), RACK_HEIGHT)

    assert len(errors) == 1
    assert '42' in errors[0]


def test_a_one_u_mount_at_the_top_fits() -> None:
    """The boundary case: the very top slot alone"""
    assert validate_mount_fits_rack(_mount(RackArea.BACK.value, start_slot=42, height=1), RACK_HEIGHT) == []


def test_a_mount_reaching_below_the_floor_does_not_fit() -> None:
    """
    A mount grows downward, so a tall one anchored low leaves the rack at the BOTTOM

    3U anchored at slot 2 would need slots 2, 1 and 0 - and there is no slot 0.
    """
    errors = validate_mount_fits_rack(_mount(RackArea.FRONT.value, start_slot=2, height=3), RACK_HEIGHT)

    assert len(errors) == 1
    assert 'below the bottom' in errors[0]


def test_a_mount_reaching_exactly_to_the_floor_fits() -> None:
    """2U anchored at slot 2 occupies 2 and 1, which is the whole bottom of the rack"""
    assert validate_mount_fits_rack(_mount(RackArea.FRONT.value, start_slot=2, height=2), RACK_HEIGHT) == []


def test_a_mount_filling_the_whole_rack_fits() -> None:
    """Anchored at the top with the rack's full height reaches exactly to slot 1"""
    mount = _mount(RackArea.FRONT.value, start_slot=RACK_HEIGHT, height=RACK_HEIGHT)

    assert validate_mount_fits_rack(mount, RACK_HEIGHT) == []


def test_both_ends_are_reported_together() -> None:
    """A mount taller than the rack overshoots the top and the floor at once"""
    errors = validate_mount_fits_rack(_mount(RackArea.FRONT.value, start_slot=43, height=50), RACK_HEIGHT)

    assert len(errors) == 2


@pytest.mark.parametrize('area', [RackArea.LEFT.value, RackArea.UNASSIGNED.value])
def test_a_mount_without_slots_always_fits(area: str) -> None:
    """Side and unassigned mounts occupy no slots, so the rack height cannot constrain them"""
    assert validate_mount_fits_rack(_mount(area, height=99), RACK_HEIGHT) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                                find_slot_conflicts                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_no_conflict_when_ranges_do_not_touch() -> None:
    """Two mounts in the same area with disjoint ranges coexist (10/h3 covers 8-10, 4/h4 covers 1-4)"""
    existing = [_mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5)]

    assert find_slot_conflicts(_mount(RackArea.FRONT.value, start_slot=4, height=4), existing) == []


def test_overlapping_ranges_in_the_same_area_conflict() -> None:
    """The existing mount covers 8-10; a new one covering 9-10 collides on both"""
    existing = [_mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5)]

    errors = find_slot_conflicts(_mount(RackArea.FRONT.value, start_slot=10, height=2), existing)

    assert len(errors) == 1
    assert '[9, 10]' in errors[0]
    assert '[5]' in errors[0]


def test_front_and_back_do_not_conflict_with_each_other() -> None:
    """The two views are independent - the same U can hold one mount in each"""
    existing = [_mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5)]

    assert find_slot_conflicts(_mount(RackArea.BACK.value, start_slot=10, height=3), existing) == []


def test_a_full_depth_mount_blocks_the_front() -> None:
    """A full-depth mount occupies its U range in both views, so the front is taken too"""
    existing = [_mount(RackArea.FULL_DEPTH.value, start_slot=20, height=2, public_id=6)]

    assert find_slot_conflicts(_mount(RackArea.FRONT.value, start_slot=20, height=1), existing) != []


def test_a_full_depth_mount_blocks_the_back() -> None:
    """The same holds for the back view"""
    existing = [_mount(RackArea.FULL_DEPTH.value, start_slot=20, height=2, public_id=6)]

    assert find_slot_conflicts(_mount(RackArea.BACK.value, start_slot=19, height=1), existing) != []


def test_a_full_depth_placement_is_blocked_by_a_front_mount() -> None:
    """And the reverse: a full-depth mount cannot be placed where either view is occupied"""
    existing = [_mount(RackArea.FRONT.value, start_slot=30, height=1, public_id=7)]

    assert find_slot_conflicts(_mount(RackArea.FULL_DEPTH.value, start_slot=30, height=1), existing) != []


def test_a_full_depth_placement_is_blocked_by_a_back_mount() -> None:
    """A back-only mount also stands in the way of a full-depth one"""
    existing = [_mount(RackArea.BACK.value, start_slot=30, height=1, public_id=8)]

    assert find_slot_conflicts(_mount(RackArea.FULL_DEPTH.value, start_slot=30, height=1), existing) != []


def test_side_mounts_conflict_with_nothing() -> None:
    """A side list has no geometry, so nothing can collide there"""
    existing = [_mount(RackArea.LEFT.value, position=0, public_id=9)]

    assert find_slot_conflicts(_mount(RackArea.LEFT.value, position=0), existing) == []


def test_the_mount_being_moved_is_excluded_from_its_own_check() -> None:
    """
    Without this, re-slotting a mount would always collide with where it already is

    Here the mount keeps its exact slots, which must be allowed.
    """
    existing = [_mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5)]

    conflicts = find_slot_conflicts(
        _mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5), existing, exclude_mount_id=5,
    )

    assert conflicts == []


def test_excluding_one_mount_does_not_excuse_a_conflict_with_another() -> None:
    """The exclusion is a single mount, not a free pass"""
    existing = [
        _mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5),
        _mount(RackArea.FRONT.value, start_slot=20, height=2, public_id=6),
    ]

    conflicts = find_slot_conflicts(
        _mount(RackArea.FRONT.value, start_slot=20, height=1, public_id=5), existing, exclude_mount_id=5,
    )

    assert conflicts != []


def test_a_malformed_existing_mount_blocks_nothing() -> None:
    """A drifted row must not make every placement fail"""
    existing = [
        {'public_id': 5, 'area': 'GARBAGE', 'start_slot': 1, 'height': 99},
        {'public_id': 6, 'area': RackArea.FRONT.value},
    ]

    assert find_slot_conflicts(_mount(RackArea.FRONT.value, start_slot=1, height=2), existing) == []


def test_several_conflicting_mounts_are_all_named() -> None:
    """One message lists every contested slot and every mount holding one"""
    existing = [
        _mount(RackArea.FRONT.value, start_slot=1, height=1, public_id=5),
        _mount(RackArea.FULL_DEPTH.value, start_slot=3, height=1, public_id=6),
    ]

    errors = find_slot_conflicts(_mount(RackArea.FRONT.value, start_slot=3, height=3), existing)

    assert '[1, 3]' in errors[0]
    assert '[5, 6]' in errors[0]

# -------------------------------------------------------------------------------------------------------------------- #
#                                             validate_mount_placement                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_placement_short_circuits_on_an_invalid_area() -> None:
    """Nothing downstream can be judged without a valid area, so only that is reported"""
    errors = validate_mount_placement(_mount('NOPE', start_slot=0), RACK_HEIGHT, [])

    assert len(errors) == 1
    assert 'valid Rack area' in errors[0]


def test_placement_short_circuits_on_a_broken_shape() -> None:
    """
    A mount with no start slot is not measured against the rack

    Reporting "would end past the rack height" for a mount that has no start slot at all would just
    bury the real problem.
    """
    existing = [_mount(RackArea.FRONT.value, start_slot=1, height=40, public_id=5)]

    errors = validate_mount_placement(_mount(RackArea.FRONT.value), RACK_HEIGHT, existing)

    assert all('occupied' not in error for error in errors)
    assert any('start slot' in error for error in errors)


def test_placement_reports_the_fit_and_the_overlap_together() -> None:
    """Once the shape holds, both remaining rules run so the caller sees every problem at once"""
    existing = [_mount(RackArea.FRONT.value, start_slot=3, height=1, public_id=5)]

    errors = validate_mount_placement(_mount(RackArea.FRONT.value, start_slot=3, height=5), RACK_HEIGHT, existing)

    assert len(errors) == 2


def test_a_valid_placement_reports_nothing() -> None:
    """The happy path"""
    existing = [_mount(RackArea.FRONT.value, start_slot=10, height=3, public_id=5)]

    assert validate_mount_placement(_mount(RackArea.FRONT.value, start_slot=2, height=2), RACK_HEIGHT, existing) == []


def test_an_unassigned_mount_is_always_a_valid_placement() -> None:
    """Membership without placement cannot conflict with anything"""
    existing = [_mount(RackArea.FRONT.value, start_slot=1, height=42, public_id=5)]

    assert validate_mount_placement(_mount(RackArea.UNASSIGNED.value), RACK_HEIGHT, existing) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                       standalone robustness of the helpers                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_fits_rack_passes_a_main_area_mount_with_incomplete_geometry() -> None:
    """
    Measuring a mount that has no start slot yet is not this rule's job

    validate_mount_placement never gets here (the shape rules run first), but the function must stay
    safe when called on its own.
    """
    assert validate_mount_fits_rack(_mount(RackArea.FRONT.value, height=3), RACK_HEIGHT) == []


def test_conflicts_are_empty_for_a_candidate_without_slots() -> None:
    """A candidate occupying nothing can collide with nothing, whatever else is in the rack"""
    existing = [_mount(RackArea.FRONT.value, start_slot=1, height=42, public_id=5)]

    assert find_slot_conflicts(_mount(RackArea.FRONT.value), existing) == []


@pytest.mark.parametrize('mount, reason', [
    ({'area': 'GARBAGE', 'start_slot': 1, 'height': 2}, 'unknown area'),
    ({'area': RackArea.LEFT.value, 'start_slot': 1, 'height': 2}, 'side area'),
    ({'area': RackArea.UNASSIGNED.value, 'height': 2}, 'unplaced'),
    ({'area': RackArea.FRONT.value, 'height': 2}, 'no start slot'),
    ({'area': RackArea.FRONT.value, 'start_slot': 1}, 'no height'),
    ({'area': RackArea.FRONT.value, 'start_slot': 1, 'height': 0}, 'zero height'),
], ids=lambda value: value if isinstance(value, str) else '')
def test_a_mount_without_usable_main_geometry_occupies_nothing(mount: dict[str, Any], reason: str) -> None:
    """
    The slot computation is safe on any document shape

    A drifted row must block nothing rather than raise, or one bad row would make every placement in
    the rack impossible.
    """
    del reason
    assert occupied_slots_of(mount) == set()


def test_occupied_slots_span_downward_from_the_anchor() -> None:
    """A 3U mount anchored at 5 occupies 5, 4 and 3 - it grows toward the bottom of the rack"""
    assert occupied_slots_of({'area': RackArea.FRONT.value, 'start_slot': 5, 'height': 3}) == {3, 4, 5}
