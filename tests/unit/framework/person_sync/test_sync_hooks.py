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
Unit tests for cmdb.framework.person_sync.sync_hooks

Pinned: without a registered builder there are no events, the last registration counts; a sync outside a request reads
only the settings while the user sync is off; a success removes the pending mark and hands the events over; a failure
undoes the sync, marks the user and raises nothing; a lost connection is undone and raised
"""
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync import sync_hooks
from cmdb.framework.person_sync.sync_engine import SyncResult
from cmdb.framework.person_sync.sync_hooks import (
    register_sync_events_builder,
    registered_sync_events,
    sync_user_outside_request,
)
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings
from cmdb.errors.database import DocumentNetworkError
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.person_sync.sync_hooks'
USER: CmdbUser = CmdbUser(public_id=7, user_name='ann', active=True)
DB_NAME: str = 'tenant'
ON: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=3))


@pytest.fixture(autouse=True, name='no_builder')
def fixture_no_builder() -> Iterator[None]:
    """Every test starts and ends without a registered builder"""
    sync_hooks._EVENTS_BUILDERS.clear()  # pylint: disable=protected-access
    yield
    sync_hooks._EVENTS_BUILDERS.clear()  # pylint: disable=protected-access


class TestTheRegistry:
    """The route layer's builder."""

    def test_without_a_builder_there_are_no_events(self) -> None:
        """Outside the app nothing is logged"""
        assert registered_sync_events(USER) is None

    def test_the_last_registration_builds_for_the_acting_user(self) -> None:
        """A second app start replaces the first builder"""
        register_sync_events_builder(lambda user: 'first')
        register_sync_events_builder(lambda user: ('second', user.public_id))

        assert registered_sync_events(USER) == ('second', USER.public_id)


class TestSyncOutsideRequest:
    """An LDAP sign-in, the cloud admin set-up."""

    @staticmethod
    def _context() -> Any:
        """A context of mocked managers"""
        return SimpleNamespace(users_manager=MagicMock(), objects_manager=MagicMock())

    def test_while_off_only_the_settings_are_read(self) -> None:
        """Nothing else"""
        with patch(f'{PATH}.read_sync_settings', return_value=PersonSyncSettings()), \
             patch(f'{PATH}.build_sync_context') as build, patch(f'{PATH}.sync_user') as sync:
            sync_user_outside_request(MagicMock(), DB_NAME, USER)

        build.assert_not_called()
        sync.assert_not_called()

    def test_a_success_removes_the_mark_and_emits(self) -> None:
        """The events through the registered builder, for the user itself"""
        context, result = self._context(), SyncResult(created=[1])
        register_sync_events_builder(lambda user: ('events', user.public_id))

        with patch(f'{PATH}.read_sync_settings', return_value=ON), \
             patch(f'{PATH}.build_sync_context', return_value=context), \
             patch(f'{PATH}.sync_user', return_value=result), patch(f'{PATH}.emit_sync_events') as emit:
            sync_user_outside_request(MagicMock(), DB_NAME, USER)

        assert context.users_manager.update.call_args.args == (
            {'public_id': USER.public_id, 'sync_pending': {'$exists': True}}, {'$unset': {'sync_pending': ''}})
        emit.assert_called_once_with(context.objects_manager, result, ('events', USER.public_id))

    def test_a_failure_is_undone_marked_and_swallowed(self) -> None:
        """The sign-in goes on"""
        context, ledger = self._context(), MagicMock()

        with patch(f'{PATH}.read_sync_settings', return_value=ON), \
             patch(f'{PATH}.build_sync_context', return_value=context), \
             patch(f'{PATH}.WriteLedger', return_value=ledger), \
             patch(f'{PATH}.sync_user', side_effect=RuntimeError('target gone')), \
             patch(f'{PATH}.emit_sync_events') as emit:
            sync_user_outside_request(MagicMock(), DB_NAME, USER)

        ledger.undo.assert_called_once()
        context.users_manager.update.assert_called_once_with({'public_id': USER.public_id}, {'sync_pending': True})
        emit.assert_not_called()

    def test_a_lost_connection_is_undone_and_raised(self) -> None:
        """The request's own failure - the app answers it"""
        context, ledger = self._context(), MagicMock()
        outage = DocumentNetworkError('lost')

        with patch(f'{PATH}.read_sync_settings', return_value=ON), \
             patch(f'{PATH}.build_sync_context', return_value=context), \
             patch(f'{PATH}.WriteLedger', return_value=ledger), \
             patch(f'{PATH}.sync_user', side_effect=outage), pytest.raises(DocumentNetworkError):
            sync_user_outside_request(MagicMock(), DB_NAME, USER)

        ledger.undo.assert_called_once()
        context.users_manager.update.assert_not_called()
