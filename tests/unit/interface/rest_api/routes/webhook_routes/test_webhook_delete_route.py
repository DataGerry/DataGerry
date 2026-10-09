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
Unit tests for DELETE /webhooks/<id>: a webhook goes together with its delivery log, or not at all

The webhook is deleted first and recorded in the write ledger, then its events in one statement. When deleting the
events fails the webhook is put back under its old id and the request answers 400 with nothing changed; when the
webhook itself cannot be deleted, its events are never touched. The managers are MagicMocks; the ledger's undo runs
for real against them
"""
from http import HTTPStatus
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.errors.manager.webhooks_event_manager import WebhooksEventManagerDeleteError
from cmdb.errors.manager.webhooks_manager import WebhooksManagerDeleteError
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.webhook_routes.webhook_routes import delete_webhook
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.webhook_routes.webhook_routes'
WEBHOOK_ID: int = 4
STORED_WEBHOOK: dict[str, Any] = {'public_id': WEBHOOK_ID, 'name': 'hook', 'url': 'https://x.io', 'active': True}


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain down to the handler."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


def _managers() -> tuple[MagicMock, MagicMock]:
    """The webhooks manager (the stored webhook readable) and the events manager."""
    webhooks_manager = MagicMock()
    webhooks_manager.get_item.return_value = dict(STORED_WEBHOOK)
    webhooks_manager.delete_item.return_value = True
    events_manager = MagicMock()

    return webhooks_manager, events_manager


def _delete(webhooks_manager: MagicMock, events_manager: MagicMock) -> Any:
    """Runs the handler with the two managers handed out by the provider."""
    managers = {ManagerType.WEBHOOKS: webhooks_manager, ManagerType.WEBHOOKS_EVENT: events_manager}

    with Flask(__name__).test_request_context('/', method='DELETE'), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=lambda kind, _user: managers[kind]):
        return _unwrap(delete_webhook)(public_id=WEBHOOK_ID, request_user=MagicMock())


def test_the_webhook_and_its_events_are_deleted() -> None:
    """The webhook, then its delivery log in one statement; nothing is put back"""
    webhooks_manager, events_manager = _managers()

    response = _delete(webhooks_manager, events_manager)

    assert response.status_code == HTTPStatus.OK
    webhooks_manager.delete_item.assert_called_once_with(WEBHOOK_ID)
    events_manager.delete_events_of_webhook.assert_called_once_with(WEBHOOK_ID)
    webhooks_manager.insert.assert_not_called()


def test_a_failed_event_delete_puts_the_webhook_back_and_answers_400() -> None:
    """The ledger re-inserts the deleted webhook under its old id; the request reports the failure"""
    webhooks_manager, events_manager = _managers()
    events_manager.delete_events_of_webhook.side_effect = WebhooksEventManagerDeleteError('events locked')
    # the undo first finds the webhook gone, then reads back the re-inserted copy
    webhooks_manager.get_one_by.side_effect = [None, dict(STORED_WEBHOOK)]

    with pytest.raises(HTTPException) as exc_info:
        _delete(webhooks_manager, events_manager)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    webhooks_manager.insert.assert_called_once_with(STORED_WEBHOOK, skip_public=True)


def test_an_undo_that_cannot_finish_answers_500_naming_the_residue() -> None:
    """When the webhook cannot be put back, the request says so instead of a clean failure"""
    webhooks_manager, events_manager = _managers()
    events_manager.delete_events_of_webhook.side_effect = WebhooksEventManagerDeleteError('events locked')
    webhooks_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        _delete(webhooks_manager, events_manager)

    assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_a_failed_webhook_delete_never_touches_the_events() -> None:
    """Nothing was deleted, so there is nothing to undo and the log stays"""
    webhooks_manager, events_manager = _managers()
    webhooks_manager.delete_item.side_effect = WebhooksManagerDeleteError('webhooks locked')

    with pytest.raises(HTTPException) as exc_info:
        _delete(webhooks_manager, events_manager)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    events_manager.delete_events_of_webhook.assert_not_called()
    webhooks_manager.insert.assert_not_called()


def test_a_missing_webhook_deletes_nothing() -> None:
    """404 before either delete"""
    webhooks_manager, events_manager = _managers()
    webhooks_manager.get_item.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        _delete(webhooks_manager, events_manager)

    assert exc_info.value.code == HTTPStatus.NOT_FOUND
    webhooks_manager.delete_item.assert_not_called()
    events_manager.delete_events_of_webhook.assert_not_called()
