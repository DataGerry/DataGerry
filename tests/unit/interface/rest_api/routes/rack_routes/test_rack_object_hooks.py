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
Unit tests for the seam between the generic CmdbObject paths and the Rack feature

Three things worth asserting here rather than further in. That the seam is **cheap for everything that is
not a Rack** - the object write path runs for every object in the product, so a non-rack must cost one type
lookup and nothing else. That the delete ORDER holds - the members' location nodes are removed while the
mount rows still exist, since the mount rows are the only record of who the members are. And that the
location guard refuses exactly the moves it should, and that the membership reconcile writes the mount
row a location change now implies
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.rack_model.rack_mount_constants import RackArea
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    guard_rack_location_change,
    handle_object_deleted,
    handle_rack_object_updated,
    reconcile_object_rack_membership,
    resolve_rack_of_location_node,
)
# -------------------------------------------------------------------------------------------------------------------- #

HOOKS_PATH: str = 'cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks'

RACK_ID: int = 700
RACK_TYPE_ID: int = 70
PLAIN_TYPE_ID: int = 71
MEMBER_ID: int = 800
RACK_NODE_ID: int = 31

app = Flask(__name__)


def _types_manager() -> MagicMock:
    """A TypesManager where only RACK_TYPE_ID carries the RACK marker"""
    manager = MagicMock()

    def _get_type(type_id: int) -> dict[str, Any] | None:
        if type_id == RACK_TYPE_ID:
            return {'public_id': type_id, 'special_type': SpecialType.RACK.value}

        return {'public_id': type_id}

    manager.get_type.side_effect = _get_type

    return manager


def _rack_doc() -> dict[str, Any]:
    """A Rack CmdbObject document"""
    return {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID, 'fields': []}


def _plain_doc() -> dict[str, Any]:
    """An ordinary CmdbObject document"""
    return {'public_id': MEMBER_ID, 'type_id': PLAIN_TYPE_ID, 'fields': []}

# -------------------------------------------------------------------------------------------------------------------- #
#                                       handle_rack_object_updated                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_rack_write_applies_both_consequences() -> None:
    """The height rule and the location reconcile are the two things a rack write can trigger"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOKS_PATH}.handle_rack_height_change') as height, \
         patch(f'{HOOKS_PATH}.reconcile_member_locations') as reconcile:
        handle_rack_object_updated(
            MagicMock(), RACK_ID, _rack_doc(), _rack_doc(), MagicMock(), _types_manager(), MagicMock(),
        )

    height.assert_called_once()
    reconcile.assert_called_once()


def test_a_non_rack_write_costs_one_type_lookup_and_nothing_else() -> None:
    """
    This runs on EVERY object write in the product, so the non-rack path has to be cheap

    No manager is resolved and neither consequence is reached.
    """
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager') as provider, \
         patch(f'{HOOKS_PATH}.handle_rack_height_change') as height, \
         patch(f'{HOOKS_PATH}.reconcile_member_locations') as reconcile:
        handle_rack_object_updated(
            MagicMock(), MEMBER_ID, _plain_doc(), _plain_doc(), MagicMock(), _types_manager(), MagicMock(),
        )

    provider.assert_not_called()
    height.assert_not_called()
    reconcile.assert_not_called()


def test_the_locations_manager_is_reused_when_given() -> None:
    """The object write path already holds one, so the hook must not resolve a second"""
    locations_manager = MagicMock()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOKS_PATH}.handle_rack_height_change'), \
         patch(f'{HOOKS_PATH}.reconcile_member_locations') as reconcile:
        handle_rack_object_updated(
            MagicMock(), RACK_ID, _rack_doc(), _rack_doc(), MagicMock(), _types_manager(), locations_manager,
        )

    assert reconcile.call_args.args[3] is locations_manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_object_deleted                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_deleting_a_rack_detaches_the_members_before_dropping_the_rows() -> None:
    """
    The order is the whole point

    The mount rows are the only record of who the members are, so removing them first would leave every
    member stranded in the tree under a rack that no longer exists.
    """
    calls: list[str] = []

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOKS_PATH}.detach_all_member_locations', side_effect=lambda *a, **k: calls.append('detach')), \
         patch(f'{HOOKS_PATH}.delete_rack_memberships', side_effect=lambda *a, **k: calls.append('rows')):
        handle_object_deleted(MagicMock(), _rack_doc(), MagicMock(), _types_manager(), MagicMock())

    assert calls == ['detach', 'rows']


def test_deleting_a_member_drops_only_its_membership() -> None:
    """Its own location node is already handled by the generic object-delete path"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOKS_PATH}.detach_all_member_locations') as detach, \
         patch(f'{HOOKS_PATH}.delete_rack_memberships') as rows:
        handle_object_deleted(MagicMock(), _plain_doc(), MagicMock(), _types_manager(), MagicMock())

    detach.assert_not_called()
    rows.assert_called_once()


