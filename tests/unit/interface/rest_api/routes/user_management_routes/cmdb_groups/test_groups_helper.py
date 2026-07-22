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
Unit tests for the CmdbUserGroup route helper ``resolve_move_target``

Pure tests with a stubbed GroupsManager: a non-MOVE action resolves to None without a lookup; a
MOVE without a target id aborts 400; a MOVE whose target is missing aborts 404; a valid MOVE returns
the resolved target group. flask.abort raises a werkzeug HTTPException, so the status codes are
asserted without a Flask app context
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.group_model import GroupDeleteMode
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_helper import resolve_move_target
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_GROUP_ID: int = 42


def _manager(target: object = None) -> MagicMock:
    """A stub GroupsManager whose get_group returns the given target."""
    manager = MagicMock()
    manager.get_group.return_value = target
    return manager


def test_non_move_action_returns_none_without_lookup() -> None:
    """DELETE (any non-MOVE action) resolves to None and never looks a group up."""
    manager = _manager()

    assert resolve_move_target(manager, GroupDeleteMode.DELETE, TARGET_GROUP_ID) is None
    manager.get_group.assert_not_called()


def test_none_action_returns_none_without_lookup() -> None:
    """A missing action (plain delete) resolves to None and never looks a group up."""
    manager = _manager()

    assert resolve_move_target(manager, None, None) is None
    manager.get_group.assert_not_called()


def test_move_without_target_id_aborts_400() -> None:
    """MOVE without a target id is a bad request."""
    manager = _manager()

    with pytest.raises(HTTPException) as exc_info:
        resolve_move_target(manager, GroupDeleteMode.MOVE, None)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    manager.get_group.assert_not_called()


def test_move_with_missing_target_aborts_404() -> None:
    """MOVE to a target group that does not exist is a not-found."""
    manager = _manager(target=None)

    with pytest.raises(HTTPException) as exc_info:
        resolve_move_target(manager, GroupDeleteMode.MOVE, TARGET_GROUP_ID)

    assert exc_info.value.code == HTTPStatus.NOT_FOUND
    manager.get_group.assert_called_once_with(TARGET_GROUP_ID)


def test_valid_move_returns_target_group() -> None:
    """A MOVE to an existing target returns that target group."""
    target_group = MagicMock(name='target_group')
    manager = _manager(target=target_group)

    assert resolve_move_target(manager, GroupDeleteMode.MOVE, TARGET_GROUP_ID) is target_group
    manager.get_group.assert_called_once_with(TARGET_GROUP_ID)
