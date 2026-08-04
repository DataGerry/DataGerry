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
member-location guard refuses exactly the moves it should
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    guard_member_location_change,
    handle_object_deleted,
    handle_rack_object_updated,
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
#                                     guard_member_location_change                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def _mounts_manager(mount: dict[str, Any] | None) -> MagicMock:
    """A RackMountsManager reporting the given membership for the object"""
    manager = MagicMock()
    manager.get_mount_of_object.return_value = mount

    return manager


def test_an_object_that_is_not_a_member_may_be_moved_freely() -> None:
    """The guard only speaks for rack members"""
    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=_mounts_manager(None)):
        guard_member_location_change(MagicMock(), MEMBER_ID, 12, MagicMock())


def test_a_member_pointed_at_its_own_rack_is_allowed() -> None:
    """
    That is exactly what the rack's own mirroring writes

    Refusing it would make the feature fight itself.
    """
    locations_manager = MagicMock()
    locations_manager.get_location_for_object.return_value = {'public_id': RACK_NODE_ID}
    mount = {'public_id': 900, 'rack_id': RACK_ID, 'object_id': MEMBER_ID}

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=_mounts_manager(mount)):
        guard_member_location_change(MagicMock(), MEMBER_ID, RACK_NODE_ID, locations_manager)


def test_moving_a_member_elsewhere_is_refused() -> None:
    """
    W9e: the rack owns where its members sit

    Without this a user could point a member anywhere from the object form and the tree would disagree with
    the rack until something re-reconciled it.
    """
    locations_manager = MagicMock()
    locations_manager.get_location_for_object.return_value = {'public_id': RACK_NODE_ID}
    mount = {'public_id': 900, 'rack_id': RACK_ID, 'object_id': MEMBER_ID}

    with app.test_request_context():
        with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=_mounts_manager(mount)):
            with pytest.raises(HTTPException) as err:
                guard_member_location_change(MagicMock(), MEMBER_ID, 12, locations_manager)

    assert err.value.code == 400
    assert str(RACK_ID) in err.value.description


def test_clearing_a_members_location_is_refused() -> None:
    """Removing it from the tree by hand is a move like any other - take it out of the rack instead"""
    locations_manager = MagicMock()
    locations_manager.get_location_for_object.return_value = {'public_id': RACK_NODE_ID}
    mount = {'public_id': 900, 'rack_id': RACK_ID, 'object_id': MEMBER_ID}

    with app.test_request_context():
        with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=_mounts_manager(mount)):
            with pytest.raises(HTTPException) as err:
                guard_member_location_change(MagicMock(), MEMBER_ID, None, locations_manager)

    assert err.value.code == 400


def test_a_member_of_a_rack_without_a_location_may_be_cleared() -> None:
    """
    Its rack is not in the tree, so None is what the rack's own mirroring would produce

    Nothing to conflict with.
    """
    locations_manager = MagicMock()
    locations_manager.get_location_for_object.return_value = None
    mount = {'public_id': 900, 'rack_id': RACK_ID, 'object_id': MEMBER_ID}

    with patch(f'{HOOKS_PATH}.ManagerProvider.get_manager', return_value=_mounts_manager(mount)):
        guard_member_location_change(MagicMock(), MEMBER_ID, None, locations_manager)