@pytest.mark.parametrize('public_id', [None, 'abc'], ids=str)
def test_a_malformed_document_is_a_no_op(public_id: Any) -> None:
    """Nothing identifiable to clean up"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager') as provider, \
         patch(f'{HOOKS_PATH}.delete_rack_memberships') as rows:
        handle_object_deleted(
            MagicMock(), {'public_id': public_id, 'type_id': PLAIN_TYPE_ID}, MagicMock(),
            _types_manager(), MagicMock(),
        )

    provider.assert_not_called()
    rows.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                       guard_rack_location_change                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

OTHER_NODE_ID: int = 32
OTHER_RACK_ID: int = 701


def _managers(mount: dict[str, Any] | None, candidate_type_id: int = PLAIN_TYPE_ID) -> MagicMock:
    """
    A ManagerProvider.get_manager stand-in serving the three managers the guard resolves

    The objects/types pair answers "is the object being moved a Rack?", the mounts manager answers
    "is it a member, and is it placed?"
    """
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.get_object.return_value = {'public_id': MEMBER_ID, 'type_id': candidate_type_id}

    types_manager = MagicMock(name='types_manager')
    types_manager.get_type.return_value = {
        'public_id': candidate_type_id,
        'special_type': SpecialType.RACK.value if candidate_type_id == RACK_TYPE_ID else None,
    }

    mounts_manager = MagicMock(name='rack_mounts_manager')
    mounts_manager.get_mount_of_object.return_value = mount

    def _get_manager(manager_type, _request_user=None):
        name: str = getattr(manager_type, 'name', str(manager_type))

        if name == 'OBJECTS':
            return objects_manager
        if name == 'TYPES':
            return types_manager

        return mounts_manager

    provider = MagicMock(side_effect=_get_manager)
    provider.objects_manager = objects_manager
    provider.types_manager = types_manager
    provider.mounts_manager = mounts_manager

    return provider


def _locations_manager(rack_node_id: int | None = RACK_NODE_ID,
                       node_owner_id: int | None = None) -> MagicMock:
    """A LocationsManager reporting the rack's own node and, optionally, who owns a requested node"""
    manager = MagicMock(name='locations_manager')
    manager.get_location_for_object.return_value = (
        {'public_id': rack_node_id} if rack_node_id is not None else None
    )
    manager.get_location.return_value = (
        {'public_id': OTHER_NODE_ID, 'object_id': node_owner_id} if node_owner_id is not None else None
    )

    return manager


def _mount(area: str = RackArea.UNASSIGNED.value, rack_id: int = RACK_ID) -> dict[str, Any]:
    """A membership row for MEMBER_ID in the given area"""
    return {'public_id': 900, 'rack_id': rack_id, 'object_id': MEMBER_ID, 'area': area}


