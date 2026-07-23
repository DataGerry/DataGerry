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
"""
import csv
from logging import Logger, getLogger

from cmdb.utils.cast import auto_cast
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.importer_constants import CsvParserConfigKey
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse

from cmdb.errors.importer import ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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
            header=header,
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
