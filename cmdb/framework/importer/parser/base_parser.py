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
Implementation of BaseParser
"""
from logging import Logger, getLogger

from cmdb.framework.importer.responses.base_parser_response import BaseParserResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  BaseParser - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseParser:
    """
    A base class for parsers that handle file parsing with configurable settings

    Attributes:
        DEFAULT_CONFIG (dict): Default configuration settings, merged under any caller-supplied config
    """
    DEFAULT_CONFIG: dict = {}

    def __init__(self, parser_config: dict | None = None) -> None:
        """
        Initializes the BaseParser with a given configuration

        The effective configuration is DEFAULT_CONFIG overlaid with the caller-supplied values, so
        omitted keys keep their defaults.

        Args:
            parser_config (dict | None): Parser-specific settings. If None, only DEFAULT_CONFIG is used
        """
        self.parser_config: dict = {**self.DEFAULT_CONFIG, **(parser_config or {})}


    def get_config(self) -> dict:
        """
        Retrieves the current parser configuration

        Returns:
            dict: The parser's effective configuration settings
        """
        return self.parser_config


    def parse(self, file: str) -> BaseParserResponse:
        """
        Parses the given file

        Args:
            file (str): Path to the file to be parsed

        Returns:
            BaseParserResponse: The result of the parsing process

        Raises:
            NotImplementedError: This method must be implemented in a subclass
        """
        raise NotImplementedError("Subclasses must implement the `parse` method!")
