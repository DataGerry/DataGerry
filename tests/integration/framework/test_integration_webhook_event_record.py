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
Integration tests for the stored webhook delivery record, against a real MongoDB

`deliver_webhook_event` writes one CmdbWebhookEvent per delivery attempt through the real
WebhooksEventManager; the HTTP call is stubbed. What is pinned is the contract between the writer and
CmdbWebhookEvent.SCHEMA once the document has been through MongoDB: the record read back - with its
BSON date - validates, for a delivery that succeeded and for one that got no response at all
"""
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from cerberus import Validator  # type: ignore

from cmdb.database import MongoDatabaseManager
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WEBHOOK_NO_RESPONSE_CODE
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_ID: int = 97951
DELIVERED_CODE: int = 204
TARGET_URL: str = 'https://example.test/hook'
OBJECT_AFTER: dict[str, Any] = {'public_id': 1, 'fields': [{'name': 'dg-name', 'value': 'created'}]}


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """The webhook event collection of the test database"""
    return database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes this module's delivery records before and after each test"""
    _collection(database_manager, database_name).delete_many({'webhook_id': WEBHOOK_ID})
    yield
    _collection(database_manager, database_name).delete_many({'webhook_id': WEBHOOK_ID})


def _deliver_and_read_back(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Delivers one CREATE event through the real manager and answers the stored record"""
    webhook = SimpleNamespace(url=TARGET_URL, public_id=WEBHOOK_ID)
    payload: dict[str, Any] = webhook_helper.build_webhook_payload(WebhookEventType.CREATE, None, OBJECT_AFTER, None)

    webhook_helper.deliver_webhook_event(webhook, payload, WebhooksEventManager(database_manager))

    stored: dict[str, Any] | None = _collection(database_manager, database_name).find_one(
        {'webhook_id': WEBHOOK_ID}, {'_id': 0}
    )
    assert stored is not None

    return stored


def _errors(document: dict[str, Any]) -> dict[str, Any]:
    """The schema's complaints about a stored record"""
    validator = Validator(CmdbWebhookEvent.SCHEMA)
    validator.validate(document)

    return validator.errors


def test_a_delivered_event_is_stored_as_its_schema_says(
        database_manager: MongoDatabaseManager, database_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The target answered 2xx: the record read back validates, event_time is a real date"""
    monkeypatch.setattr(webhook_helper.requests, 'post',
                        lambda *args, **kwargs: SimpleNamespace(status_code=DELIVERED_CODE))

    stored: dict[str, Any] = _deliver_and_read_back(database_manager, database_name)

    assert _errors(stored) == {}
    assert stored['status'] is True
    assert stored['response_code'] == DELIVERED_CODE


def test_an_unreachable_target_is_stored_as_its_schema_says(
        database_manager: MongoDatabaseManager, database_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """No response at all: recorded with code 0 and status False, and still a valid record"""
    def _refused(*args: Any, **kwargs: Any) -> Any:
        raise requests.exceptions.ConnectionError('refused')

    monkeypatch.setattr(webhook_helper.requests, 'post', _refused)

    stored: dict[str, Any] = _deliver_and_read_back(database_manager, database_name)

    assert _errors(stored) == {}
    assert stored['status'] is False
    assert stored['response_code'] == WEBHOOK_NO_RESPONSE_CODE
