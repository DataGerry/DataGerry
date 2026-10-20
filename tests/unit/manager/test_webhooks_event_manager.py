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
Unit tests for WebhooksEventManager.delete_events_of_webhook

A webhook's whole delivery log is deleted in one statement filtered on its id; the count deleted is answered, and a
failed delete is the manager's own delete error with the base error kept as its cause
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.errors.manager.webhooks_event_manager import WebhooksEventManagerDeleteError
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.models.webhook_model.webhook_event_constants import WebhookEventKey
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_ID: int = 7
DELETED_COUNT: int = 3


def _manager() -> MagicMock:
    """A stand-in carrying the BaseManager method the method under test calls."""
    return MagicMock(spec=WebhooksEventManager)


def test_the_webhooks_events_are_deleted_in_one_statement() -> None:
    """One delete_many, filtered on the webhook id, answering the deleted count"""
    manager = _manager()
    manager.delete_many.return_value = SimpleNamespace(deleted_count=DELETED_COUNT)

    deleted = WebhooksEventManager.delete_events_of_webhook(manager, WEBHOOK_ID)

    manager.delete_many.assert_called_once_with({WebhookEventKey.WEBHOOK_ID.value: WEBHOOK_ID})
    assert deleted == DELETED_COUNT


def test_a_failed_delete_is_the_managers_delete_error() -> None:
    """The base error is wrapped, not leaked, and kept as the cause"""
    manager = _manager()
    cause = BaseManagerDeleteError('disk full')
    manager.delete_many.side_effect = cause

    with pytest.raises(WebhooksEventManagerDeleteError) as exc_info:
        WebhooksEventManager.delete_events_of_webhook(manager, WEBHOOK_ID)

    assert exc_info.value.__cause__ is cause
    assert exc_info.value.args[0] is cause
