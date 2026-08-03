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
    def __init__(
        self,
        count: int,
        entries: list,
        entry_length: int,
        header: list | None = None,
        raw_header: list | None = None,
    ) -> None:
        """
        Initializes a CsvObjectParserResponse instance

        Args:
            count (int): The total number of parsed entries
            entries (list): A list of parsed entries
            entry_length (int): The number of fields in each entry
            header (list | None): The resolved header - one column IDENTIFIER per entry, which is what
                the mapping and the MDS reassembly work with. Defaults to an empty list
            raw_header (list | None): The file's original header line, column for column. Only differs
                from `header` for a decorated (import-template) header; defaults to `header` so a
                consumer always has both
        """
        self.entry_length: int = entry_length
        self.header: list = header or []
        self.raw_header: list = raw_header if raw_header is not None else list(self.header)
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
        Retrieves the resolved header row

        Returns:
            list: The CSV header as a list of column identifiers (empty when no header was parsed)
        """
        return self.header


    def get_raw_header_list(self) -> list:
        """
        Retrieves the file's original header row

        Returns:
            list: The CSV header exactly as it was read, labels and all (empty when none was parsed)
        """
        return self.raw_header
