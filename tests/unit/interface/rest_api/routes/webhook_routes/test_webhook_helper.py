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
Unit tests for the webhook helper

build_webhook_payload is pure. send_webhook_event orchestrates two managers (resolved via
ManagerProvider) + an HTTP POST; here both managers and requests.post are stubbed to assert it
notifies each webhook and records one event per webhook, without a database or network.
"""
from types import SimpleNamespace

from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import build_webhook_payload, send_webhook_event
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
# -------------------------------------------------------------------------------------------------------------------- #


class TestBuildWebhookPayload:
    """build_webhook_payload assembles the event payload."""

    def test_includes_all_fields(self) -> None:
        """The payload carries the operation and the before/after/changes plus an event_time."""
        payload = build_webhook_payload(WebhookEventType.UPDATE, {'a': 1}, {'a': 2}, {'a': [1, 2]})

        assert payload['operation'] == WebhookEventType.UPDATE
        assert payload['object_before'] == {'a': 1}
        assert payload['object_after'] == {'a': 2}
        assert payload['changes'] == {'a': [1, 2]}
        assert 'event_time' in payload


class _StubWebhooksManager:
    """Returns a fixed list of webhooks from iterate_items."""

    def __init__(self, webhooks: list) -> None:
        self._webhooks = webhooks

    def iterate_items(self, _builder_params):
        """Mimics GenericManager.iterate_items().results."""
        return SimpleNamespace(results=self._webhooks, total=len(self._webhooks))


class _StubEventManager:
    """Records every inserted event payload."""

    def __init__(self) -> None:
        self.inserted: list = []

    def insert_item(self, payload) -> int:
        """Records the payload and returns a fake public_id."""
        self.inserted.append(payload)
        return len(self.inserted)


class TestSendWebhookEvent:
    """send_webhook_event notifies each webhook and records one event per webhook."""

    def test_posts_and_records_event_per_webhook(self, monkeypatch) -> None:
        """Two active webhooks -> two POSTs -> two recorded events with response metadata."""
        webhooks = [
            SimpleNamespace(public_id=1, url='http://a.test/hook'),
            SimpleNamespace(public_id=2, url='http://b.test/hook'),
        ]
        event_manager = _StubEventManager()

        def _get_manager(manager_type, _request_user):
            return _StubWebhooksManager(webhooks) if 'WEBHOOKS' == manager_type.name else event_manager

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager', staticmethod(_get_manager))
        monkeypatch.setattr(webhook_helper.requests, 'post',
                            lambda *_a, **_k: SimpleNamespace(status_code=200))

        send_webhook_event(request_user=None, operation=WebhookEventType.UPDATE,
                           object_after={'public_id': 5})

        assert len(event_manager.inserted) == 2
        assert {event['webhook_id'] for event in event_manager.inserted} == {1, 2}
        assert all(event['status'] is True and event['response_code'] == 200
                   for event in event_manager.inserted)

    def test_swallows_errors(self, monkeypatch) -> None:
        """A failure while sending is logged and swallowed (never raised to the caller)."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('resolver down')

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager', staticmethod(_boom))

        # Must not raise
        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})