def test_an_object_that_is_not_a_member_may_be_moved_freely() -> None:
    """The guard only speaks for rack members and for Racks"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(None)):
        guard_rack_location_change(MagicMock(), MEMBER_ID, 12, _locations_manager())


def test_a_member_pointed_at_its_own_rack_is_allowed() -> None:
    """
    That is exactly what the rack's own mirroring writes

    Refusing it would make the feature fight itself.
    """
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount(RackArea.FRONT.value))):
        guard_rack_location_change(MagicMock(), MEMBER_ID, RACK_NODE_ID, _locations_manager())


def test_a_member_re_pointed_at_its_own_rack_needs_no_license_check() -> None:
    """
    Nothing is being ADDED to a rack, so the licensed-surface check does not apply

    This is what an ordinary edit of a member sends back, on an instance that may well be unlicensed.
    """
    locations_manager = _locations_manager(rack_node_id=OTHER_NODE_ID, node_owner_id=RACK_ID)

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount(RackArea.FRONT.value))), \
         patch(f'{HOOKS_PATH}.resolve_rack_of_location_node', return_value=RACK_ID), \
         patch(f'{HOOKS_PATH}.abort_if_feature_locked') as feature_gate:
        guard_rack_location_change(MagicMock(), MEMBER_ID, OTHER_NODE_ID, locations_manager)

    feature_gate.assert_not_called()


def test_moving_a_placed_member_elsewhere_is_refused() -> None:
    """
    A placed member's slot is layout the rack view owns, and a location change cannot say what becomes
    of it - so the move is refused with the placement named
    """
    with app.test_request_context():
        with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount(RackArea.FRONT.value))):
            with pytest.raises(HTTPException) as err:
                guard_rack_location_change(MagicMock(), MEMBER_ID, 12, _locations_manager())

    assert err.value.code == 400
    assert str(RACK_ID) in err.value.description
    assert RackArea.FRONT.value in err.value.description


def test_clearing_a_placed_members_location_is_refused() -> None:
    """Clearing is a move like any other for a member that occupies slots"""
    with app.test_request_context():
        with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount(RackArea.FULL_DEPTH.value))):
            with pytest.raises(HTTPException) as err:
                guard_rack_location_change(MagicMock(), MEMBER_ID, None, _locations_manager())

    assert err.value.code == 400


def test_moving_an_unassigned_member_is_allowed() -> None:
    """
    Membership without placement has nothing to lose

    The membership row follows the location afterwards - that is reconcile_object_rack_membership's job,
    not the guard's.
    """
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount())):
        guard_rack_location_change(MagicMock(), MEMBER_ID, 12, _locations_manager())


def test_clearing_an_unassigned_members_location_is_allowed() -> None:
    """Same case with no new parent: the object simply leaves the rack"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount())):
        guard_rack_location_change(MagicMock(), MEMBER_ID, None, _locations_manager())


def test_a_placed_member_of_a_rack_without_a_location_may_be_saved() -> None:
    """
    Its rack is not in the tree, so its own location is empty and every edit sends None

    Reading that as "left the rack" would refuse ordinary edits of the object.
    """
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(_mount(RackArea.BACK.value))):
        guard_rack_location_change(MagicMock(), MEMBER_ID, None, _locations_manager(rack_node_id=None))


def test_a_rack_pointed_into_another_rack_is_refused() -> None:
    """Racks do not nest, so the placement that would have to mean membership is refused instead"""
    locations_manager = _locations_manager(node_owner_id=OTHER_RACK_ID)

    with app.test_request_context():
        with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', _managers(None, RACK_TYPE_ID)):
            with pytest.raises(HTTPException) as err:
                guard_rack_location_change(MagicMock(), MEMBER_ID, OTHER_NODE_ID, locations_manager)

    assert err.value.code == 400
    assert 'nest' in err.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                    reconcile_object_rack_membership                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def _reconcile_managers(mount: dict[str, Any] | None) -> tuple[MagicMock, MagicMock, MagicMock]:
    """The (objects, types, mounts) trio the reconcile works with, mounts reporting the given membership"""
    objects_manager = MagicMock(name='objects_manager')
    types_manager = MagicMock(name='types_manager')
    mounts_manager = MagicMock(name='rack_mounts_manager')
    mounts_manager.get_mount_of_object.return_value = mount

    return objects_manager, types_manager, mounts_manager


def test_pointing_an_object_at_a_rack_creates_an_unassigned_membership() -> None:
    """The gap this closes: a location that names a rack now really puts the object in it"""
    objects_manager, types_manager, mounts_manager = _reconcile_managers(None)
    locations_manager = _locations_manager()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager), \
         patch(f'{HOOKS_PATH}.resolve_rack_of_location_node', return_value=RACK_ID), \
         patch(f'{HOOKS_PATH}.member_object_blocker', return_value=(MEMBER_ID, None)):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, OTHER_NODE_ID, objects_manager, types_manager, locations_manager,
        )

    written = mounts_manager.insert_item.call_args.args[0]
    assert written['rack_id'] == RACK_ID
    assert written['object_id'] == MEMBER_ID
    assert written['area'] == RackArea.UNASSIGNED.value
    mounts_manager.delete_item.assert_not_called()


