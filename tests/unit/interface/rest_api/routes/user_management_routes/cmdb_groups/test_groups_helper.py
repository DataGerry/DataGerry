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
Unit tests for the CmdbUserGroup route helpers

``resolve_move_target``: a non-MOVE action resolves to None without a lookup; a MOVE without a
target id aborts 400; a MOVE whose target is missing aborts 404; a valid MOVE returns the resolved
target group.

``ensure_admin_group_keeps_master_right``: any group other than the administrator group passes
untouched (even when it drops every right); the administrator group passes only while its payload
still lists the master right as a name string - an omitted, empty, null or dict-shaped rights list
aborts 400.

Pure tests with a stubbed GroupsManager. flask.abort raises a werkzeug HTTPException, so the status
codes are asserted without a Flask app context
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.group_model import GroupDeleteMode, GroupKey, ADMIN_GROUP_ID, MASTER_RIGHT_NAME
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_helper import (
    resolve_move_target,
    ensure_admin_group_keeps_master_right,
)
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_GROUP_ID: int = 42
NON_ADMIN_GROUP_ID: int = 4711
OTHER_RIGHT_NAME: str = 'base.framework.object.view'


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                       ensure_admin_group_keeps_master_right                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def _admin_payload(rights: object = ...) -> dict[str, object]:
    """An administrator-group update payload; omit ``rights`` entirely by leaving the default."""
    payload: dict[str, object] = {GroupKey.NAME: 'admin', GroupKey.LABEL: 'Administrator'}

    if rights is not ...:
        payload[GroupKey.RIGHTS] = rights

    return payload


def test_admin_group_keeping_master_right_passes() -> None:
    """The administrator group may be updated as long as the payload still lists the master right."""
    assert ensure_admin_group_keeps_master_right(ADMIN_GROUP_ID, _admin_payload([MASTER_RIGHT_NAME])) is None


def test_admin_group_keeping_master_right_among_others_passes() -> None:
    """Adding further rights next to the master right is allowed."""
    payload = _admin_payload([OTHER_RIGHT_NAME, MASTER_RIGHT_NAME])

    assert ensure_admin_group_keeps_master_right(ADMIN_GROUP_ID, payload) is None


@pytest.mark.parametrize(
    'rights',
    [
        pytest.param([], id='empty-list'),
        pytest.param(None, id='null'),
        pytest.param([OTHER_RIGHT_NAME], id='master-right-replaced'),
        # A payload of full right dicts resolves to no rights at all in CmdbUserGroup.from_data,
        # so it must be rejected here too rather than silently wiping the group's rights.
        pytest.param([{'name': MASTER_RIGHT_NAME}], id='right-dicts'),
    ],
)
def test_admin_group_dropping_master_right_aborts_400(rights: object) -> None:
    """Any administrator-group payload that does not list the master right by name is a bad request."""
    with pytest.raises(HTTPException) as exc_info:
        ensure_admin_group_keeps_master_right(ADMIN_GROUP_ID, _admin_payload(rights))

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST


def test_admin_group_without_rights_key_aborts_400() -> None:
    """A payload omitting ``rights`` entirely would wipe the master right, so it is refused."""
    with pytest.raises(HTTPException) as exc_info:
        ensure_admin_group_keeps_master_right(ADMIN_GROUP_ID, _admin_payload())

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize(
    'rights',
    [
        pytest.param([], id='empty-list'),
        pytest.param([OTHER_RIGHT_NAME], id='other-right'),
        pytest.param([MASTER_RIGHT_NAME], id='master-right'),
    ],
)
def test_non_admin_group_is_never_guarded(rights: list) -> None:
    """Every other group keeps its full freedom, including dropping all of its rights."""
    payload = {GroupKey.NAME: f'group-{NON_ADMIN_GROUP_ID}', GroupKey.RIGHTS: rights}

    assert ensure_admin_group_keeps_master_right(NON_ADMIN_GROUP_ID, payload) is None
