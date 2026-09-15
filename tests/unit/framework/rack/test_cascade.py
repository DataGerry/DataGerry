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
Unit tests for cmdb.framework.rack.cascade

A mount row references two objects, so either of them being deleted would leave it dangling. Asserts the
right side is cleaned up for each role - a deleted Rack loses every membership, a deleted member loses its
own - and that neither is done with a per-row loop
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.rack.cascade import delete_rack_memberships
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
RACK_TYPE_ID: int = 70
PLAIN_TYPE_ID: int = 71
OBJECT_ID: int = 800


def _types_manager() -> MagicMock:
    """A TypesManager where only RACK_TYPE_ID carries the RACK marker"""
    manager = MagicMock()

    def _get_type(type_id: int) -> dict[str, Any] | None:
        if type_id == RACK_TYPE_ID:
            return {'public_id': type_id, 'special_type': SpecialType.RACK.value}

        if type_id == PLAIN_TYPE_ID:
            return {'public_id': type_id}

        return None

    manager.get_type.side_effect = _get_type

    return manager


def _mounts_manager(rack_removals: int = 0, object_removals: int = 0) -> MagicMock:
    """A RackMountsManager reporting the given delete counts"""
    manager = MagicMock()
    manager.delete_mounts_of_rack.return_value = rack_removals
    manager.delete_mount_of_object.return_value = object_removals

    return manager

# -------------------------------------------------------------------------------------------------------------------- #

def test_deleting_a_rack_removes_every_membership() -> None:
    """The rack is gone, so nothing can still be mounted in it"""
    manager = _mounts_manager(rack_removals=3)

    removed = delete_rack_memberships(
        _types_manager(), manager, {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID},
    )

    assert removed == 3
    manager.delete_mounts_of_rack.assert_called_once_with(RACK_ID)


def test_deleting_a_rack_does_not_touch_the_mounted_objects() -> None:
    """
    Deleting a rack deletes the rack, not the devices that were in it

    Only the membership rows go; nothing here reaches into the objects.
    """
    manager = _mounts_manager(rack_removals=2)

    delete_rack_memberships(_types_manager(), manager, {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID})

    manager.delete_mount_of_object.assert_not_called()


def test_deleting_a_mounted_object_removes_its_own_membership() -> None:
    """The rack survives with a free slot"""
    manager = _mounts_manager(object_removals=1)

    removed = delete_rack_memberships(
        _types_manager(), manager, {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID},
    )

    assert removed == 1
    manager.delete_mount_of_object.assert_called_once_with(OBJECT_ID)
    manager.delete_mounts_of_rack.assert_not_called()


def test_deleting_an_unmounted_object_removes_nothing() -> None:
    """The lookup is cheap and finds nothing to do"""
    manager = _mounts_manager(object_removals=0)

    assert delete_rack_memberships(
        _types_manager(), manager, {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID},
    ) == 0


@pytest.mark.parametrize('public_id', [None, 'abc', 1.5], ids=str)
def test_a_malformed_object_id_is_a_no_op(public_id: Any) -> None:
    """A drifted document short-circuits before any write"""
    manager = _mounts_manager()

    assert delete_rack_memberships(
        _types_manager(), manager, {'public_id': public_id, 'type_id': PLAIN_TYPE_ID},
    ) == 0
    manager.delete_mount_of_object.assert_not_called()
    manager.delete_mounts_of_rack.assert_not_called()


def test_an_object_of_a_missing_type_is_treated_as_a_member() -> None:
    """
    A type that no longer resolves is not a Rack, so the object's own membership is what goes

    Deleting every membership of it would be the destructive guess; this is the safe one.
    """
    manager = _mounts_manager(object_removals=1)

    delete_rack_memberships(_types_manager(), manager, {'public_id': OBJECT_ID, 'type_id': 999})

    manager.delete_mount_of_object.assert_called_once_with(OBJECT_ID)


def test_deleting_an_empty_rack_removes_nothing() -> None:
    """A rack that held nothing has no memberships to drop"""
    manager = _mounts_manager(rack_removals=0)

    assert delete_rack_memberships(
        _types_manager(), manager, {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID},
    ) == 0
    manager.delete_mounts_of_rack.assert_called_once_with(RACK_ID)
