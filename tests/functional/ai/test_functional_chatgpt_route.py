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
Functional smoke for the ``/chatgpt/message`` REST route

Covers the route handler's own behavior with the document_generator license guard bypassed and the
``ChatGptClient`` patched (no real OpenAI call): the happy-path reply round-trip, the 400 guards on
a missing / non-dict / message-less body, and the 500 mapping when the client fails. The
403-without-license gating is covered separately in the license suite
(``test_functional_document_generator_gating``).

The not-configured suite at the bottom is the exception: it deliberately does NOT patch the client,
because the whole point is what an installation with no ``[ChatGPT]`` section answers. That was the
gap this route shipped with - every test mocked the client away, so the path every fresh on-premise
install takes was the one path nothing exercised.
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest

from cmdb.interface.rest_api.routes.ai_routes import chatgpt_routes
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client_constants import (
    ChatGptStatusKey,
    CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE,
    CHATGPT_NOT_CONFIGURED_ENV_MESSAGE,
)
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.ai import ChatGptNotConfiguredError
from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/chatgpt/message'
STATUS_URL: str = '/chatgpt/status'
USER_MESSAGE: str = 'Generate a server documentation template'
MODEL_REPLY: str = '<p>generated</p>'


@pytest.fixture(autouse=True)
def _document_generator_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypasses the document_generator license guard so the handler itself is exercised."""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.DOCUMENT_GENERATOR,
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, *, reply: str = MODEL_REPLY,
                  side_effect: Exception | None = None) -> MagicMock:
    """Replaces ChatGptClient in the route module with a mock instance and returns it."""
    client_instance = MagicMock()
    if side_effect is not None:
        client_instance.send_template_request.side_effect = side_effect
    else:
        client_instance.send_template_request.return_value = reply

    monkeypatch.setattr(chatgpt_routes, 'ChatGptClient', lambda: client_instance)

    return client_instance


class TestSendChatgptMessage:
    """POST /chatgpt/message forwards the message to ChatGPT and returns the reply."""

    def test_returns_chatgpt_reply(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A valid message returns 200 with the model reply and forwards the message verbatim."""
        client_instance = _patch_client(monkeypatch)

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == MODEL_REPLY
        client_instance.send_template_request.assert_called_once_with(USER_MESSAGE)

    def test_empty_body_returns_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty JSON object has no message and returns 400."""
        _patch_client(monkeypatch)

        assert rest_api.post(ROUTE_URL, json={}).status_code == HTTPStatus.BAD_REQUEST

    def test_missing_message_key_returns_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A body without the 'message' key returns 400."""
        _patch_client(monkeypatch)

        assert rest_api.post(ROUTE_URL, json={'foo': 'bar'}).status_code == HTTPStatus.BAD_REQUEST

    def test_no_json_body_returns_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A request with no JSON body returns 400 (regression: previously a 500)."""
        _patch_client(monkeypatch)

        assert rest_api.post(ROUTE_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_client_failure_returns_500(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failure inside ChatGptClient surfaces as a 500."""
        _patch_client(monkeypatch, side_effect=RuntimeError('boom'))

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CHATGPT NOT CONFIGURED                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWhenChatgptIsNotConfigured:
    """An installation with no API key gets told so, by status and by message.

    These run against the REAL ChatGptClient - only the config reader underneath it is replaced -
    so what is asserted is the response a frontend actually receives.
    """

    def test_missing_config_section_answers_not_configured(self, rest_api, monkeypatch) -> None:
        """The default on-premise install: cmdb.conf carries no [ChatGPT] section at all."""
        monkeypatch.setattr(
            ChatGptClient,
            'resolve_api_key',
            staticmethod(_raiser(ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE))),
        )

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == chatgpt_routes.NOT_CONFIGURED_STATUS
        assert response.get_json()['message'] == CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE

    def test_the_message_names_the_section_and_the_entry(self, rest_api, monkeypatch) -> None:
        """The point of the fix: the caller is told what to add, not what the route was doing."""
        monkeypatch.setattr(
            ChatGptClient,
            'resolve_api_key',
            staticmethod(_raiser(ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE))),
        )

        message = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE}).get_json()['message']

        assert '[ChatGPT]' in message
        assert 'api_key' in message
        assert 'internal server error' not in message.lower()

    def test_missing_environment_variable_answers_not_configured(self, rest_api, monkeypatch) -> None:
        """The cloud half of the same state names the environment variable instead."""
        monkeypatch.setattr(
            ChatGptClient,
            'resolve_api_key',
            staticmethod(_raiser(ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_ENV_MESSAGE))),
        )

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == chatgpt_routes.NOT_CONFIGURED_STATUS
        assert 'CHATGPT_API_KEY' in response.get_json()['message']

    def test_the_unconfigured_reader_reaches_the_route_as_not_configured(self, rest_api, monkeypatch) -> None:
        """End to end from the config reader: a SectionError no longer surfaces as a 500."""
        reader = MagicMock()
        reader.get_value.side_effect = SectionError("The section 'ChatGPT' does not exist!")
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.ai_routes.chatgpt_client.SystemConfigReader',
            lambda *args, **kwargs: reader,
        )

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == chatgpt_routes.NOT_CONFIGURED_STATUS
        assert response.get_json()['message'] == CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE

    def test_a_real_failure_is_still_a_500(self, rest_api, monkeypatch) -> None:
        """The new arm must not swallow anything else - an OpenAI outage stays an internal error."""
        _patch_client(monkeypatch, side_effect=RuntimeError('OpenAI is down'))

        response = rest_api.post(ROUTE_URL, json={'message': USER_MESSAGE})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'while interacting with ChatGPT' in response.get_json()['message']


