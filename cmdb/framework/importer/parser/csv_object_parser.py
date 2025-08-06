# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import logging

from cmdb.utils.cast import auto_cast
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse

from cmdb.errors.importer import ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CsvObjectParser - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectParser(BaseObjectParser, CSVContent):
    """
    Parser for CSV files that extracts structured data from CSV content.
    
    Attributes:
        BYTE_ORDER_MARK (str): Unicode BOM character used in some CSV files
        BAD_DELIMITERS (list): Characters that are problematic as delimiters
        DEFAULT_QUOTE_CHAR (str): Default quote character for CSV parsing
        DEFAULT_CONFIG (dict): Default configuration for CSV parsing
    """
    BYTE_ORDER_MARK = '\ufeff'
    BAD_DELIMITERS = ['\r', '\n', '"', BYTE_ORDER_MARK]
    DEFAULT_QUOTE_CHAR = '"'
    DEFAULT_CONFIG = {
        'delimiter': ',',
        'newline': '',
        'quoteChar': DEFAULT_QUOTE_CHAR,
        'escapeChar': None,
        'header': True
    }

    def __init__(self, parser_config: dict = None):
        """
        Initializes the CsvObjectParser with an optional parser configuration

        Args:
            parser_config (dict | None): Configuration dictionary for the parser
        """
        super().__init__(parser_config)


    def parse(self, file) -> CsvObjectParserResponse:
        """
        Parses a CSV file and returns structured data
        
        Args:
            file (str): Path to the CSV file

        Raises:
            ParserRuntimeError: If an error occurs while reading or parsing the file

        Returns:
            CsvObjectParserResponse: A structured response containing parsed data
        """
        run_config = self.get_config()
        parsed = {
            'count': 0,
            'header': None,
            'entries': [],
            'entry_length': 0
        }
        try:
            with open(file, 'r', encoding='utf-8', newline=run_config.get('newline')) as csv_file:
                csv_reader = csv.reader(
                    csv_file,
                    delimiter=run_config.get('delimiter'),
                    quotechar=run_config.get('quoteChar'),
                    escapechar=run_config.get('escapeChar'),
                    skipinitialspace=True
                )

                if run_config.get('header'):
                    parsed['header'] = next(csv_reader, None)

                for row in csv_reader:
                    row_list = [auto_cast(entry) for entry in row]
                    parsed['entries'].append(self.__generate_index_pair(row_list))
                    parsed['count'] += 1

                if parsed['entries']:
                    parsed['entry_length'] = len(parsed['entries'][0])
                else:
                    raise ParserRuntimeError(f"[{self.__class__.__name__}]: No content data!")
        except Exception as err:
            LOGGER.error("Error parsing CSV file: %s", err)
            raise ParserRuntimeError(f"[{self.__class__.__name__}]: An error occurred: {err}") from err

        return CsvObjectParserResponse(**parsed)


    @staticmethod
    def __generate_index_pair(row: list) -> dict:
        """
        Generates a dictionary mapping index positions to row values
        
        Args:
            row (list[str]): A list representing a single row of CSV data
        
        Returns:
            dict[int, str]: A dictionary mapping column indices to values
        """
        return dict(enumerate(row))