def test_clearing_the_location_of_an_unassigned_member_removes_the_membership() -> None:
    """The symmetric half: leaving the rack's node in the tree means leaving the rack"""
    objects_manager, types_manager, mounts_manager = _reconcile_managers(_mount())
    locations_manager = _locations_manager()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager), \
         patch(f'{HOOKS_PATH}.resolve_rack_of_location_node', return_value=None):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, None, objects_manager, types_manager, locations_manager,
        )

    mounts_manager.delete_item.assert_called_once_with(900)
    mounts_manager.insert_item.assert_not_called()


def test_moving_an_unassigned_member_to_another_rack_moves_the_membership() -> None:
    """One membership at a time: the old row goes before the new one is written"""
    objects_manager, types_manager, mounts_manager = _reconcile_managers(_mount())
    locations_manager = _locations_manager()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager), \
         patch(f'{HOOKS_PATH}.resolve_rack_of_location_node', return_value=OTHER_RACK_ID), \
         patch(f'{HOOKS_PATH}.member_object_blocker', return_value=(MEMBER_ID, None)):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, OTHER_NODE_ID, objects_manager, types_manager, locations_manager,
        )

    mounts_manager.delete_item.assert_called_once_with(900)
    assert mounts_manager.insert_item.call_args.args[0]['rack_id'] == OTHER_RACK_ID


def test_a_member_still_under_its_own_rack_is_left_alone() -> None:
    """An ordinary edit re-sends the same parent; nothing about the membership changed"""
    objects_manager, types_manager, mounts_manager = _reconcile_managers(_mount())
    locations_manager = _locations_manager()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, RACK_NODE_ID, objects_manager, types_manager, locations_manager,
        )

    mounts_manager.delete_item.assert_not_called()
    mounts_manager.insert_item.assert_not_called()


def test_a_placed_member_of_a_location_less_rack_keeps_its_membership() -> None:
    """
    Its rack is not in the tree, so an edit sends None - and dropping the row would silently unmount it

    The guard lets this write through precisely because it changes nothing, so the reconcile must agree.
    """
    objects_manager, types_manager, mounts_manager = _reconcile_managers(_mount(RackArea.FRONT.value))
    locations_manager = _locations_manager(rack_node_id=None)

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, None, objects_manager, types_manager, locations_manager,
        )

    mounts_manager.delete_item.assert_not_called()
    mounts_manager.insert_item.assert_not_called()


def test_an_object_the_rack_view_would_refuse_gets_no_membership() -> None:
    """
    The picker's own rules decide who may be a member, so no membership is invented behind its back

    The location still stands - the one case where the tree says more than the rack does.
    """
    objects_manager, types_manager, mounts_manager = _reconcile_managers(None)
    locations_manager = _locations_manager()

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=mounts_manager), \
         patch(f'{HOOKS_PATH}.resolve_rack_of_location_node', return_value=RACK_ID), \
         patch(f'{HOOKS_PATH}.member_object_blocker', return_value=(None, 'no location field')):
        reconcile_object_rack_membership(
            _request_user(), MEMBER_ID, OTHER_NODE_ID, objects_manager, types_manager, locations_manager,
        )

    mounts_manager.insert_item.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                      resolve_rack_of_location_node                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_node_owned_by_a_rack_resolves_to_that_rack() -> None:
    """The rack's OWN node is what membership is read from"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID}
    types_manager = MagicMock()
    types_manager.get_type.return_value = {'public_id': RACK_TYPE_ID, 'special_type': SpecialType.RACK.value}

    resolved = resolve_rack_of_location_node(
        OTHER_NODE_ID, objects_manager, types_manager, _locations_manager(node_owner_id=RACK_ID),
    )

    assert resolved == RACK_ID


def test_a_node_owned_by_an_ordinary_object_resolves_to_nothing() -> None:
    """A location under a rack, or anywhere else, says nothing about membership"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': 55, 'type_id': PLAIN_TYPE_ID}
    types_manager = MagicMock()
    types_manager.get_type.return_value = {'public_id': PLAIN_TYPE_ID, 'special_type': None}

    resolved = resolve_rack_of_location_node(
        OTHER_NODE_ID, objects_manager, types_manager, _locations_manager(node_owner_id=55),
    )

    assert resolved is None


def test_no_requested_parent_resolves_to_nothing() -> None:
    """Nothing was asked for, so no rack is named"""
    assert resolve_rack_of_location_node(None, MagicMock(), MagicMock(), MagicMock()) is None


def _request_user() -> MagicMock:
    """A CmdbUser stub answering the accessor the membership row records"""
    request_user = MagicMock()
    request_user.get_public_id.return_value = 1

    return request_user