def _raiser(exception: Exception):
    """Returns a no-argument callable that raises the given exception."""
    def _raise(*_args, **_kwargs):
        raise exception

    return _raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                               GET /chatgpt/status                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheStatusRoute:
    """Answers one boolean about the installation, and nothing else."""

    def test_reports_configured_when_a_key_is_resolvable(self, rest_api, monkeypatch) -> None:
        """A resolvable key answers 200 with configured true."""
        monkeypatch.setattr(ChatGptClient, 'resolve_api_key', staticmethod(lambda: 'sk-a-real-key'))

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {ChatGptStatusKey.CONFIGURED.value: True}

    def test_reports_not_configured_when_no_key_exists(self, rest_api, monkeypatch) -> None:
        """The unconfigured installation answers 200 - the question was answered, nothing failed."""
        monkeypatch.setattr(
            ChatGptClient,
            'resolve_api_key',
            staticmethod(_raiser(ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE))),
        )

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {ChatGptStatusKey.CONFIGURED.value: False}

    def test_the_body_carries_nothing_but_the_flag(self, rest_api, monkeypatch) -> None:
        """No key, no source, no fragment of either - the whole point of a status route."""
        secret = 'sk-secret-value-0123456789'
        monkeypatch.setattr(ChatGptClient, 'resolve_api_key', staticmethod(lambda: secret))

        body = rest_api.get(STATUS_URL).get_data(as_text=True)

        assert secret not in body
        assert 'api_key' not in body
        assert 'CHATGPT_API_KEY' not in body
        assert list(rest_api.get(STATUS_URL).get_json()) == [ChatGptStatusKey.CONFIGURED.value]

    def test_the_real_reader_without_a_section_answers_false(self, rest_api, monkeypatch) -> None:
        """End to end through the real client: a missing [ChatGPT] section is configured false."""
        reader = MagicMock()
        reader.get_value.side_effect = SectionError("The section 'ChatGPT' does not exist!")
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.ai_routes.chatgpt_client.SystemConfigReader',
            lambda *args, **kwargs: reader,
        )

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {ChatGptStatusKey.CONFIGURED.value: False}

    def test_it_builds_no_openai_client(self, rest_api, monkeypatch) -> None:
        """A status check must not reach the network, so the SDK is never constructed."""
        monkeypatch.setattr(ChatGptClient, 'resolve_api_key', staticmethod(lambda: 'sk-a-real-key'))
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.ai_routes.chatgpt_client.OpenAI',
            _raiser(AssertionError('the OpenAI client must not be constructed by a status check')),
        )

        assert rest_api.get(STATUS_URL).status_code == HTTPStatus.OK

    def test_it_requires_authentication(self, rest_api) -> None:
        """No right is required, but a token is."""
        response = rest_api.get(STATUS_URL, environ_overrides={'HTTP_AUTHORIZATION': ''})

        assert response.status_code == HTTPStatus.UNAUTHORIZED
