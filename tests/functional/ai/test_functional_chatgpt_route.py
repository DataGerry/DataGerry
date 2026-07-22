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
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest

from cmdb.interface.rest_api.routes.ai_routes import chatgpt_routes
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/chatgpt/message'
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
