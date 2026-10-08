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

``build_webhook_payload`` is pure and ``parse_webhook_params`` needs no request context: it reads the
merged write payload it is handed, typed (a JSON body) or text (a query string), and aborts 400.
``send_webhook_event`` orchestrates two managers (resolved via ManagerProvider) + an HTTP POST; both
managers and requests.post are stubbed here, so nothing touches a database or the network.

Two properties are the point of this module, because both were broken and neither is visible in
coverage (the helper was at 100% while failing them):

* **isolation** - one unreachable webhook must not stop the webhooks after it, and must still be
  logged. A single function-level ``try`` around the delivery lets the first failure end the
  fan-out and no CmdbWebhookEvent was written for any webhook, including the one that failed.
* **any 2xx is a delivery** - a receiver answering 204 must not be recorded with ``status`` False.

The dispatch is forced onto the calling thread by the autouse fixture below; the delivery code itself
is untouched by that, only the thread it runs on.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from cerberus import Validator  # type: ignore
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import (
    WEBHOOK_ACTIVE_DEFAULT,
    WEBHOOK_ACTIVE_INVALID_MSG,
    WEBHOOK_TEXT_NOT_A_STRING_MSG,
)
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import (
    WEBHOOK_WRITE_SCHEMA,
    build_webhook_payload,
    parse_webhook_params,
    send_webhook_event,
)
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
# -------------------------------------------------------------------------------------------------------------------- #

# The three scope steps as shipped, kept before the module-wide pass-through below replaces them
_REAL_READ_EVENT_TYPE_DOCUMENT = webhook_helper.read_event_type_document
_REAL_READ_WEBHOOK_OWNERS = webhook_helper.read_webhook_owners
_REAL_SCOPE_WEBHOOKS_TO_OWNERS = webhook_helper.scope_webhooks_to_owners


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


@pytest.fixture(autouse=True)
def _owners_receive_everything(monkeypatch: pytest.MonkeyPatch):
    """
    Lets every stand-in webhook through the owner scope

    The fan-out tests below are about isolation and status codes, not about who may receive an event,
    so the two scope reads are stubbed and the scope passes every webhook. The scope itself is covered
    by ``TestSendWebhookEventOwnerScope`` and by ``test_webhook_delivery_scope.py``.
    """
    monkeypatch.setattr(webhook_helper, 'read_event_type_document', lambda *_a: None)
    monkeypatch.setattr(webhook_helper, 'read_webhook_owners', lambda *_a: {})
    monkeypatch.setattr(webhook_helper, 'scope_webhooks_to_owners', lambda webhooks, *_a: webhooks)


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
        """204 must not be recorded as a failure, which a check of == 200 would do."""
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


TARGET_URL: str = 'https://example.test/h'


