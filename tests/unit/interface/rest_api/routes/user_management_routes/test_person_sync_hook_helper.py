# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for user_management_routes.person_sync_hook_helper

Pinned: the write runs with a ledger and the sync's context, and the events follow for the request user; a sync failure
is undone and answered 500 without events; any other error passes unchanged, after the undo; the members of a deleted
user group are synced - the kept ones as users, the deleted ones as deleted users
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.sync_engine import SyncResult
from cmdb.framework.write_ledger import WriteLedger
from cmdb.errors.person_sync import PersonSyncTargetError
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_hook_helper import (
    PERSON_SYNC_FAILED_MESSAGE,
    sync_regrouped_users,
    write_with_person_sync,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_hook_helper'
REQUEST_USER: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True)


def _patched(context: Any) -> tuple[Any, Any, Any]:
    """The context, the events builder and the emitter patched"""
    return (patch(f'{PATH}.person_sync_context', return_value=context), patch(f'{PATH}.build_sync_events'),
            patch(f'{PATH}.emit_sync_events'))


def test_the_write_runs_on_a_ledger_and_the_events_follow() -> None:
    """For the request user, with what the write answered"""
    context, result = SimpleNamespace(objects_manager=MagicMock()), SyncResult(created=[5])
    seen: list[tuple[Any, Any]] = []

    def _write(ledger: WriteLedger, sync_context: Any) -> SyncResult:
        seen.append((ledger, sync_context))
        return result

    context_patch, builder_patch, emit_patch = _patched(context)

    with context_patch, builder_patch as builder, emit_patch as emit:
        write_with_person_sync(REQUEST_USER, _write)

    assert isinstance(seen[0][0], WriteLedger) and seen[0][1] is context
    builder.assert_called_once_with(REQUEST_USER)
    emit.assert_called_once_with(context.objects_manager, result, builder.return_value)


def test_a_sync_failure_is_undone_and_answered_500() -> None:
    """No events - nothing stood"""
    undone: list[bool] = []

    def _write(ledger: WriteLedger, _context: Any) -> SyncResult:
        ledger.compensated('users', 'the user write', undo=lambda: undone.append(True), verify=lambda: True)
        raise PersonSyncTargetError('Type 3 is deactivated')

    context_patch, builder_patch, emit_patch = _patched(SimpleNamespace(objects_manager=MagicMock()))

    with context_patch, builder_patch, emit_patch as emit, pytest.raises(HTTPException) as raised:
        write_with_person_sync(REQUEST_USER, _write)

    assert raised.value.code == 500
    assert raised.value.description == PERSON_SYNC_FAILED_MESSAGE.format(error='Type 3 is deactivated')
    assert undone == [True]
    emit.assert_not_called()


def test_another_error_passes_unchanged_after_the_undo() -> None:
    """The route answers what it hit"""
    undone: list[bool] = []

    def _write(ledger: WriteLedger, _context: Any) -> SyncResult:
        ledger.compensated('users', 'the user write', undo=lambda: undone.append(True), verify=lambda: True)
        raise NotFound('gone')

    context_patch, builder_patch, emit_patch = _patched(SimpleNamespace(objects_manager=MagicMock()))

    with context_patch, builder_patch, emit_patch, pytest.raises(NotFound):
        write_with_person_sync(REQUEST_USER, _write)

    assert undone == [True]


def test_the_members_of_a_deleted_group_are_synced() -> None:
    """Kept members synced at once (their groups once), deleted ones as deleted users; nothing read for an empty list"""
    users_manager = MagicMock()
    kept = CmdbUser(public_id=4, user_name='kept', active=True)
    users_manager.get_user_lookup.return_value = {4: kept}
    context, ledger = SimpleNamespace(users_manager=users_manager), MagicMock()

    with patch(f'{PATH}.sync_users', return_value=SyncResult(created=[40])) as sync, \
         patch(f'{PATH}.sync_user_deleted', return_value=SyncResult(created=[50])) as deleted:
        result = sync_regrouped_users(context, ledger, [4], [6])

    sync.assert_called_once_with(context, ledger, [kept])
    deleted.assert_called_once_with(context, ledger, 6)
    assert result.created == [40, 50]

    users_manager.get_user_lookup.reset_mock()
    with patch(f'{PATH}.sync_users', return_value=SyncResult()) as sync, patch(f'{PATH}.sync_user_deleted'):
        sync_regrouped_users(context, ledger, [], [])

    users_manager.get_user_lookup.assert_not_called()
    sync.assert_called_once_with(context, ledger, [])
