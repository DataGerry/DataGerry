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
from cmdb.framework.importer.importer_constants import JsonParserConfigKey
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse

from cmdb.errors.importer import ParserRuntimeError
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
            - encoding: The file encoding used when reading the file (default 'UTF-8')
    """
    DEFAULT_CONFIG: dict[str, Any] = {
        JsonParserConfigKey.ENCODING.value: 'UTF-8',
    }

    def parse(self, file: str) -> JsonObjectParserResponse:
        """
        Parses the provided JSON file and returns a response containing the parsed data

        The file is read with the encoding specified in the configuration, and the JSON data is loaded.
        It returns a structured response containing the number of entries and the parsed data.

        Args:
            file (str): The path to the JSON file to be parsed

        Returns:
            JsonObjectParserResponse: A structured response containing:
                - count: The number of objects in the parsed JSON list
                - entries: The parsed objects (the top-level JSON list)

        Raises:
            ParserRuntimeError: If the file cannot be read/parsed, or its top level is not a JSON list
        """
        run_config = self.get_config()

        try:
            with open(file, 'r', encoding=run_config.get(JsonParserConfigKey.ENCODING.value)) as json_file:
                parsed = json.load(json_file)
        except Exception as err:
            LOGGER.error("Error parsing JSON file: %s", err)
            raise ParserRuntimeError(f"[{self.__class__.__name__}]: An error occurred: {err}") from err

        # The import shape is a list of objects; require it so ``count`` is the object count (a dict would
        # otherwise count its keys, a scalar would fail on len())
        if not isinstance(parsed, list):
            raise ParserRuntimeError(
                f"[{self.__class__.__name__}]: expected a JSON list of objects at the top level"
            )

        return JsonObjectParserResponse(count=len(parsed), entries=parsed)
