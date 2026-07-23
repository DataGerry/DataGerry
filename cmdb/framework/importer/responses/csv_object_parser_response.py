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
Implementation of CsvObjectParserResponse
"""
from cmdb.framework.importer.responses.object_parser_response import ObjectParserResponse
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CsvObjectParserResponse - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectParserResponse(ObjectParserResponse):
    """
    Represents the response of a CSV object parser

    Extends: ObjectParserResponse
    """
    def __init__(self, count: int, entries: list, entry_length: int, header: list | None = None) -> None:
        """
        Initializes a CsvObjectParserResponse instance

        Args:
            count (int): The total number of parsed entries
            entries (list): A list of parsed entries
            entry_length (int): The number of fields in each entry
            header (list | None): The CSV header row as a list of column names. Defaults to an empty list
        """
        self.entry_length: int = entry_length
        self.header: list = header or []
        super().__init__(count=count, entries=entries)


    def get_entry_length(self) -> int:
        """
        Retrieves the number of fields in each entry

        Returns:
            int: The number of fields per entry
        """
        return self.entry_length


    def get_header_list(self) -> list:
        """
        Retrieves the header row

        Returns:
            list: The CSV header as a list of column names (empty when no header was parsed)
        """
        return self.header
