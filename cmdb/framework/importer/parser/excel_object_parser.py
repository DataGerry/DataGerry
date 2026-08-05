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
Implementation of ExcelObjectParser
"""
from logging import Logger, getLogger
from typing import Any
from openpyxl import load_workbook

from cmdb.framework.importer.content_types import XLSXContent
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.excel_object_parser_response import ExcelObjectParserResponse

from cmdb.errors.importer import ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ExcelObjectParser - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ExcelObjectParser(BaseObjectParser, XLSXContent):
    """
    Parses Excel files (XLSX) to extract data according to a given configuration

    Extends: BaseObjectParser, XLSXContent

    Attributes:
        DEFAULT_CONFIG (dict): Default configuration for the parser
            - sheet_name: The name of the sheet to parse (default 'Sheet1')
            - header: Whether the sheet includes a header (default True)
    """
    DEFAULT_CONFIG: dict[str, Any] = {
        'sheet_name': 'Sheet1',
        'header': True
    }

    def __init__(self, parser_config: dict = None):
        super().__init__(parser_config)


    def parse(self, file) -> ExcelObjectParserResponse:

        run_config = self.get_config()
        try:
            working_sheet = run_config['sheet_name']
        except (IndexError, ValueError, KeyError) as err:
            raise ParserRuntimeError(f"[ExcelObjectParser] An error occured: {err}") from err

        wb = load_workbook(file)

        try:
            wb[working_sheet]
        except KeyError as err:
            raise ParserRuntimeError(f"[ExcelObjectParser] An error occured: {err}") from err

        return ExcelObjectParserResponse(0, [], 0)
