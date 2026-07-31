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
Implementation of CsvObjectParser

Besides reading the rows, the parser resolves each header column to the IDENTIFIER the rest of the
import works with: a column may either be a plain field name (what a CSV export emits) or carry its
name in a trailing bracketed group (what the object-import template emits, so a person filling the
file in reads a label). Both notations are accepted, decided per column, and the file's original
header line is handed on untouched next to the resolved one.
"""
import csv
import re
from logging import Logger, getLogger

from cmdb.utils.cast import auto_cast
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.importer_constants import CSV_HEADER_IDENTIFIER_PATTERN, CsvParserConfigKey
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse

from cmdb.errors.importer import ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Compiled once: the header of every parsed CSV runs through it
_HEADER_IDENTIFIER_REGEX = re.compile(CSV_HEADER_IDENTIFIER_PATTERN)


def extract_column_identifier(header_cell: str) -> str:
    """
    Resolves one CSV header column to the identifier the import maps it by

    A column ending in a bracketed group carries its field name there - that is the object-import
    template's notation (`Port [MDS-Interfaces] [port]` -> `port`), and the LAST group wins so the MDS
    marker never shadows the name. Anything else is an identifier already and is returned verbatim, which
    is what a plain export header is. A bracketed group that holds only whitespace names nothing, so the
    cell stands as it is rather than resolving to an empty column key

    Args:
        header_cell (str): One raw header column, as read from the file

    Returns:
        str: The column's identifier
    """
    if not isinstance(header_cell, str):
        return header_cell

    match = _HEADER_IDENTIFIER_REGEX.search(header_cell)

    if not match:
        return header_cell

    identifier = match.group(1).strip()

    return identifier or header_cell


def normalize_csv_header(header: list | None) -> list:
    """
    Resolves every column of a CSV header row to its identifier

    Args:
        header (list | None): The raw header row, or None when the file carries none

    Returns:
        list: The resolved header, column for column and in the same order (empty when there was none)
    """
    return [extract_column_identifier(column) for column in header or []]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CsvObjectParser - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectParser(BaseObjectParser, CSVContent):
    """
    Parser for CSV files that extracts structured data from CSV content

    Attributes:
        DEFAULT_QUOTE_CHAR (str): Default quote character for CSV parsing
        DEFAULT_CONFIG (dict): Default configuration for CSV parsing
    """
    DEFAULT_QUOTE_CHAR: str = '"'
    DEFAULT_CONFIG: dict = {
        CsvParserConfigKey.DELIMITER.value: ',',
        CsvParserConfigKey.NEWLINE.value: '',
        CsvParserConfigKey.QUOTE_CHAR.value: DEFAULT_QUOTE_CHAR,
        CsvParserConfigKey.ESCAPE_CHAR.value: None,
        CsvParserConfigKey.HEADER.value: True,
        CsvParserConfigKey.ENCODING.value: 'utf-8',
    }

    def parse(self, file: str) -> CsvObjectParserResponse:
        """
        Parses a CSV file and returns structured data

        The returned ``header`` holds the resolved column IDENTIFIERS (see extract_column_identifier), so
        a template's decorated columns and a plain export header are indistinguishable to every consumer.
        The file's original header line travels along as ``raw_header`` for anything that wants to show
        the labels

        Args:
            file (str): Path to the CSV file

        Returns:
            CsvObjectParserResponse: A structured response containing parsed data

        Raises:
            ParserRuntimeError: If the file cannot be read/parsed, or contains no data rows
        """
        run_config = self.get_config()
        header: list | None = None
        entries: list[dict] = []

        try:
            with open(
                file,
                'r',
                encoding=run_config.get(CsvParserConfigKey.ENCODING.value),
                newline=run_config.get(CsvParserConfigKey.NEWLINE.value),
            ) as csv_file:
                csv_reader = csv.reader(
                    csv_file,
                    delimiter=run_config.get(CsvParserConfigKey.DELIMITER.value),
                    quotechar=run_config.get(CsvParserConfigKey.QUOTE_CHAR.value),
                    escapechar=run_config.get(CsvParserConfigKey.ESCAPE_CHAR.value),
                    skipinitialspace=True,
                )

                if run_config.get(CsvParserConfigKey.HEADER.value):
                    header = next(csv_reader, None)

                for row in csv_reader:
                    entries.append(self._generate_index_pair([auto_cast(entry) for entry in row]))

                if not entries:
                    raise ParserRuntimeError(f"[{self.__class__.__name__}]: No content data!")
        except ParserRuntimeError:
            raise
        except Exception as err:
            LOGGER.error("Error parsing CSV file: %s", err)
            raise ParserRuntimeError(f"[{self.__class__.__name__}]: An error occurred: {err}") from err

        return CsvObjectParserResponse(
            count=len(entries),
            entries=entries,
            entry_length=len(entries[0]),
            header=normalize_csv_header(header),
            raw_header=header,
        )


    @staticmethod
    def _generate_index_pair(row: list) -> dict:
        """
        Generates a dictionary mapping index positions to row values

        Args:
            row (list): A list representing a single row of CSV data

        Returns:
            dict: A dictionary mapping column indices to values
        """
        return dict(enumerate(row))
