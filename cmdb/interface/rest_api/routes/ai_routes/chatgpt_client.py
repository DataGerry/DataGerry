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
    DOCUMENT_GENERATOR_PROMPT,
)
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
    """
    def __init__(self) -> None:
        """
        Constructs the wrapped OpenAI client

        In cloud (non-local) mode the API key is read from the ``ChatGptKeys.ENV_API_KEY``
        environment variable. In every other mode it is read from ``ChatGptKeys.CONFIG_API_KEY``
        within the ``ChatGptKeys.CONFIG_SECTION`` section of the system config file
        """
        if current_app.cloud_mode and not current_app.local_mode:
            self.client: OpenAI = OpenAI(api_key=os.getenv(ChatGptKeys.ENV_API_KEY.value))
        else:
            scr = SystemConfigReader()
            self.client: OpenAI = OpenAI(api_key=scr.get_value(ChatGptKeys.CONFIG_API_KEY, ChatGptKeys.CONFIG_SECTION))


    def get_client(self) -> OpenAI:
        """
        Returns the underlying ``OpenAI`` client instance

        Returns:
            OpenAI: The wrapped OpenAI SDK client
        """
        return self.client


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
