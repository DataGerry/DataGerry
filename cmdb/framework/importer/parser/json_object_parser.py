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
Implementation of JsonObjectParser
"""
import json
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.importer.content_types import JSONContent
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               JsonObjectParser - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonObjectParser(BaseObjectParser, JSONContent):
    """
    A parser class that reads and processes JSON files

    Extends: BaseObjectParser, JSONContent

    Attributes:
        DEFAULT_CONFIG (dict): The default configuration for the parser. Includes:
            - indent: The number of spaces to use for indentation in the output (default 2)
            - encoding: The file encoding used when reading the file (default 'UTF-8')
    """
    DEFAULT_CONFIG: dict[str, Any] = {
        'indent': 2,
        'encoding': 'UTF-8'
    }


    def __init__(self, parser_config: dict = None) -> None:
        """
        Initializes the JsonObjectParser with a given configuration

        Args:
            parser_config (dict, optional): Custom configuration to override default settings
                If None, the default configuration will be used
        """
        super().__init__(parser_config)


    def parse(self, file) -> JsonObjectParserResponse:
        """
        Parses the provided JSON file and returns a response containing the parsed data

        The file is read with the encoding specified in the configuration, and the JSON data is loaded.
        It returns a structured response containing the number of entries and the parsed data

        Args:
            file (str): The path to the JSON file to be parsed

        Returns:
            JsonObjectParserResponse: A structured response containing:
                - count: The number of entries in the parsed JSON data
                - entries: The actual parsed JSON data (usually a list or dictionary)
        """
        run_config = self.get_config()

        with open(file, 'r', encoding=run_config.get('encoding')) as json_file:
            parsed = json.load(json_file)

        return JsonObjectParserResponse(count=len(parsed), entries=parsed)
