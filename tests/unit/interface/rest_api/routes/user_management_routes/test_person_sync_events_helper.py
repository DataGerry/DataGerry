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
Unit tests for user_management_routes.person_sync_events_helper

Pinned: a created person gets its CREATE log and webhook; an edit that changed a field its EDIT log and UPDATE webhook
(the emitter); an edit that changed the active state its ACTIVE_CHANGE log too - and when only the state changed, one
UPDATE webhook naming the state instead of the edit's
"""
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.framework.object_edit import ObjectWrite
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper import (
    build_sync_events,
    has_field_changes,
    is_unlinked,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper'
ACTING_USER: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True)
FIELD_CHANGE: dict[str, Any] = {'old': [{'name': 'email', 'value': 'a'}], 'new': [{'name': 'email', 'value': 'b'}]}
NO_CHANGE: dict[str, Any] = {'old': [], 'new': []}


def _object(active: bool, linked: bool = False) -> CmdbObject:
    """A person in the given state - linked to user 7 when asked"""
    return CmdbObject(public_id=501, type_id=3, author_id=1, fields=[], active=active,
                      system_ref={'kind': 'user', 'id': 7} if linked else None)


@pytest.mark.parametrize('changes, expected', [
    (FIELD_CHANGE, True), (NO_CHANGE, False), ({**NO_CHANGE, 'multi_data_sections': {'old': [1]}}, True),
], ids=['field', 'none', 'section'])
def test_has_field_changes(changes: dict[str, Any], expected: bool) -> None:
    """Fields and sections count; an empty diff does not"""
    assert has_field_changes(changes) is expected


def test_a_created_person_gets_its_create_log_and_webhook() -> None:
    """Credited to the acting user"""
    created = _object(True)

    with patch(f'{PATH}.build_object_write_emitter'), patch(f'{PATH}.handle_create_object_log') as log, \
         patch(f'{PATH}.handle_notify_webhooks') as webhook:
        build_sync_events(ACTING_USER).on_create(created)

    log.assert_called_once_with(ACTING_USER, created, LogAction.CREATE)
    webhook.assert_called_once_with(ACTING_USER, created, WebhookEventType.CREATE)


def test_a_field_edit_goes_through_the_emitter_only() -> None:
    """EDIT log + UPDATE webhook; no state change, no ACTIVE_CHANGE"""
    write = ObjectWrite(_object(True), _object(True), FIELD_CHANGE)

    with patch(f'{PATH}.build_object_write_emitter') as emitter, patch(f'{PATH}.log_object_change') as log, \
         patch(f'{PATH}.send_webhook_event') as webhook, patch(f'{PATH}.ManagerProvider'):
        build_sync_events(ACTING_USER).on_edit(write)

    emitter.return_value.assert_called_once_with(write)
    log.assert_not_called()
    webhook.assert_not_called()


def test_a_state_only_edit_sends_one_state_webhook_and_logs_the_change() -> None:
    """No EDIT entry for an empty diff"""
    write = ObjectWrite(_object(True), _object(False), NO_CHANGE)

    with patch(f'{PATH}.build_object_write_emitter') as emitter, patch(f'{PATH}.log_object_change') as log, \
         patch(f'{PATH}.send_webhook_event') as webhook, patch(f'{PATH}.ManagerProvider'):
        build_sync_events(ACTING_USER).on_edit(write)

    emitter.return_value.assert_not_called()
    assert webhook.call_args.args[-1] == {'state': False}
    assert log.call_args.args[2] == LogAction.ACTIVE_CHANGE
    assert log.call_args.kwargs['changes'] == {'old': True, 'new': False}


def test_a_field_and_state_edit_does_both() -> None:
    """EDIT through the emitter, ACTIVE_CHANGE beside it, no second webhook"""
    write = ObjectWrite(_object(True), _object(False), FIELD_CHANGE)

    with patch(f'{PATH}.build_object_write_emitter') as emitter, patch(f'{PATH}.log_object_change') as log, \
         patch(f'{PATH}.send_webhook_event') as webhook, patch(f'{PATH}.ManagerProvider'):
        build_sync_events(ACTING_USER).on_edit(write)

    emitter.return_value.assert_called_once_with(write)
    assert log.call_args.args[2] == LogAction.ACTIVE_CHANGE
    webhook.assert_not_called()


@pytest.mark.parametrize('before, after, expected', [
    (True, False, True), (True, True, False), (False, False, False), (False, True, False),
], ids=['unlinked', 'still-linked', 'never-linked', 'linked'])
def test_is_unlinked(before: bool, after: bool, expected: bool) -> None:
    """Linked before, not after"""
    assert is_unlinked(ObjectWrite(_object(False, before), _object(False, after), NO_CHANGE)) is expected


def test_an_unlink_alone_is_logged_as_an_edit() -> None:
    """An inactive person losing its link: one EDIT entry naming it, no webhook"""
    write = ObjectWrite(_object(False, linked=True), _object(False), NO_CHANGE)

    with patch(f'{PATH}.build_object_write_emitter') as emitter, patch(f'{PATH}.log_object_change') as log, \
         patch(f'{PATH}.send_webhook_event') as webhook, patch(f'{PATH}.ManagerProvider'):
        build_sync_events(ACTING_USER).on_edit(write)

    emitter.return_value.assert_not_called()
    webhook.assert_not_called()
    log.assert_called_once()
    assert (log.call_args.args[2], log.call_args.args[4]) == (LogAction.EDIT, 'Unlinked from user management')
    assert log.call_args.kwargs['changes'] == NO_CHANGE


def test_an_unlink_with_a_state_change_logs_both() -> None:
    """The former user's deactivation and the unlink"""
    write = ObjectWrite(_object(True, linked=True), _object(False), NO_CHANGE)

    with patch(f'{PATH}.build_object_write_emitter'), patch(f'{PATH}.log_object_change') as log, \
         patch(f'{PATH}.send_webhook_event'), patch(f'{PATH}.ManagerProvider'):
        build_sync_events(ACTING_USER).on_edit(write)

    assert [call.args[2] for call in log.call_args_list] == [LogAction.ACTIVE_CHANGE, LogAction.EDIT]


def test_a_moved_config_item_count_is_reported_for_the_acting_user() -> None:
    """The same report an object create or delete makes - the decision whether to send is its own"""
    with patch(f'{PATH}.build_object_write_emitter'), \
         patch(f'{PATH}.handle_sync_config_item_count') as report:
        build_sync_events(ACTING_USER).on_config_items_changed()

    report.assert_called_once_with(ACTING_USER)
