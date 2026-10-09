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

``abort_if_admin_would_be_deleted``: only a DELETE-mode delete looks, in this group only, and refuses 400.

``unknown_right_names`` / ``abort_if_unknown_rights``: known names and wildcards pass; each unknown name is
listed once, in the order sent, and the refusal is a 400 naming all of them. An absent or empty list passes.

``redistribute_members``: the members are read once, the inverse is recorded BEFORE the write (MOVE: move exactly
those ids back, checked by a count; DELETE: batch snapshots of the users and their settings), and the write is
handed exactly the ids read. An empty group records and writes nothing.

Pure tests with a stubbed GroupsManager. flask.abort raises a werkzeug HTTPException, so the status
codes are asserted without a Flask app context
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.models.group_model import GroupDeleteMode, GroupKey, ADMIN_GROUP_ID, MASTER_RIGHT_NAME
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_helper import (
    resolve_move_target,
    abort_if_admin_would_be_deleted,
    abort_if_members_would_be_stranded,
    ensure_admin_group_keeps_master_right,
    redistribute_members,
    unknown_right_names,
    abort_if_unknown_rights,
)
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_MEMBERS_NEED_ACTION_MSG,
    GROUP_MOVE_TARGET_IS_SOURCE_MSG,
    GROUP_UNKNOWN_RIGHTS_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_GROUP_ID: int = 42
SOURCE_GROUP_ID: int = 77
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

    assert resolve_move_target(manager, GroupDeleteMode.DELETE, TARGET_GROUP_ID, SOURCE_GROUP_ID) is None
    manager.get_group.assert_not_called()


def test_none_action_returns_none_without_lookup() -> None:
    """A missing action (plain delete) resolves to None and never looks a group up."""
    manager = _manager()

    assert resolve_move_target(manager, None, None, SOURCE_GROUP_ID) is None
    manager.get_group.assert_not_called()


def test_move_without_target_id_aborts_400() -> None:
    """MOVE without a target id is a bad request."""
    manager = _manager()

    with pytest.raises(HTTPException) as exc_info:
        resolve_move_target(manager, GroupDeleteMode.MOVE, None, SOURCE_GROUP_ID)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    manager.get_group.assert_not_called()


def test_move_with_missing_target_aborts_404() -> None:
    """MOVE to a target group that does not exist is a not-found."""
    manager = _manager(target=None)

    with pytest.raises(HTTPException) as exc_info:
        resolve_move_target(manager, GroupDeleteMode.MOVE, TARGET_GROUP_ID, SOURCE_GROUP_ID)

    assert exc_info.value.code == HTTPStatus.NOT_FOUND
    manager.get_group.assert_called_once_with(TARGET_GROUP_ID)


def test_move_into_the_group_being_deleted_aborts_400() -> None:
    """The members would land in a group that is gone the moment the delete completes"""
    manager = _manager(target=MagicMock())

    with pytest.raises(HTTPException) as exc_info:
        resolve_move_target(manager, GroupDeleteMode.MOVE, SOURCE_GROUP_ID, SOURCE_GROUP_ID)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == GROUP_MOVE_TARGET_IS_SOURCE_MSG.format(public_id=SOURCE_GROUP_ID)
    manager.get_group.assert_not_called()


def _users_manager(has_members: bool) -> MagicMock:
    """A stub UsersManager answering whether the group has members."""
    users_manager = MagicMock()
    users_manager.has_group_members.return_value = has_members
    return users_manager


def test_no_action_with_members_aborts_400() -> None:
    """They would keep a group_id that resolves to nothing - refused, naming the group and the choices"""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_members_would_be_stranded(_users_manager(True), SOURCE_GROUP_ID, None)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == GROUP_MEMBERS_NEED_ACTION_MSG.format(public_id=SOURCE_GROUP_ID)


def test_no_action_for_an_empty_group_passes() -> None:
    """Nobody to strand"""
    users_manager = _users_manager(False)

    abort_if_members_would_be_stranded(users_manager, SOURCE_GROUP_ID, None)

    users_manager.has_group_members.assert_called_once_with(SOURCE_GROUP_ID)


@pytest.mark.parametrize('action', [GroupDeleteMode.MOVE, GroupDeleteMode.DELETE], ids=lambda action: action.value)
def test_an_action_needs_no_member_check(action: GroupDeleteMode) -> None:
    """Either mode says what happens to the members, so nothing is counted"""
    users_manager = _users_manager(True)

    abort_if_members_would_be_stranded(users_manager, SOURCE_GROUP_ID, action)

    users_manager.has_group_members.assert_not_called()


def test_valid_move_returns_target_group() -> None:
    """A MOVE to an existing target returns that target group."""
    target_group = MagicMock(name='target_group')
    manager = _manager(target=target_group)

    assert resolve_move_target(manager, GroupDeleteMode.MOVE, TARGET_GROUP_ID, SOURCE_GROUP_ID) is target_group
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
        # The schema refuses full right dicts before this guard runs; the guard alone must not take a
        # dict for the master right's name either.
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


