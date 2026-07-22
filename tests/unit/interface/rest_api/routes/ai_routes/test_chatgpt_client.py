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
Unit tests for cmdb.interface.rest_api.routes.ai_routes.chatgpt_client.ChatGptClient

Pure tests: no Flask app context, no real OpenAI SDK calls. ``current_app``, the ``OpenAI``
constructor and the ``SystemConfigReader`` are patched at the module level so each branch of
``__init__`` and ``get_document_generator_prompt`` is exercised in isolation. The trivial
one-line ``get_client`` is intentionally outside the scope
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client_constants import ChatGptKeys
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.ai_routes.chatgpt_client'

CLOUD_API_KEY: str = 'cloud-api-key'
LOCAL_API_KEY: str = 'local-api-key'
ENV_PROMPT_VALUE: str = 'env-supplied prompt'
USER_MESSAGE: str = 'Generate a server documentation template'
MODEL_REPLY: str = '<p>generated</p>'

# A phrase the embedded fallback prompt is guaranteed to contain — used to confirm the fallback
# branch ran without coupling the test to the full ~150-line prompt text.
EMBEDDED_PROMPT_MARKER: str = 'DATAGerry'


def _mock_current_app(*, cloud_mode: bool, local_mode: bool) -> MagicMock:
    """Builds a ``current_app`` stand-in carrying the two mode flags the client branches on."""
    app = MagicMock()
    app.cloud_mode = cloud_mode
    app.local_mode = local_mode
    return app


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   __init__                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """``ChatGptClient.__init__`` wires the underlying OpenAI client per the mode flags."""

    def test_cloud_mode_uses_environment_api_key(self) -> None:
        """In cloud (non-local) mode the OpenAI client is constructed with the env API key."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=True, local_mode=False)), \
             patch(f'{MODULE_PATH}.OpenAI') as openai_cls, \
             patch.dict('os.environ', {ChatGptKeys.ENV_API_KEY: CLOUD_API_KEY}, clear=False):
            ChatGptClient()

        openai_cls.assert_called_once_with(api_key=CLOUD_API_KEY)

    def test_local_mode_uses_system_config_reader(self) -> None:
        """In local (or non-cloud) mode the API key is read from the SystemConfigReader."""
        scr_instance = MagicMock()
        scr_instance.get_value.return_value = LOCAL_API_KEY

        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=False, local_mode=False)), \
             patch(f'{MODULE_PATH}.OpenAI') as openai_cls, \
             patch(f'{MODULE_PATH}.SystemConfigReader', return_value=scr_instance):
            ChatGptClient()

        scr_instance.get_value.assert_called_once_with(ChatGptKeys.CONFIG_API_KEY, ChatGptKeys.CONFIG_SECTION)
        openai_cls.assert_called_once_with(api_key=LOCAL_API_KEY)

    def test_cloud_plus_local_uses_system_config_reader(self) -> None:
        """``local_mode=True`` overrides the cloud branch even when ``cloud_mode`` is also True."""
        scr_instance = MagicMock()
        scr_instance.get_value.return_value = LOCAL_API_KEY

        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=True, local_mode=True)), \
             patch(f'{MODULE_PATH}.OpenAI') as openai_cls, \
             patch(f'{MODULE_PATH}.SystemConfigReader', return_value=scr_instance):
            ChatGptClient()

        openai_cls.assert_called_once_with(api_key=LOCAL_API_KEY)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       get_document_generator_prompt                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetDocumentGeneratorPrompt:
    """Branching of ``get_document_generator_prompt`` across cloud/local mode and env presence."""

    def test_cloud_returns_env_prompt_when_set(self) -> None:
        """In cloud (non-local) mode with the env var set, the env value is returned verbatim."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=True, local_mode=False)), \
             patch.dict('os.environ', {ChatGptKeys.ENV_DOCGEN_PROMPT: ENV_PROMPT_VALUE}, clear=False):
            prompt = ChatGptClient.get_document_generator_prompt(MagicMock())

        assert prompt == ENV_PROMPT_VALUE

    def test_cloud_falls_back_to_embedded_when_env_missing(self) -> None:
        """In cloud mode with the env var absent, the embedded prompt is returned as fallback."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=True, local_mode=False)), \
             patch.dict('os.environ', {}, clear=True):
            prompt = ChatGptClient.get_document_generator_prompt(MagicMock())

        assert EMBEDDED_PROMPT_MARKER in prompt
        assert prompt != ENV_PROMPT_VALUE

    def test_cloud_falls_back_to_embedded_when_env_is_empty(self) -> None:
        """An empty-string env value counts as 'not set' and triggers the embedded fallback."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=True, local_mode=False)), \
             patch.dict('os.environ', {ChatGptKeys.ENV_DOCGEN_PROMPT: ''}, clear=False):
            prompt = ChatGptClient.get_document_generator_prompt(MagicMock())

        assert EMBEDDED_PROMPT_MARKER in prompt

    def test_local_mode_ignores_env_and_returns_embedded(self) -> None:
        """In local mode the env var is never consulted; the embedded prompt is returned."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=False, local_mode=True)), \
             patch.dict('os.environ', {ChatGptKeys.ENV_DOCGEN_PROMPT: ENV_PROMPT_VALUE}, clear=False):
            prompt = ChatGptClient.get_document_generator_prompt(MagicMock())

        assert EMBEDDED_PROMPT_MARKER in prompt
        assert prompt != ENV_PROMPT_VALUE

    def test_not_cloud_mode_returns_embedded(self) -> None:
        """When ``cloud_mode`` is False the embedded prompt is returned regardless of the env."""
        with patch(f'{MODULE_PATH}.current_app', _mock_current_app(cloud_mode=False, local_mode=False)), \
             patch.dict('os.environ', {ChatGptKeys.ENV_DOCGEN_PROMPT: ENV_PROMPT_VALUE}, clear=False):
            prompt = ChatGptClient.get_document_generator_prompt(MagicMock())

        assert EMBEDDED_PROMPT_MARKER in prompt
        assert prompt != ENV_PROMPT_VALUE


# -------------------------------------------------------------------------------------------------------------------- #
#                                          send_template_request                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSendTemplateRequest:
    """``send_template_request`` resolves the prompt, forwards to the OpenAI client, returns text."""

    def _build_client_with_response(self, output_text: str) -> tuple[ChatGptClient, MagicMock]:
        """Builds a ChatGptClient whose ``client.responses.create`` returns the given text."""
        instance = ChatGptClient.__new__(ChatGptClient)
        instance.client = MagicMock()
        instance.client.responses.create.return_value = MagicMock(output_text=output_text)
        return instance, instance.client.responses.create

    def test_returns_output_text(self) -> None:
        """On success the model's ``output_text`` is returned to the caller."""
        instance, _ = self._build_client_with_response(MODEL_REPLY)

        with patch.object(ChatGptClient, 'get_document_generator_prompt', return_value=ENV_PROMPT_VALUE):
            result = instance.send_template_request(USER_MESSAGE)

        assert result == MODEL_REPLY

    def test_forwards_payload_with_system_and_user_roles(self) -> None:
        """The system prompt and user message are forwarded as the two ``input`` entries."""
        instance, create_mock = self._build_client_with_response(MODEL_REPLY)

        with patch.object(ChatGptClient, 'get_document_generator_prompt', return_value=ENV_PROMPT_VALUE):
            instance.send_template_request(USER_MESSAGE)

        call_kwargs: dict[str, Any] = create_mock.call_args.kwargs
        assert call_kwargs['model'] == ChatGptKeys.MODEL
        assert call_kwargs['input'] == [
            {'role': 'system', 'content': ENV_PROMPT_VALUE},
            {'role': 'user', 'content': USER_MESSAGE},
        ]

    def test_raises_when_resolved_prompt_is_empty(self) -> None:
        """If the resolved prompt is empty the defensive guard raises ``ValueError`` before the API call."""
        instance, create_mock = self._build_client_with_response(MODEL_REPLY)

        with patch.object(ChatGptClient, 'get_document_generator_prompt', return_value=''):
            with pytest.raises(ValueError):
                instance.send_template_request(USER_MESSAGE)

        create_mock.assert_not_called()
