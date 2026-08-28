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

``build_webhook_payload`` is pure and ``parse_webhook_params`` needs only a request context to abort
in. ``send_webhook_event`` orchestrates two managers (resolved via ManagerProvider) + an HTTP POST;
both managers and requests.post are stubbed here, so nothing touches a database or the network.

Two properties are the point of this module, because both were broken and neither is visible in
coverage (the helper was at 100% while failing them):

* **isolation** - one unreachable webhook must not stop the webhooks after it, and must still be
  logged. The delivery used to sit in a single function-level ``try``, so the first failure ended the
  fan-out and no CmdbWebhookEvent was written for any webhook, including the one that failed.
* **any 2xx is a delivery** - a receiver answering 204 used to be recorded with ``status`` False.

The dispatch is forced onto the calling thread by the autouse fixture below; the delivery code itself
is untouched by that, only the thread it runs on.
"""
from http import HTTPStatus
from types import SimpleNamespace

import pytest
import requests
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import (
    build_webhook_payload,
    parse_webhook_params,
    send_webhook_event,
)
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _dispatch_inline(monkeypatch: pytest.MonkeyPatch):
    """
    Runs every dispatched delivery on the calling thread

    ``send_webhook_event`` hands the deliveries to a ThreadPoolExecutor so an object write is not
    blocked by them. Asserting on a background thread would be a race, so the pool is replaced by an
    inline runner - the delivery code under test is unchanged, only the thread it runs on is.
    """
    def _submit_inline(fn, *args, **kwargs):
        fn(*args, **kwargs)

    monkeypatch.setattr(webhook_helper.DISPATCH_EXECUTOR, 'submit', _submit_inline)


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


def _manager_resolver(webhooks: list, event_manager):
    """
    Builds a ManagerProvider.get_manager stand-in returning the webhook stub, then the event stub

    Args:
        webhooks (list): The webhooks the WebhooksManager stub should yield
        event_manager: The stub recording the inserted CmdbWebhookEvents

    Returns:
        Callable: A get_manager replacement keyed on the ManagerType name
    """
    def _get_manager(manager_type, _request_user):
        return _StubWebhooksManager(webhooks) if manager_type.name == 'WEBHOOKS' else event_manager

    return _get_manager


def _raise_on_post(exc: Exception):
    """
    Returns a requests.post stand-in that always raises the given exception

    Args:
        exc (Exception): The exception every call should raise

    Returns:
        Callable: A requests.post replacement
    """
    def _post(*_args, **_kwargs):
        raise exc

    return _post


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


class TestDeliveryIsolation:
    """One failing webhook may neither silence the others nor hide its own failure."""

    def test_a_failing_webhook_does_not_stop_the_later_ones(self, monkeypatch) -> None:
        """
        Every webhook is delivered independently (regression)

        With the old single try/except the loop ended on the first exception, so webhook 2 was never
        POSTed to and no event was recorded for either of them.
        """
        webhooks = [
            SimpleNamespace(public_id=1, url='http://bad.test/hook'),
            SimpleNamespace(public_id=2, url='http://good.test/hook'),
        ]
        event_manager = _StubEventManager()
        posted: list[str] = []

        def _post(url, **_kwargs):
            posted.append(url)

            if 'bad' in url:
                raise requests.exceptions.ConnectTimeout('boom')

            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver(webhooks, event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post', _post)

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert posted == ['http://bad.test/hook', 'http://good.test/hook']
        assert {event['webhook_id'] for event in event_manager.inserted} == {1, 2}

    def test_a_failed_delivery_is_still_recorded(self, monkeypatch) -> None:
        """
        A transport failure produces an event with no response code and status False

        The delivery log exists to show which deliveries failed; recording only the successes made it
        unable to answer that.
        """
        webhooks = [SimpleNamespace(public_id=7, url='http://bad.test/hook')]
        event_manager = _StubEventManager()

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver(webhooks, event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post',
                            _raise_on_post(requests.exceptions.ConnectionError('refused')))

        send_webhook_event(request_user=None, operation=WebhookEventType.DELETE, object_before={})

        assert len(event_manager.inserted) == 1
        event = event_manager.inserted[0]
        assert event['webhook_id'] == 7
        assert event['status'] is False
        assert event['response_code'] == webhook_helper.WEBHOOK_NO_RESPONSE_CODE

    def test_a_failing_event_insert_does_not_stop_the_later_webhooks(self, monkeypatch) -> None:
        """Recording is guarded too, so a database hiccup on one event does not lose the rest."""
        webhooks = [
            SimpleNamespace(public_id=1, url='http://a.test/hook'),
            SimpleNamespace(public_id=2, url='http://b.test/hook'),
        ]
        posted: list[str] = []

        class _FlakyEventManager:
            """Raises on the first insert, records the rest."""

            def __init__(self) -> None:
                self.inserted: list = []

            def insert_item(self, payload) -> int:
                """Fails once, then behaves."""
                if not self.inserted and payload['webhook_id'] == 1:
                    self.inserted.append(None)
                    raise RuntimeError('collection unavailable')

                self.inserted.append(payload)
                return len(self.inserted)

        event_manager = _FlakyEventManager()

        def _post(url, **_kwargs):
            posted.append(url)
            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver(webhooks, event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post', _post)

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert len(posted) == 2


class TestDeliveredStatus:
    """Any 2xx means the target accepted the payload."""

    @pytest.mark.parametrize('status_code', [200, 201, 202, 204, 299])
    def test_every_2xx_counts_as_delivered(self, monkeypatch, status_code: int) -> None:
        """204 used to be recorded as a failure, because the check was == 200."""
        event_manager = _StubEventManager()
        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver([SimpleNamespace(public_id=1, url='http://a.test/h')],
                                                           event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post',
                            lambda *_a, **_k: SimpleNamespace(status_code=status_code))

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert event_manager.inserted[0]['status'] is True
        assert event_manager.inserted[0]['response_code'] == status_code

    @pytest.mark.parametrize('status_code', [199, 300, 400, 404, 500])
    def test_anything_outside_2xx_is_not_delivered(self, monkeypatch, status_code: int) -> None:
        """The event is still recorded, with the real code and status False."""
        event_manager = _StubEventManager()
        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver([SimpleNamespace(public_id=1, url='http://a.test/h')],
                                                           event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post',
                            lambda *_a, **_k: SimpleNamespace(status_code=status_code))

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert event_manager.inserted[0]['status'] is False
        assert event_manager.inserted[0]['response_code'] == status_code


class TestDispatch:
    """The deliveries are handed to the pool, not run on the request thread."""

    def test_one_task_is_submitted_per_webhook(self, monkeypatch) -> None:
        """
        send_webhook_event submits and returns; it does not wait for the POSTs

        Asserted on the submissions rather than on timing: the request thread must only pay for the
        one query that reads the webhooks.
        """
        submitted: list = []
        webhooks = [SimpleNamespace(public_id=i, url=f'http://h{i}.test/hook') for i in (1, 2, 3)]
        event_manager = _StubEventManager()

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver(webhooks, event_manager)))
        monkeypatch.setattr(webhook_helper.DISPATCH_EXECUTOR, 'submit',
                            lambda fn, *args, **kwargs: submitted.append((fn, args)))

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert len(submitted) == 3
        assert all(fn is webhook_helper.deliver_webhook_event for fn, _args in submitted)
        assert not event_manager.inserted

    def test_each_delivery_gets_its_own_payload_copy(self, monkeypatch) -> None:
        """
        The payload is built once and copied per delivery

        deliver_webhook_event writes that webhook's transport metadata into the dict it is handed, so
        sharing one dict across the fan-out would make the events overwrite each other's webhook_id.
        """
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h'),
                    SimpleNamespace(public_id=2, url='http://b.test/h')]
        event_manager = _StubEventManager()

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(_manager_resolver(webhooks, event_manager)))
        monkeypatch.setattr(webhook_helper.requests, 'post',
                            lambda *_a, **_k: SimpleNamespace(status_code=200))

        send_webhook_event(request_user=None, operation=WebhookEventType.UPDATE, object_after={'public_id': 9})

        assert len(event_manager.inserted) == 2
        assert event_manager.inserted[0] is not event_manager.inserted[1]
        assert [event['webhook_id'] for event in event_manager.inserted] == [1, 2]

    def test_no_webhook_means_no_event_manager_and_no_dispatch(self, monkeypatch) -> None:
        """With nothing subscribed the write pays for one query and stops."""
        resolved: list = []

        def _get_manager(manager_type, _request_user):
            resolved.append(manager_type.name)

            return _StubWebhooksManager([])

        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager', staticmethod(_get_manager))

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE, object_after={})

        assert resolved == ['WEBHOOKS']


class TestParseWebhookParams:
    """parse_webhook_params is the only validation a CmdbWebhook document gets."""

    def test_normalises_a_valid_payload(self) -> None:
        """event_types becomes a list, active a bool, and name/url are stripped."""
        params = {'name': '  Hook  ', 'url': 'https://example.test/h',
                  'event_types': "['CREATE', 'UPDATE']", 'active': 'True'}

        parse_webhook_params(params)

        assert params == {'name': 'Hook', 'url': 'https://example.test/h',
                          'event_types': ['CREATE', 'UPDATE'], 'active': True}

    def test_active_defaults_to_false_when_absent(self) -> None:
        """Anything that is not the string 'true' is False - unchanged behaviour, pinned."""
        params = {'name': 'Hook', 'url': 'https://example.test/h', 'event_types': "['CREATE']"}

        parse_webhook_params(params)

        assert params['active'] is False

    @pytest.mark.parametrize('params', [
        {'url': 'https://e.test/h', 'event_types': "['CREATE']"},
        {'name': ' ', 'url': 'https://e.test/h', 'event_types': "['CREATE']"},
        {'name': 'Hook', 'event_types': "['CREATE']"},
        {'name': 'Hook', 'url': 'ftp://e.test/h', 'event_types': "['CREATE']"},
        {'name': 'Hook', 'url': 'http://', 'event_types': "['CREATE']"},
        {'name': 'Hook', 'url': 'https://e.test/h'},
        {'name': 'Hook', 'url': 'https://e.test/h', 'event_types': '42'},
        {'name': 'Hook', 'url': 'https://e.test/h', 'event_types': '[]'},
        {'name': 'Hook', 'url': 'https://e.test/h', 'event_types': "['NOPE']"},
        {'name': 'Hook', 'url': 'https://e.test/h', 'event_types': 'not a literal'},
    ], ids=['no-name', 'blank-name', 'no-url', 'bad-scheme', 'no-host', 'no-event-types',
            'event-types-int', 'event-types-empty', 'event-types-unknown', 'event-types-unparsable'])
    def test_rejects_an_unusable_payload(self, params: dict) -> None:
        """Each of these used to be accepted and stored."""
        with pytest.raises(HTTPException) as raised:
            parse_webhook_params(dict(params))

        assert raised.value.code == HTTPStatus.BAD_REQUEST