SOURCE_GROUP: int = 70
TARGET_GROUP: int = 71
MEMBERS: list[int] = [11, 12]
USERS_COLLECTION: str = 'management.users'
SETTINGS_COLLECTION: str = 'management.users.settings'


@pytest.mark.parametrize('action', [GroupDeleteMode.MOVE, None], ids=['move', 'none'])
def test_the_admin_check_only_runs_for_a_delete(action: GroupDeleteMode | None) -> None:
    """A move or an empty-group delete never deletes the admin, so nothing is read."""
    users_manager = MagicMock()

    abort_if_admin_would_be_deleted(users_manager, SOURCE_GROUP, action)

    users_manager.get_one_by.assert_not_called()


def test_the_admin_in_the_group_refuses_a_delete() -> None:
    """400, looked up in this group only."""
    users_manager = MagicMock()
    users_manager.get_one_by.return_value = {'public_id': CmdbUser.ADMIN_PUBLIC_ID}

    with pytest.raises(HTTPException) as exc_info:
        abort_if_admin_would_be_deleted(users_manager, SOURCE_GROUP, GroupDeleteMode.DELETE)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    users_manager.get_one_by.assert_called_once_with({'group_id': SOURCE_GROUP, 'public_id': CmdbUser.ADMIN_PUBLIC_ID})


def test_a_delete_without_the_admin_passes() -> None:
    """No admin member, no refusal."""
    users_manager = MagicMock()
    users_manager.get_one_by.return_value = None

    assert abort_if_admin_would_be_deleted(users_manager, SOURCE_GROUP, GroupDeleteMode.DELETE) is None


def _managers(members: list[int]) -> tuple[MagicMock, MagicMock]:
    """A users and a settings manager stub; the users manager reports the given members."""
    users_manager, settings_manager = MagicMock(), MagicMock()
    users_manager.collection = USERS_COLLECTION
    settings_manager.collection = SETTINGS_COLLECTION
    users_manager.get_group_member_ids.return_value = list(members)
    users_manager.find.return_value = [{'_id': f'u{i}', 'public_id': i} for i in members]
    settings_manager.find.return_value = [{'_id': 's1', 'user_id': members[0]}] if members else []

    return users_manager, settings_manager


class TestRedistributeMembers:
    """The one write path for a deleted group's members."""

    @pytest.mark.parametrize('action', [GroupDeleteMode.MOVE, GroupDeleteMode.DELETE], ids=['move', 'delete'])
    def test_an_empty_group_records_and_writes_nothing(self, action: GroupDeleteMode) -> None:
        """No members: no entry, no write."""
        ledger = WriteLedger()
        users_manager, settings_manager = _managers([])

        redistribute_members(ledger, (users_manager, settings_manager), SOURCE_GROUP, action, TARGET_GROUP)

        assert not ledger.entries
        users_manager.handle_users_on_group_delete.assert_not_called()

    @pytest.mark.parametrize('action', [GroupDeleteMode.MOVE, GroupDeleteMode.DELETE], ids=['move', 'delete'])
    def test_the_write_gets_exactly_the_ids_read(self, action: GroupDeleteMode) -> None:
        """The ids the inverse covers are the ids the write selects."""
        users_manager, settings_manager = _managers(MEMBERS)

        redistribute_members(WriteLedger(), (users_manager, settings_manager), SOURCE_GROUP, action, TARGET_GROUP)

        users_manager.handle_users_on_group_delete.assert_called_once_with(SOURCE_GROUP, action, TARGET_GROUP,
                                                                           MEMBERS)
        users_manager.get_group_member_ids.assert_called_once_with(SOURCE_GROUP)

    @pytest.mark.parametrize('action', [GroupDeleteMode.MOVE, GroupDeleteMode.DELETE], ids=['move', 'delete'])
    def test_the_inverse_is_recorded_before_the_write(self, action: GroupDeleteMode) -> None:
        """A write that raises part-way is still undone: its entries are already there."""
        ledger = WriteLedger()
        users_manager, settings_manager = _managers(MEMBERS)
        recorded: list[int] = []
        users_manager.handle_users_on_group_delete.side_effect = lambda *_a: recorded.append(len(ledger.entries))

        redistribute_members(ledger, (users_manager, settings_manager), SOURCE_GROUP, action, TARGET_GROUP)

        assert recorded == [len(ledger.entries)] and recorded[0] > 0

    def test_the_move_inverse_moves_exactly_the_members_back(self) -> None:
        """Checked by counting them in the source group again."""
        ledger = WriteLedger()
        users_manager, settings_manager = _managers(MEMBERS)
        users_manager.count_documents.return_value = len(MEMBERS)
        redistribute_members(ledger, (users_manager, settings_manager), SOURCE_GROUP, GroupDeleteMode.MOVE,
                             TARGET_GROUP)

        assert not ledger.undo()
        users_manager.move_users.assert_called_once_with(MEMBERS, SOURCE_GROUP)
        users_manager.count_documents.assert_called_once_with({'public_id': {'$in': MEMBERS},
                                                               'group_id': SOURCE_GROUP})

    def test_a_move_inverse_that_leaves_one_behind_is_residue(self) -> None:
        """One member still in the target: the count says so."""
        ledger = WriteLedger()
        users_manager, settings_manager = _managers(MEMBERS)
        users_manager.count_documents.return_value = len(MEMBERS) - 1
        redistribute_members(ledger, (users_manager, settings_manager), SOURCE_GROUP, GroupDeleteMode.MOVE,
                             TARGET_GROUP)

        residue = ledger.undo()

        assert [(item.collection, item.kind) for item in residue] == [(USERS_COLLECTION, WriteKind.COMPENSATED)]

    def test_a_delete_snapshots_the_users_and_their_settings(self) -> None:
        """Two batch entries, read by the member ids: whole user documents, and settings by user_id."""
        ledger = WriteLedger()
        users_manager, settings_manager = _managers(MEMBERS)

        redistribute_members(ledger, (users_manager, settings_manager), SOURCE_GROUP, GroupDeleteMode.DELETE, None)

        users_manager.find.assert_called_once_with(criteria={'public_id': {'$in': MEMBERS}}, projection=None)
        settings_manager.find.assert_called_once_with(criteria={'user_id': {'$in': MEMBERS}}, projection=None)
        assert [entry.collection for entry in ledger.entries] == [USERS_COLLECTION, SETTINGS_COLLECTION]


