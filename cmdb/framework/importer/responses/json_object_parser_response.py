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
JsonObjectParserResponse
"""
import logging

from cmdb.framework.importer.responses.object_parser_response import ObjectParserResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           JsonObjectParserResponse - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonObjectParserResponse(ObjectParserResponse):
    """
    A response class that represents the result of parsing a JSON file

    Extends: ObjectParserResponse
    """

    def __init__(self, count: int, entries: list) -> None:
        """
        Initializes the JsonObjectParserResponse instance with the provided count and entries

        Args:
            count (int): The number of entries in the parsed data
            entries (list): The parsed data (usually a list or dictionary) from the JSON file
        """
        super().__init__(count=count, entries=entries)
