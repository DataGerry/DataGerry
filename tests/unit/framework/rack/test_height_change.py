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
Unit tests for cmdb.framework.rack.height_change

The rule is that lowering a Rack's height UNPLACES what no longer fits - the object stays a member and
keeps its height as a re-placing hint, so nothing is ever lost. Covered here: which mounts count as
beyond the height (a mount ending exactly at the top still fits), that unplacing is one bulk write with
distinct positions, that growing or keeping the height does nothing at all, and that the hook is a no-op
for anything that is not a Rack
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.rack_model.rack_mount_constants import RackArea
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.rack_model.rack_mount_helpers import top_slot_of
from cmdb.framework.rack.height_change import (
    build_unplace_operations,
    find_mounts_beyond_height,
    get_height_conflicts,
    handle_rack_height_change,
    read_rack_height,
    unplace_mounts_beyond_height,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
RACK_TYPE_ID: int = 70
PLAIN_TYPE_ID: int = 71


def _mount(public_id: int, area: str, start_slot: Any = None, height: Any = None) -> dict[str, Any]:
    """Builds a stored mount document"""
    return {
        'public_id': public_id,
        'rack_id': RACK_ID,
        'object_id': 800 + public_id,
        'area': area,
        'start_slot': start_slot,
        'height': height,
        'position': None,
    }


def _rack(height: Any) -> dict[str, Any]:
    """Builds a Rack CmdbObject document carrying the given height"""
    return {
        'public_id': RACK_ID,
        'type_id': RACK_TYPE_ID,
        'fields': [{'name': RackField.HEIGHT.value, 'value': height, 'type': 'number'}],
    }


def _types_manager(is_rack: bool = True) -> MagicMock:
    """A TypesManager resolving the rack type id to RACK or to an ordinary type"""
    manager = MagicMock()
    manager.get_type.return_value = (
        {'public_id': RACK_TYPE_ID, 'special_type': SpecialType.RACK.value} if is_rack
        else {'public_id': RACK_TYPE_ID}
    )

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                top_slot_of                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_top_slot_is_the_anchor() -> None:
    """
    A mount grows downward, so nothing it occupies is above its start slot

    A 3U mount at slot 10 covers 10, 9 and 8 - its top is 10.
    """
    assert top_slot_of(_mount(1, RackArea.FRONT.value, 10, 3)) == 10


def test_a_one_u_mount_tops_out_where_it_starts() -> None:
    """The degenerate case"""
    assert top_slot_of(_mount(1, RackArea.FRONT.value, 10, 1)) == 10


@pytest.mark.parametrize('area', [RackArea.LEFT.value, RackArea.RIGHT.value, RackArea.UNASSIGNED.value])
def test_a_mount_without_slots_has_no_last_slot(area: str) -> None:
    """
    Side and unassigned mounts can never be affected by a height change

    None rather than 0, so they are not mistaken for occupying slot 0.
    """
    assert top_slot_of(_mount(1, area, 10, 3)) is None


@pytest.mark.parametrize('mount', [
    {'public_id': 1, 'area': 'GARBAGE', 'start_slot': 1, 'height': 2},
    {'public_id': 2, 'area': RackArea.FRONT.value, 'start_slot': None, 'height': 2},
    {'public_id': 3, 'area': RackArea.FRONT.value, 'start_slot': 1, 'height': None},
], ids=str)
def test_a_drifted_mount_has_no_last_slot(mount: dict[str, Any]) -> None:
    """A bad row is left alone by the shrink rather than crashing it"""
    assert top_slot_of(mount) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                          find_mounts_beyond_height                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_mount_anchored_exactly_at_the_new_top_still_fits() -> None:
    """The boundary is inclusive - shrinking to exactly the anchor displaces nothing"""
    assert find_mounts_beyond_height([_mount(1, RackArea.FRONT.value, 10, 2)], 10) == []


def test_a_mount_anchored_above_the_new_top_is_displaced() -> None:
    """One U over is over. A mount grows downward, so only its anchor decides"""
    displaced = find_mounts_beyond_height([_mount(1, RackArea.FRONT.value, 10, 2)], 9)

    assert [m['public_id'] for m in displaced] == [1]


def test_a_tall_mount_reaching_below_the_new_top_is_still_displaced() -> None:
    """
    The anchor is what matters, not where the mount reaches down to

    A 6U mount anchored at 12 covers 12 down to 7; shrinking to 10 leaves its top outside the rack, so
    it goes to the bucket rather than being silently truncated.
    """
    displaced = find_mounts_beyond_height([_mount(1, RackArea.FRONT.value, 12, 6)], 10)

    assert [m['public_id'] for m in displaced] == [1]


def test_only_the_offenders_are_displaced() -> None:
    """A shrink is not a reset - everything that still fits stays where it is"""
    mounts = [
        _mount(1, RackArea.FRONT.value, 2, 2),
        _mount(2, RackArea.FRONT.value, 20, 2),
        _mount(3, RackArea.BACK.value, 19, 4),
    ]

    displaced = find_mounts_beyond_height(mounts, 10)

    assert sorted(m['public_id'] for m in displaced) == [2, 3]


def test_a_full_depth_mount_is_displaced_once() -> None:
    """It occupies two views but is one row"""
    displaced = find_mounts_beyond_height([_mount(1, RackArea.FULL_DEPTH.value, 20, 1)], 10)

    assert len(displaced) == 1


def test_side_and_unassigned_mounts_are_never_displaced() -> None:
    """They hold no slots, so no height can push them out"""
    mounts = [
        _mount(1, RackArea.LEFT.value),
        _mount(2, RackArea.UNASSIGNED.value, height=40),
    ]

    assert find_mounts_beyond_height(mounts, 1) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                           get_height_conflicts                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_conflict_read_asks_only_for_the_main_areas() -> None:
    """Nothing outside a main area can be affected, so nothing else is read"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = []

    get_height_conflicts(manager, RACK_ID, 10)

    _, areas = manager.get_mounts_in_areas.call_args.args
    assert areas == {area.value for area in RackArea.get_main_areas()}

# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_unplace_operations                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_unplacing_clears_the_slot_and_keeps_the_height() -> None:
    """
    The height survives as a re-placing hint, the slot does not

    The height is the tedious value to re-enter; the slot is what the user picks when re-placing.
    """
    operations = build_unplace_operations([_mount(1, RackArea.FRONT.value, 20, 3)], 0)

    update = operations[0]._doc['$set']  # pylint: disable=protected-access

    assert update['area'] == RackArea.UNASSIGNED.value
    assert update['start_slot'] is None
    assert 'height' not in update


def test_each_displaced_mount_gets_its_own_position() -> None:
    """
    Distinct positions are why this is a bulk write of many operations, not one update_many

    A single $set cannot give each row a different index, and the unassigned bucket has no geometry to
    fall back on for its order.
    """
    mounts = [_mount(1, RackArea.FRONT.value, 20, 1), _mount(2, RackArea.BACK.value, 21, 1)]

    operations = build_unplace_operations(mounts, 4)

    positions = [op._doc['$set']['position'] for op in operations]  # pylint: disable=protected-access
    assert positions == [4, 5]


def test_each_operation_targets_one_mount_by_id() -> None:
    """The filter is the mount's identity, so no other row can be touched"""
    operations = build_unplace_operations([_mount(7, RackArea.FRONT.value, 20, 1)], 0)

    assert operations[0]._filter == {'public_id': 7}  # pylint: disable=protected-access


def test_no_operations_for_nothing_to_unplace() -> None:
    """An empty input produces no write"""
    assert build_unplace_operations([], 0) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                       unplace_mounts_beyond_height                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_unplacing_writes_once_and_reports_the_mounts() -> None:
    """One bulk write for the whole displacement, however many mounts it covers"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = [
        _mount(1, RackArea.FRONT.value, 20, 1), _mount(2, RackArea.FRONT.value, 30, 1),
    ]
    manager.get_next_position.return_value = 0

    assert unplace_mounts_beyond_height(manager, RACK_ID, 10) == [1, 2]
    assert manager.bulk_write.call_count == 1


def test_unplacing_appends_after_the_existing_bucket() -> None:
    """Displaced mounts go to the end of the unassigned bucket, not over what is already there"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = [_mount(1, RackArea.FRONT.value, 20, 1)]
    manager.get_next_position.return_value = 7

    unplace_mounts_beyond_height(manager, RACK_ID, 10)

    operations = manager.bulk_write.call_args.args[0]
    assert operations[0]._doc['$set']['position'] == 7  # pylint: disable=protected-access


def test_nothing_is_written_when_everything_still_fits() -> None:
    """A shrink that displaces nothing performs no write at all"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = [_mount(1, RackArea.FRONT.value, 2, 2)]

    assert unplace_mounts_beyond_height(manager, RACK_ID, 10) == []
    manager.bulk_write.assert_not_called()


def test_unplacing_is_re_run_safe() -> None:
    """
    A second pass finds nothing, because the mounts it moved no longer carry slot geometry

    That is what makes the post-write hook safe to reach twice.
    """
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = [_mount(1, RackArea.UNASSIGNED.value, None, 3)]

    assert unplace_mounts_beyond_height(manager, RACK_ID, 10) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_rack_height_change                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def _mounts_manager(displaced: list[dict[str, Any]] | None = None) -> MagicMock:
    """A RackMountsManager returning the given mounts from the conflict read"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = displaced or []
    manager.get_next_position.return_value = 0

    return manager


def test_a_shrink_unplaces_the_offenders() -> None:
    """The whole point: 42U down to 10U displaces the mount at 20"""
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    unplaced = handle_rack_height_change(_types_manager(), manager, RACK_ID, _rack(10), _rack(42))

    assert unplaced == [1]


def test_growing_a_rack_changes_nothing() -> None:
    """More room cannot displace anything, so no read even happens"""
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    assert handle_rack_height_change(_types_manager(), manager, RACK_ID, _rack(60), _rack(42)) == []
    manager.get_mounts_in_areas.assert_not_called()


def test_an_unchanged_height_changes_nothing() -> None:
    """An ordinary edit to a rack's name must not touch its layout"""
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    assert handle_rack_height_change(_types_manager(), manager, RACK_ID, _rack(42), _rack(42)) == []
    manager.get_mounts_in_areas.assert_not_called()


def test_an_insert_changes_nothing() -> None:
    """There is no previous height on an insert, and a new rack holds no mounts"""
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    assert handle_rack_height_change(_types_manager(), manager, RACK_ID, _rack(10), None) == []


def test_a_non_rack_object_is_untouched() -> None:
    """The hook sits on the generic object write path, so it must ignore everything else"""
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    assert handle_rack_height_change(_types_manager(is_rack=False), manager, RACK_ID,
                                     _rack(10), _rack(42)) == []
    manager.get_mounts_in_areas.assert_not_called()


@pytest.mark.parametrize('new_height, old_height', [(None, 42), (42, None), ('abc', 42)], ids=str)
def test_an_unreadable_height_is_left_alone(new_height: Any, old_height: Any) -> None:
    """
    A height that cannot be compared must not be guessed at

    Doing nothing leaves the mounts exactly as they were, which is always recoverable.
    """
    manager = _mounts_manager([_mount(1, RackArea.FRONT.value, 20, 1)])

    assert handle_rack_height_change(_types_manager(), manager, RACK_ID,
                                     _rack(new_height), _rack(old_height)) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                              read_rack_height                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('stored, expected', [(42, 42), ('42', 42), (42.0, 42)], ids=str)
def test_the_height_is_read_and_coerced(stored: Any, expected: int) -> None:
    """The same coercion the write invariants apply"""
    assert read_rack_height(_rack(stored)) == expected


@pytest.mark.parametrize('stored', [None, '', 'abc', 3.5], ids=str)
def test_an_unusable_height_reads_as_none(stored: Any) -> None:
    """None is what makes the hook decline to act"""
    assert read_rack_height(_rack(stored)) is None