# -------------------------------------------------------------------------------------------------------------------- #
#                                         unknown_right_names / abort_if_unknown_rights                                #
# -------------------------------------------------------------------------------------------------------------------- #
KNOWN_RIGHT_NAME: str = 'base.framework.object.view'
WILDCARD_RIGHT_NAME: str = 'base.framework.*'
UNKNOWN_RIGHT_NAME: str = 'base.no-such-right'
OTHER_UNKNOWN_RIGHT_NAME: str = 'base.framework.no-such-right'
KNOWN_NAMES: frozenset[str] = frozenset({KNOWN_RIGHT_NAME, WILDCARD_RIGHT_NAME, MASTER_RIGHT_NAME})


def test_known_names_and_wildcards_are_not_unknown() -> None:
    """Every name of the tree, wildcards included, passes."""
    assert not unknown_right_names([KNOWN_RIGHT_NAME, WILDCARD_RIGHT_NAME, MASTER_RIGHT_NAME], KNOWN_NAMES)


def test_unknown_names_are_listed_once_in_the_order_sent() -> None:
    """Duplicates collapse; the first occurrence decides the position."""
    submitted: list[str] = [OTHER_UNKNOWN_RIGHT_NAME, KNOWN_RIGHT_NAME, UNKNOWN_RIGHT_NAME, OTHER_UNKNOWN_RIGHT_NAME]

    assert unknown_right_names(submitted, KNOWN_NAMES) == [OTHER_UNKNOWN_RIGHT_NAME, UNKNOWN_RIGHT_NAME]


def test_the_match_is_exact() -> None:
    """A name differing only in case is unknown - right names are compared as stored."""
    assert unknown_right_names([KNOWN_RIGHT_NAME.upper()], KNOWN_NAMES) == [KNOWN_RIGHT_NAME.upper()]


@pytest.mark.parametrize('data', [{}, {GroupKey.RIGHTS.value: []}, {GroupKey.RIGHTS.value: None}])
def test_no_rights_passes(data: dict) -> None:
    """An absent, empty or null rights list has nothing to refuse."""
    abort_if_unknown_rights(data, KNOWN_NAMES)


def test_a_payload_of_known_names_passes() -> None:
    """Nothing is raised for known names only."""
    abort_if_unknown_rights({GroupKey.RIGHTS.value: [KNOWN_RIGHT_NAME, WILDCARD_RIGHT_NAME]}, KNOWN_NAMES)


def test_an_unknown_name_aborts_400_naming_every_unknown() -> None:
    """The refusal is a 400 whose message lists each unknown name, quoted, in the order sent."""
    data: dict = {GroupKey.RIGHTS.value: [UNKNOWN_RIGHT_NAME, KNOWN_RIGHT_NAME, OTHER_UNKNOWN_RIGHT_NAME]}

    with pytest.raises(HTTPException) as exc_info:
        abort_if_unknown_rights(data, KNOWN_NAMES)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == GROUP_UNKNOWN_RIGHTS_MSG.format(
        names=f"'{UNKNOWN_RIGHT_NAME}', '{OTHER_UNKNOWN_RIGHT_NAME}'",
    )
