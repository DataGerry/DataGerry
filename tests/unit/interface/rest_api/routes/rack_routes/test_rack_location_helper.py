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
Unit tests for the rack location mirroring

There is one mechanism: the member's own location field is driven to the rack's node and the ordinary mirror
writes the node. Only a type declaring a location field may be mounted, so there is no second branch - the
picker and the mount write both refuse the rest.

Covered here: that the field is written before the mirror runs (the field is the record, the node derives
from it), that MOVING a member to another rack re-points its existing node rather than replacing it, that
the tree follows MEMBERSHIP (so nothing here is triggered by unplacing), that leaving the rack DELETES the
member's node rather than promoting it, and that the reconcile is a reconcile - it reads the rack's current
node and needs no before/after comparison
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.interface.rest_api.routes.rack_routes.rack_location_helper import (
    attach_all_member_locations,
    attach_member_location,
    detach_all_member_locations,
    detach_member_location,
    get_member_object_ids,
    get_rack_location_node,
    handle_mount_created,
    handle_mount_removed,
    reconcile_member_locations,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.rack_routes.rack_location_helper'

RACK_ID: int = 700
RACK_NODE_ID: int = 31
MEMBER_ID: int = 800
OTHER_MEMBER_ID: int = 801
MEMBER_TYPE_ID: int = 60
MEMBER_NODE_ID: int = 32


def _type() -> SimpleNamespace:
    """A CmdbType stand-in for a mountable member - every one of them declares a location field"""
    fields: list[dict[str, Any]] = [
        {'type': FieldType.TEXT.value, 'name': 'dg-name'},
        {'type': FieldType.LOCATION.value, 'name': 'dg_location'},
    ]

    return SimpleNamespace(
        public_id=MEMBER_TYPE_ID,
        label='Member',
        fields=fields,
        get_icon=lambda: 'fa-cube',
    )


def _objects_manager(member_exists: bool = True) -> MagicMock:
    """An ObjectsManager returning one mountable member object"""
    manager = MagicMock()
    manager.get_object.return_value = (
        {'public_id': MEMBER_ID, 'type_id': MEMBER_TYPE_ID} if member_exists else None
    )
    manager.get_object_type.return_value = _type()

    return manager


def _locations_manager(member_node: dict[str, Any] | None = None,
                       rack_node: dict[str, Any] | None = None) -> MagicMock:
    """A LocationsManager answering get_location_for_object per object id"""
    manager = MagicMock()

    def _get(object_id: int) -> dict[str, Any] | None:
        if object_id == RACK_ID:
            return rack_node

        return member_node

    manager.get_location_for_object.side_effect = _get

    return manager


def _mounts_manager(member_ids: list[int] | None = None) -> MagicMock:
    """A RackMountsManager whose rack holds the given members"""
    manager = MagicMock()
    manager.get_mounts_of_rack.return_value = [
        {'public_id': 900 + index, 'object_id': member_id, 'rack_id': RACK_ID}
        for index, member_id in enumerate(member_ids or [])
    ]

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     attach                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_member_gets_its_location_field_driven() -> None:
    """
    The field is the record and the node is derived from it

    So the field is written first and the ordinary mirror writes the node - which is what makes the node
    survive the object's next save.
    """
    objects_manager = _objects_manager()
    locations_manager = _locations_manager()

    with patch(f'{HELPER_PATH}.sync_object_location') as sync:
        attach_member_location(
            MEMBER_ID, RACK_NODE_ID, MagicMock(), objects_manager, locations_manager,
        )

    objects_manager.set_location_field_for_objects.assert_called_once_with([MEMBER_ID], RACK_NODE_ID)
    assert sync.call_args.args[0] == MEMBER_ID
    assert sync.call_args.args[1] == RACK_NODE_ID


def test_the_attach_writes_no_node_itself() -> None:
    """It must not bypass the mirror - that would produce a node the next save disagrees with"""
    locations_manager = _locations_manager()

    with patch(f'{HELPER_PATH}.sync_object_location'):
        attach_member_location(
            MEMBER_ID, RACK_NODE_ID, MagicMock(), _objects_manager(), locations_manager,
        )

    locations_manager.insert_location.assert_not_called()


def test_moving_a_member_re_points_its_node_instead_of_replacing_it() -> None:
    """
    A member arriving from another rack already has a node, and it has to survive the move

    The mirror updates the parent of an existing node, so the node keeps its public_id and anything hanging
    beneath the moved object rides along. Deleting and recreating would promote those children onto the OLD
    rack and hand out a new node id.
    """
    existing = {'public_id': MEMBER_NODE_ID, 'object_id': MEMBER_ID, 'parent': 99}
    locations_manager = _locations_manager(member_node=existing)

    with patch(f'{HELPER_PATH}.sync_object_location') as sync:
        attach_member_location(
            MEMBER_ID, RACK_NODE_ID, MagicMock(), _objects_manager(), locations_manager,
        )

    locations_manager.delete_location.assert_not_called()
    assert sync.call_args.args[1] == RACK_NODE_ID


def test_a_missing_member_object_is_skipped() -> None:
    """Nothing to place"""
    locations_manager = _locations_manager()

    attach_member_location(
        MEMBER_ID, RACK_NODE_ID, MagicMock(), _objects_manager(member_exists=False), locations_manager,
    )

    locations_manager.insert_location.assert_not_called()


def test_a_failure_is_swallowed_rather_than_rolled_back() -> None:
    """
    The membership is already written and must not be undone over a tree side effect

    Same best-effort contract sync_object_location already has.
    """
    objects_manager = _objects_manager()
    objects_manager.get_object.side_effect = RuntimeError('boom')

    attach_member_location(
        MEMBER_ID, RACK_NODE_ID, MagicMock(), objects_manager, _locations_manager(),
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     detach                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_leaving_the_rack_deletes_the_node() -> None:
    """
    By decision the node goes rather than being promoted onto whatever was above the rack

    An object's place in the tree came from the rack, so it leaves with the rack.
    """
    existing = {'public_id': MEMBER_NODE_ID, 'object_id': MEMBER_ID, 'parent': RACK_NODE_ID}
    locations_manager = _locations_manager(member_node=existing)

    detach_member_location(MEMBER_ID, MagicMock(), MagicMock(), locations_manager)

    locations_manager.delete_location.assert_called_once_with(MEMBER_NODE_ID)


def test_leaving_the_rack_clears_the_objects_location_field() -> None:
    """
    Otherwise the field would dangle at a node that no longer exists

    A dangling field fails validate_object_location_change on the object's next edit.
    """
    objects_manager = MagicMock()

    detach_member_location(MEMBER_ID, MagicMock(), objects_manager, _locations_manager())

    objects_manager.clear_location_field_for_objects.assert_called_once_with([MEMBER_ID])


def test_the_field_is_cleared_even_without_a_node() -> None:
    """A field pointing at an already-gone node must not linger"""
    objects_manager = MagicMock()
    locations_manager = _locations_manager(member_node=None)

    detach_member_location(MEMBER_ID, MagicMock(), objects_manager, locations_manager)

    objects_manager.clear_location_field_for_objects.assert_called_once_with([MEMBER_ID])
    locations_manager.delete_location.assert_not_called()


def test_a_detach_failure_is_swallowed() -> None:
    """Best-effort, like the attach"""
    locations_manager = _locations_manager()
    locations_manager.get_location_for_object.side_effect = RuntimeError('boom')

    detach_member_location(MEMBER_ID, MagicMock(), MagicMock(), locations_manager)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            membership enumeration                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_member_of_the_rack_is_enumerated() -> None:
    """Placed and unplaced alike - the tree follows membership"""
    manager = _mounts_manager([MEMBER_ID, OTHER_MEMBER_ID])

    assert get_member_object_ids(manager, RACK_ID) == [MEMBER_ID, OTHER_MEMBER_ID]


def test_a_mount_without_an_integer_object_id_is_skipped() -> None:
    """A drifted row must not reach the per-member work"""
    manager = MagicMock()
    manager.get_mounts_of_rack.return_value = [{'public_id': 900, 'object_id': None}]

    assert get_member_object_ids(manager, RACK_ID) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  reconcile                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_rack_with_a_location_places_every_member() -> None:
    """The rack gained or moved to a location, so the members follow it"""
    rack_node = {'public_id': RACK_NODE_ID, 'object_id': RACK_ID, 'parent': 12}
    locations_manager = _locations_manager(rack_node=rack_node)

    with patch(f'{HELPER_PATH}.attach_member_location') as attach:
        count = reconcile_member_locations(
            RACK_ID, MagicMock(), MagicMock(), locations_manager,
            _mounts_manager([MEMBER_ID, OTHER_MEMBER_ID]),
        )

    assert count == 2
    assert attach.call_count == 2
    assert {call.args[1] for call in attach.call_args_list} == {RACK_NODE_ID}


def test_a_rack_without_a_location_removes_every_member() -> None:
    """
    The rack lost its location, so its members leave the tree with it

    By decision they are NOT promoted onto the rack's former parent.
    """
    locations_manager = _locations_manager(rack_node=None)

    with patch(f'{HELPER_PATH}.detach_member_location') as detach:
        count = reconcile_member_locations(
            RACK_ID, MagicMock(), MagicMock(), locations_manager,
            _mounts_manager([MEMBER_ID, OTHER_MEMBER_ID]),
        )

    assert count == 2
    assert detach.call_count == 2


def test_the_reconcile_needs_no_before_and_after() -> None:
    """
    It reads the rack's CURRENT node and acts on that

    Which is why the same call is correct for gaining, moving and losing a location - and why running it
    twice changes nothing.
    """
    rack_node = {'public_id': RACK_NODE_ID, 'object_id': RACK_ID, 'parent': 12}
    locations_manager = _locations_manager(rack_node=rack_node)
    mounts_manager = _mounts_manager([MEMBER_ID])

    with patch(f'{HELPER_PATH}.attach_member_location') as attach:
        reconcile_member_locations(
            RACK_ID, MagicMock(), MagicMock(), locations_manager, mounts_manager,
        )
        reconcile_member_locations(
            RACK_ID, MagicMock(), MagicMock(), locations_manager, mounts_manager,
        )

    assert attach.call_count == 2


def test_a_rack_with_no_members_reconciles_to_nothing() -> None:
    """The cheap common case"""
    locations_manager = _locations_manager(rack_node={'public_id': RACK_NODE_ID})

    with patch(f'{HELPER_PATH}.attach_member_location') as attach:
        assert reconcile_member_locations(
            RACK_ID, MagicMock(), MagicMock(), locations_manager, _mounts_manager([]),
        ) == 0

    attach.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              mount triggers                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_new_membership_places_the_member() -> None:
    """The tree follows membership, so joining is enough - no slot required"""
    rack_node = {'public_id': RACK_NODE_ID, 'object_id': RACK_ID}
    locations_manager = _locations_manager(rack_node=rack_node)

    with patch(f'{HELPER_PATH}.attach_member_location') as attach:
        handle_mount_created(
            RACK_ID, MEMBER_ID, MagicMock(), MagicMock(), locations_manager,
        )

    attach.assert_called_once()
    assert attach.call_args.args[1] == RACK_NODE_ID


def test_a_new_membership_in_a_rack_without_a_location_does_nothing() -> None:
    """
    There is nowhere to hang the member

    It will be placed later if the rack is ever given a location - that is what the reconcile is for.
    """
    locations_manager = _locations_manager(rack_node=None)

    with patch(f'{HELPER_PATH}.attach_member_location') as attach, \
         patch(f'{HELPER_PATH}.detach_member_location') as detach:
        handle_mount_created(
            RACK_ID, MEMBER_ID, MagicMock(), MagicMock(), locations_manager,
        )

    attach.assert_not_called()
    detach.assert_not_called()


def test_a_member_moved_into_a_rack_without_a_location_leaves_the_tree() -> None:
    """
    It still sits under the rack it came from, so doing nothing would show it in a rack it left

    This is the one case where the two differ: a member that was never in a rack has no node to worry
    about, while a moved one does.
    """
    locations_manager = _locations_manager(rack_node=None)

    with patch(f'{HELPER_PATH}.detach_member_location') as detach:
        handle_mount_created(
            RACK_ID, MEMBER_ID, MagicMock(), MagicMock(), locations_manager, moved_from_rack=True,
        )

    detach.assert_called_once()


def test_a_member_moved_into_a_rack_with_a_location_is_re_attached() -> None:
    """The ordinary path - the move is the attach, which re-points the node it already has"""
    locations_manager = _locations_manager(rack_node={'public_id': RACK_NODE_ID, 'object_id': RACK_ID})

    with patch(f'{HELPER_PATH}.attach_member_location') as attach, \
         patch(f'{HELPER_PATH}.detach_member_location') as detach:
        handle_mount_created(
            RACK_ID, MEMBER_ID, MagicMock(), MagicMock(), locations_manager, moved_from_rack=True,
        )

    attach.assert_called_once()
    assert attach.call_args.args[1] == RACK_NODE_ID
    detach.assert_not_called()


def test_removing_a_membership_detaches_the_member() -> None:
    """Leaving the rack means leaving the tree"""
    with patch(f'{HELPER_PATH}.detach_member_location') as detach:
        handle_mount_removed(MEMBER_ID, MagicMock(), MagicMock(), MagicMock())

    detach.assert_called_once()


def test_attach_all_reports_the_number_of_members() -> None:
    """Used by the reconcile to report what it did"""
    with patch(f'{HELPER_PATH}.attach_member_location'):
        assert attach_all_member_locations(
            RACK_ID, RACK_NODE_ID, MagicMock(), MagicMock(), MagicMock(),
            _mounts_manager([MEMBER_ID, OTHER_MEMBER_ID]),
        ) == 2


def test_detach_all_reports_the_number_of_members() -> None:
    """The mirror image"""
    with patch(f'{HELPER_PATH}.detach_member_location'):
        assert detach_all_member_locations(
            RACK_ID, MagicMock(), MagicMock(), MagicMock(), _mounts_manager([MEMBER_ID]),
        ) == 1


def test_the_rack_node_lookup_is_by_the_racks_own_object_id() -> None:
    """The rack is an object like any other, so its node is found the same way"""
    rack_node = {'public_id': RACK_NODE_ID}
    manager = MagicMock()
    manager.get_location_for_object.return_value = rack_node

    assert get_rack_location_node(manager, RACK_ID) == rack_node
    manager.get_location_for_object.assert_called_once_with(RACK_ID)
