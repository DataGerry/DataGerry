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
Unit tests for cmdb.manager.rack_mounts_manager

DB-free: the manager is built via __new__ and its BaseManager query methods are replaced, so each test
asserts the criteria the manager builds rather than what Mongo returns. Covers the read helpers, the
append-position computation, the bulk deletes and the second-membership check
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.models.rack_model import RackArea
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.rack_mounts_manager import (
    RackMountsManagerGetError,
    RackMountsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
OBJECT_ID: int = 800
MOUNT_ID: int = 900


def _manager() -> RackMountsManager:
    """Builds a RackMountsManager without touching a database"""
    return RackMountsManager.__new__(RackMountsManager)


def _mount(public_id: int, **overrides: Any) -> dict[str, Any]:
    """Builds a stored mount document"""
    mount: dict[str, Any] = {
        'public_id': public_id,
        'rack_id': RACK_ID,
        'object_id': OBJECT_ID,
        'area': RackArea.FRONT.value,
        'position': None,
    }
    mount.update(overrides)

    return mount

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_mount_of_object                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_mount_of_object_queries_by_object_id() -> None:
    """One rack per object, so the lookup is a single-document read"""
    manager = _manager()
    manager.get_one_by = MagicMock(return_value=_mount(MOUNT_ID))

    assert manager.get_mount_of_object(OBJECT_ID)['public_id'] == MOUNT_ID
    manager.get_one_by.assert_called_once_with({'object_id': OBJECT_ID})


def test_get_mount_of_object_wraps_a_base_error() -> None:
    """A BaseManager failure surfaces as the manager's own error type"""
    manager = _manager()
    manager.get_one_by = MagicMock(side_effect=BaseManagerGetError('boom'))

    with pytest.raises(RackMountsManagerGetError):
        manager.get_mount_of_object(OBJECT_ID)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_mounts_of_rack                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_mounts_of_rack_without_an_area_filters_on_the_rack_only() -> None:
    """No area given means every area of the rack"""
    manager = _manager()
    manager.find = MagicMock(return_value=[])

    manager.get_mounts_of_rack(RACK_ID)

    manager.find.assert_called_once_with(criteria={'rack_id': RACK_ID})


def test_get_mounts_of_rack_with_an_area_filters_on_both() -> None:
    """An area narrows the read to the compound index's exact key"""
    manager = _manager()
    manager.find = MagicMock(return_value=[])

    manager.get_mounts_of_rack(RACK_ID, RackArea.LEFT.value)

    manager.find.assert_called_once_with(criteria={'rack_id': RACK_ID, 'area': RackArea.LEFT.value})


def test_get_unassigned_mounts_filters_on_the_unassigned_bucket() -> None:
    """The convenience wrapper targets exactly the unplaced members"""
    manager = _manager()
    manager.find = MagicMock(return_value=[])

    manager.get_unassigned_mounts(RACK_ID)

    manager.find.assert_called_once_with(criteria={'rack_id': RACK_ID, 'area': RackArea.UNASSIGNED.value})

# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_mounts_in_areas                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_mounts_in_areas_uses_one_query_for_every_area() -> None:
    """
    The overlap check needs several areas at once

    A full-depth placement competes with all three main areas; doing one read per area would be an
    avoidable N+1 on every mount write.
    """
    manager = _manager()
    manager.find = MagicMock(return_value=[])

    manager.get_mounts_in_areas(RACK_ID, {RackArea.FRONT.value, RackArea.FULL_DEPTH.value})

    manager.find.assert_called_once_with(criteria={
        'rack_id': RACK_ID,
        'area': {'$in': [RackArea.FRONT.value, RackArea.FULL_DEPTH.value]},
    })


def test_get_mounts_in_areas_skips_the_query_for_an_empty_set() -> None:
    """A side or unassigned placement competes with nothing, so it must not query at all"""
    manager = _manager()
    manager.find = MagicMock()

    assert manager.get_mounts_in_areas(RACK_ID, set()) == []
    manager.find.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_next_position                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_next_position_is_zero_for_an_empty_area() -> None:
    """The ordering is zero-based"""
    manager = _manager()
    manager.find = MagicMock(return_value=[])

    assert manager.get_next_position(RACK_ID, RackArea.LEFT.value) == 0


def test_next_position_appends_after_the_highest_in_use() -> None:
    """A new member goes to the end of the list, not into a gap"""
    manager = _manager()
    manager.find = MagicMock(return_value=[
        _mount(1, position=0), _mount(2, position=4), _mount(3, position=2),
    ])

    assert manager.get_next_position(RACK_ID, RackArea.LEFT.value) == 5


def test_next_position_ignores_mounts_without_a_position() -> None:
    """A row with no position must not break the append"""
    manager = _manager()
    manager.find = MagicMock(return_value=[_mount(1, position=None), _mount(2, position=1)])

    assert manager.get_next_position(RACK_ID, RackArea.LEFT.value) == 2

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    deletes                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_delete_mounts_of_rack_is_one_statement() -> None:
    """Deleting a rack removes every membership in one operation, not a per-mount loop"""
    manager = _manager()
    manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=3))

    assert manager.delete_mounts_of_rack(RACK_ID) == 3
    manager.delete_many.assert_called_once_with({'rack_id': RACK_ID})


