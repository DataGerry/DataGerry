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
Definition of the ChatGptClient
"""
import os
from logging import Logger, getLogger

from flask import current_app
from openai import OpenAI

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client_constants import (
    ChatGptKeys,
    CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE,
    CHATGPT_NOT_CONFIGURED_ENV_MESSAGE,
    DOCUMENT_GENERATOR_PROMPT,
)

from cmdb.errors.ai import ChatGptNotConfiguredError
from cmdb.errors.system_config import ConfigFileError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ChatGptClient - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ChatGptClient:
    """
    Thin wrapper around the OpenAI client configured for the DATAGerry document generator

    Picks its API key from the environment in cloud (non-local) mode and from the SystemConfigReader
    ``[ChatGPT]`` section otherwise. ``send_template_request`` is the single public entry point used
    by the AI routes; the system prompt it sends is resolved by
    :py:meth:`get_document_generator_prompt`

    **An unconfigured installation is told apart from a failing one.** Constructing the client
    resolves the API key first and raises ``ChatGptNotConfiguredError`` when there is none, so the
    route can answer "ChatGPT is not configured" instead of the generic 500 that any escaping
    exception would otherwise become. Every way of having no key - no section, no entry, an empty
    value, an unset environment variable - ends in that one error
    """
    def __init__(self) -> None:
        """
        Constructs the wrapped OpenAI client

        Raises:
            ChatGptNotConfiguredError: When no usable API key is configured for the current mode
        """
        self.client: OpenAI = OpenAI(api_key=self.resolve_api_key())


    @staticmethod
    def resolve_api_key() -> str:
        """
        Resolves the OpenAI API key for the current mode, or reports that there is none

        In cloud (non-local) mode the key comes from the ``ChatGptKeys.ENV_API_KEY`` environment
        variable. In every other mode it comes from ``ChatGptKeys.CONFIG_API_KEY`` within the
        ``ChatGptKeys.CONFIG_SECTION`` section of the system config file, where **three** distinct
        outcomes all mean "not configured": a missing section, a missing entry, and an entry whose
        value is empty. The reader's ``auto_cast`` may hand back a non-string (a digits-only key
        arrives as an int), so the value is stringified before it reaches the OpenAI client

        Raises:
            ChatGptNotConfiguredError: When no usable API key is configured for the current mode

        Returns:
            str: The configured API key
        """
        if current_app.cloud_mode and not current_app.local_mode:
            env_api_key: str | None = os.getenv(ChatGptKeys.ENV_API_KEY.value)

            if not env_api_key or not env_api_key.strip():
                raise ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_ENV_MESSAGE)

            return env_api_key

        try:
            # The enum members are passed by .value: they compare equal to their string either way,
            # but a ConfigFileError formats what it was given - and the member renders as
            # 'ChatGptKeys.CONFIG_SECTION', which names DataGerry's internals rather than the
            # section an admin has to add
            configured_api_key = SystemConfigReader().get_value(
                ChatGptKeys.CONFIG_API_KEY.value,
                ChatGptKeys.CONFIG_SECTION.value,
            )
        except (ConfigFileError, KeyError) as err:
            # ConfigFileError covers the missing section and the unloaded file; KeyError is what the
            # reader raises for a section that exists without the entry
            raise ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE) from err

        api_key: str = str(configured_api_key) if configured_api_key is not None else ''

        if not api_key.strip():
            raise ChatGptNotConfiguredError(CHATGPT_NOT_CONFIGURED_CONFIG_MESSAGE)

        return api_key


    def send_template_request(self, user_message: str) -> str:
        """
        Sends a document-template generation request to ChatGPT and returns the model's reply

        The system prompt is resolved via :py:meth:`get_document_generator_prompt`; the user
        message is forwarded verbatim as the ``user`` role content. The model returns clean
        HTML suitable for the TinyMCE editor used by the document generator

        Args:
            user_message (str): Free-form user request describing the document to generate

        Raises:
            ValueError: When the resolved system prompt is empty (defensive; under normal
                configuration the embedded prompt is always available as a fallback)

        Returns:
            str: The model's ``output_text`` reply
        """
        prompt: str = self.get_document_generator_prompt()

        if not prompt:
            raise ValueError("No prompt provided for ChatGPT document generator prompt!")

        response = self.client.responses.create(
            model=ChatGptKeys.MODEL,
            input=[
                {
                    "role": "system",
                    "content": prompt
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )

        return response.output_text


    def get_document_generator_prompt(self) -> str:
        """
        Returns the system prompt used by the document generator

        In cloud (non-local) mode the prompt is sourced from the ``ChatGptKeys.ENV_DOCGEN_PROMPT``
        environment variable when set to a non-empty value; if the variable is missing or empty,
        the embedded ``DOCUMENT_GENERATOR_PROMPT`` is returned as a fallback. In every other
        mode the embedded prompt is returned unconditionally

        Returns:
            str: The system prompt to send to ChatGPT (always non-empty)
        """
        if current_app.cloud_mode and not current_app.local_mode:
            env_prompt: str | None = os.getenv(ChatGptKeys.ENV_DOCGEN_PROMPT.value)
            if env_prompt:
                return env_prompt

        return DOCUMENT_GENERATOR_PROMPT