class TestParseWebhookParams:
    """parse_webhook_params validates and normalises a CmdbWebhook write, typed or text."""

    def test_normalises_a_valid_payload(self) -> None:
        """event_types becomes a list, active a bool, and name/url are stripped."""
        params = {'name': '  Hook  ', 'url': 'https://example.test/h',
                  'event_types': "['CREATE', 'UPDATE']", 'active': 'True'}

        parse_webhook_params(params)

        assert params == {'name': 'Hook', 'url': 'https://example.test/h',
                          'event_types': ['CREATE', 'UPDATE'], 'active': True}

    def test_a_typed_json_body_is_kept_typed(self) -> None:
        """A JSON body sends the list and the bool themselves - they pass through unchanged"""
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE', 'DELETE'], 'active': False}

        parse_webhook_params(params)

        assert params == {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE', 'DELETE'],
                          'active': False}

    @pytest.mark.parametrize('params', [
        {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE']},
        {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE'], 'active': None},
    ], ids=['absent', 'null'])
    def test_active_defaults_to_true_when_left_out(self, params: dict[str, Any]) -> None:
        """A webhook created without the flag is meant to deliver - the schema's default"""
        parse_webhook_params(params)

        assert params['active'] is WEBHOOK_ACTIVE_DEFAULT is True

    @pytest.mark.parametrize('active, expected', [
        (True, True), (False, False), ('true', True), ('false', False), (' FALSE ', False),
    ], ids=['bool-true', 'bool-false', 'text-true', 'text-false', 'padded-upper'])
    def test_active_accepts_a_bool_or_its_text(self, active: Any, expected: bool) -> None:
        """A body sends a bool, a query string 'true' / 'false' - both are read exactly"""
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE'], 'active': active}

        parse_webhook_params(params)

        assert params['active'] is expected

    @pytest.mark.parametrize('active', ['yes', '1', 1, 0, 'maybe', ['true']],
                             ids=['yes', 'text-one', 'int-one', 'int-zero', 'word', 'list'])
    def test_an_unreadable_active_is_refused(self, active: Any) -> None:
        """Read leniently, each of these used to become False and store a webhook that never fires"""
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE'], 'active': active}

        with pytest.raises(HTTPException) as raised:
            parse_webhook_params(params)

        assert raised.value.code == HTTPStatus.BAD_REQUEST
        assert raised.value.description == WEBHOOK_ACTIVE_INVALID_MSG.format(actual=active)

    @pytest.mark.parametrize('field, value', [('name', 5), ('url', ['https://e.test/h']), ('name', True)],
                             ids=['name-int', 'url-list', 'name-bool'])
    def test_a_name_or_url_that_is_not_text_is_refused(self, field: str, value: Any) -> None:
        """A JSON body can send any type; only text is a name or a URL"""
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE'], field: value}

        with pytest.raises(HTTPException) as raised:
            parse_webhook_params(params)

        assert raised.value.code == HTTPStatus.BAD_REQUEST
        assert raised.value.description == WEBHOOK_TEXT_NOT_A_STRING_MSG.format(field=field, actual=value)

    @pytest.mark.parametrize('event_types', [{'CREATE': 1}, 42, [], ['CREATE', 1], [['CREATE']], ('CREATE',)],
                             ids=['dict', 'int', 'empty', 'non-text-member', 'nested', 'tuple'])
    def test_typed_event_types_that_are_not_a_known_list_are_refused(self, event_types: Any) -> None:
        """The typed path is held to the same rule as the text one"""
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': event_types}

        with pytest.raises(HTTPException) as raised:
            parse_webhook_params(params)

        assert raised.value.code == HTTPStatus.BAD_REQUEST

    def test_the_normalised_document_satisfies_the_model_schema(self) -> None:
        """What is stored validates against CmdbWebhook.SCHEMA itself, whatever spelling came in"""
        params = {'name': ' Hook ', 'url': TARGET_URL, 'event_types': '["UPDATE"]', 'active': 'true',
                  'public_id': 7}

        parse_webhook_params(params)

        validator = Validator(CmdbWebhook.SCHEMA)
        assert validator.validate(params), validator.errors


class TestWebhookDocumentShape:
    """The last step of parse_webhook_params holds the document against the write schema."""

    def test_the_write_schema_is_the_document_schema_without_public_id(self) -> None:
        """public_id is server-owned: the create route reserves it and the update route pins it"""
        assert set(WEBHOOK_WRITE_SCHEMA) == set(CmdbWebhook.SCHEMA) - {'public_id'}

    def test_a_document_the_schema_refuses_is_a_400_naming_the_field(self) -> None:
        """A tripwire for drift: the semantic checks above always hand the schema a valid document"""
        document = {'name': 'Hook', 'url': TARGET_URL, 'event_types': 'CREATE', 'active': True}

        with pytest.raises(HTTPException) as raised:
            webhook_helper._check_webhook_document_shape(document)  # pylint: disable=protected-access

        assert raised.value.code == HTTPStatus.BAD_REQUEST
        assert 'event_types' in raised.value.description

    def test_parse_webhook_params_ends_with_the_shape_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The schema step is part of every write, not a function that merely exists"""
        checked: list[dict[str, Any]] = []
        monkeypatch.setattr(webhook_helper, '_check_webhook_document_shape', checked.append)
        params = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE']}

        parse_webhook_params(params)

        assert checked == [params]
        assert checked[0]['active'] is True

    def test_undeclared_keys_are_not_held_against_the_schema(self) -> None:
        """A merged payload may carry the pinned public_id or a stray query parameter; from_data drops them"""
        document = {'name': 'Hook', 'url': TARGET_URL, 'event_types': ['CREATE'], 'active': True,
                    'public_id': 'not-an-int', 'stray': 'x'}

        webhook_helper._check_webhook_document_shape(document)  # pylint: disable=protected-access

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
        """Each of these must be refused rather than accepted and stored."""
        with pytest.raises(HTTPException) as raised:
            parse_webhook_params(dict(params))

        assert raised.value.code == HTTPStatus.BAD_REQUEST


class _StubTypesManager:
    """Answers the type ACL read with one fixed document, and records the criteria"""

    def __init__(self, type_documents: list[dict[str, Any]]) -> None:
        self.type_documents = type_documents
        self.calls: list[tuple[dict[str, Any], dict[str, int]]] = []

    def find(self, criteria: dict[str, Any], projection: dict[str, int]) -> list[dict[str, Any]]:
        """Mimics BaseManager.find"""
        self.calls.append((criteria, projection))
        return self.type_documents


class _StubUsersManager:
    """Answers the owner lookup from a fixed dict, and records the ids asked for"""

    def __init__(self, owners: dict[int, Any]) -> None:
        self.owners = owners
        self.calls: list[list[int]] = []

    def get_user_lookup(self, user_ids: list[int]) -> dict[int, Any]:
        """Mimics UsersManager.get_user_lookup"""
        self.calls.append(user_ids)
        return {user_id: self.owners[user_id] for user_id in user_ids if user_id in self.owners}


READER_GROUP: int = 2
HIDDEN_GROUP: int = 9
EVENT_TYPE_ID: int = 40
READER_ID: int = 51
HIDDEN_ID: int = 52


class TestSendWebhookEventOwnerScope:
    """send_webhook_event delivers only to the webhooks whose owner may read the object's type"""

    @pytest.fixture(autouse=True)
    def _real_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Undoes the module-wide pass-through: these tests are about the scope"""
        monkeypatch.setattr(webhook_helper, 'read_event_type_document', _REAL_READ_EVENT_TYPE_DOCUMENT)
        monkeypatch.setattr(webhook_helper, 'read_webhook_owners', _REAL_READ_WEBHOOK_OWNERS)
        monkeypatch.setattr(webhook_helper, 'scope_webhooks_to_owners', _REAL_SCOPE_WEBHOOKS_TO_OWNERS)

    @staticmethod
    def _wire(monkeypatch: pytest.MonkeyPatch, webhooks: list, types_manager, users_manager) -> _StubEventManager:
        """Routes the four managers to their stubs and makes every POST a 200"""
        event_manager = _StubEventManager()
        managers = {'WEBHOOKS': _StubWebhooksManager(webhooks), 'TYPES': types_manager,
                    'USERS': users_manager, 'WEBHOOKS_EVENT': event_manager}
        monkeypatch.setattr(webhook_helper.ManagerProvider, 'get_manager',
                            staticmethod(lambda manager_type, _user: managers[manager_type.name]))
        monkeypatch.setattr(webhook_helper.requests, 'post', lambda *_a, **_k: SimpleNamespace(status_code=200))
        monkeypatch.setattr(webhook_helper, 'refused_destination_reason', lambda *_a, **_k: None)

        return event_manager

    @staticmethod
    def _type_readable_by(group_id: int) -> dict[str, Any]:
        """A type ACL letting one group READ"""
        return {'acl': {'activated': True, 'groups': {'includes': {str(group_id): ['READ']}}}}

    def test_only_the_reader_owned_webhook_is_delivered_and_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The other webhook leaves no event (Q5: a skip records nothing)"""
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=HIDDEN_ID),
                    SimpleNamespace(public_id=2, url='http://b.test/h', owner_id=READER_ID)]
        owners = {READER_ID: SimpleNamespace(active=True, group_id=READER_GROUP),
                  HIDDEN_ID: SimpleNamespace(active=True, group_id=HIDDEN_GROUP)}
        types_manager = _StubTypesManager([self._type_readable_by(READER_GROUP)])
        users_manager = _StubUsersManager(owners)
        event_manager = self._wire(monkeypatch, webhooks, types_manager, users_manager)

        send_webhook_event(request_user=None, operation=WebhookEventType.UPDATE,
                           object_after={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert [event['webhook_id'] for event in event_manager.inserted] == [2]
        assert types_manager.calls == [({'public_id': EVENT_TYPE_ID}, {'_id': 0, 'acl': 1})]
        assert users_manager.calls == [[READER_ID, HIDDEN_ID]]

    def test_a_delete_is_scoped_by_the_type_before(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No state after: the deleted object's type decides"""
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=HIDDEN_ID)]
        owners = {HIDDEN_ID: SimpleNamespace(active=True, group_id=HIDDEN_GROUP)}
        types_manager = _StubTypesManager([self._type_readable_by(READER_GROUP)])
        event_manager = self._wire(monkeypatch, webhooks, types_manager, _StubUsersManager(owners))

        send_webhook_event(request_user=None, operation=WebhookEventType.DELETE,
                           object_before={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert not event_manager.inserted
        assert types_manager.calls[0][0] == {'public_id': EVENT_TYPE_ID}

    def test_an_unreadable_type_document_does_not_refuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A type that is gone: every active owner receives"""
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=HIDDEN_ID)]
        owners = {HIDDEN_ID: SimpleNamespace(active=True, group_id=HIDDEN_GROUP)}
        event_manager = self._wire(monkeypatch, webhooks, _StubTypesManager([]), _StubUsersManager(owners))

        send_webhook_event(request_user=None, operation=WebhookEventType.UPDATE,
                           object_after={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert [event['webhook_id'] for event in event_manager.inserted] == [1]

    def test_an_event_without_a_type_reads_no_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No type_id at all: the type read is skipped, not run with None"""
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=READER_ID)]
        owners = {READER_ID: SimpleNamespace(active=True, group_id=READER_GROUP)}
        types_manager = _StubTypesManager([self._type_readable_by(HIDDEN_GROUP)])
        event_manager = self._wire(monkeypatch, webhooks, types_manager, _StubUsersManager(owners))

        send_webhook_event(request_user=None, operation=WebhookEventType.UPDATE, object_after={'public_id': 5})

        assert not types_manager.calls
        assert [event['webhook_id'] for event in event_manager.inserted] == [1]

    def test_ownerless_webhooks_ask_for_no_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No owner ids: no user read, and nothing is delivered"""
        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=None),
                    SimpleNamespace(public_id=2, url='http://b.test/h')]
        users_manager = _StubUsersManager({})
        event_manager = self._wire(monkeypatch, webhooks, _StubTypesManager([]), users_manager)

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE,
                           object_after={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert not users_manager.calls
        assert not event_manager.inserted

    def test_a_failed_owner_read_delivers_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fails closed: the error is swallowed like every other read failure, and nothing leaves"""
        class _BrokenUsersManager:
            """The owner lookup fails"""
            def get_user_lookup(self, _user_ids):
                """Raises"""
                raise RuntimeError('users down')

        webhooks = [SimpleNamespace(public_id=1, url='http://a.test/h', owner_id=READER_ID)]
        event_manager = self._wire(monkeypatch, webhooks, _StubTypesManager([]), _BrokenUsersManager())

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE,
                           object_after={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert not event_manager.inserted

    def test_no_subscribed_webhook_reads_neither_type_nor_owners(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing to scope, nothing to read"""
        types_manager = _StubTypesManager([])
        users_manager = _StubUsersManager({})
        self._wire(monkeypatch, [], types_manager, users_manager)

        send_webhook_event(request_user=None, operation=WebhookEventType.CREATE,
                           object_after={'public_id': 5, 'type_id': EVENT_TYPE_ID})

        assert not types_manager.calls and not users_manager.calls