def test_delete_mount_of_object_targets_the_object() -> None:
    """Deleting the mounted object removes its membership so no mount dangles"""
    manager = _manager()
    manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=1))

    assert manager.delete_mount_of_object(OBJECT_ID) == 1
    manager.delete_many.assert_called_once_with({'object_id': OBJECT_ID})


def test_delete_wraps_a_failure() -> None:
    """A delete failure surfaces as the manager's own error type"""
    manager = _manager()
    manager.delete_many = MagicMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RackMountsManagerDeleteError):
        manager.delete_mounts_of_rack(RACK_ID)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              is_object_mounted                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_is_object_mounted_false_when_the_object_is_free() -> None:
    """An unmounted object may be mounted anywhere"""
    manager = _manager()
    manager.get_one_by = MagicMock(return_value=None)

    assert manager.is_object_mounted(OBJECT_ID) is False


def test_is_object_mounted_true_when_another_mount_holds_it() -> None:
    """A second membership is refused - including into the same rack twice"""
    manager = _manager()
    manager.get_one_by = MagicMock(return_value=_mount(MOUNT_ID))

    assert manager.is_object_mounted(OBJECT_ID) is True


def test_is_object_mounted_excludes_the_mount_being_updated() -> None:
    """
    A mount is allowed to keep holding its own object

    Without the exclusion every PATCH of a mount would fail its own membership check.
    """
    manager = _manager()
    manager.get_one_by = MagicMock(return_value=_mount(MOUNT_ID))

    assert manager.is_object_mounted(OBJECT_ID, exclude_mount_id=MOUNT_ID) is False


def test_is_object_mounted_still_reports_a_different_mount_when_excluding() -> None:
    """The exclusion is one specific mount, not a blanket pass"""
    manager = _manager()
    manager.get_one_by = MagicMock(return_value=_mount(MOUNT_ID))

    assert manager.is_object_mounted(OBJECT_ID, exclude_mount_id=MOUNT_ID + 1) is True

# -------------------------------------------------------------------------------------------------------------------- #
#                                            count_mounts_of_rack                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_count_mounts_of_rack_counts_every_member() -> None:
    """Placed and unplaced members alike count as membership"""
    manager = _manager()
    manager.count_documents = MagicMock(return_value=7)

    assert manager.count_mounts_of_rack(RACK_ID) == 7
    manager.count_documents.assert_called_once_with({'rack_id': RACK_ID})

# -------------------------------------------------------------------------------------------------------------------- #
#                                              error wrapping                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('method, args', [
    ('get_mounts_of_rack', (RACK_ID,)),
    ('get_mounts_in_areas', (RACK_ID, {RackArea.FRONT.value})),
], ids=str)
def test_a_failed_read_surfaces_as_the_managers_get_error(method: str, args: tuple) -> None:
    """Every read wraps a raw failure, so a route never has to catch a pymongo error"""
    manager = _manager()
    manager.find = MagicMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RackMountsManagerGetError):
        getattr(manager, method)(*args)


def test_a_failed_count_surfaces_as_the_managers_get_error() -> None:
    """The count is a read like any other"""
    manager = _manager()
    manager.count_documents = MagicMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RackMountsManagerGetError):
        manager.count_mounts_of_rack(RACK_ID)


def test_a_failed_object_delete_surfaces_as_the_managers_delete_error() -> None:
    """Both bulk deletes wrap their failures"""
    manager = _manager()
    manager.delete_many = MagicMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RackMountsManagerDeleteError):
        manager.delete_mount_of_object(OBJECT_ID)
