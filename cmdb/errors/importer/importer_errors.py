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
Contains all Importer error classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ImporterError(Exception):
    """
    Raised to catch all Importer related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all Importer related errors
        """
        super().__init__(err)

# -------------------------------------------------- IMPORTER ERRORS ------------------------------------------------- #

class ImportRuntimeError(ImporterError):
    """
    Raised when an errors occurs during import
    """


class ParserRuntimeError(ImporterError):
    """
    Raised when an errors occures during parsing files
    """


class ParserNoContentError(ParserRuntimeError):
    """
    Raised when a file parses correctly but carries no data rows to import

    Kept apart from a plain ParserRuntimeError because the two need opposite answers: a malformed file or
    a wrong parser configuration is a parsing problem, while an empty file - a freshly downloaded import
    template, for instance - parsed perfectly and simply has nothing in it. Naming that separately lets
    the routes report the real reason instead of pointing at settings that are not at fault
    """


class ImporterLoadError(ImporterError):
    """
    Raised when an error occurs loading the importer
    """


class ParserLoadError(ImporterError):
    """
    Raised when an error occurs loading the parser
    """
