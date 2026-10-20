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
Contains all Exporter Error Classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ExporterError(Exception):
    """
    Raised to catch all Exporter related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all Exporter related errors

        Takes the wrapped exception itself as readily as a message: str() reads the same either way,
        but args[0] then carries the error being wrapped, which a caller can branch on

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# -------------------------------------------------- Exporter ERRORS ------------------------------------------------- #

class ExporterCSVTypeError(ExporterError):
    """
    Raised when the Exporter trys to export Objects of different CmdbTypes
    """


class ExporterMetadataError(ExporterError):
    """
    Raised when the render-view `metadata` override of an export request is unusable

    The override selects the identity header and the columns of a tabular export, so it has to be a
    JSON object whose `header` / `columns` are lists. A string where a list is expected would be
    spread character by character into the header, which is why it is refused instead of exported
    """


class ExporterColumnError(ExporterError):
    """
    Raised when a tabular export (CSV / XLSX) would produce duplicate column names

    A field name is expected to be unique within a CmdbType (across its regular fields and all
    multi-data-section fields). If two fields resolve to the same column name the exported columns
    would collide, so the export is refused instead of silently overwriting a value
    """


class ExporterCharacterError(ExporterError):
    """
    Raised when an XML export would have to carry a character XML 1.0 cannot represent

    Control characters other than tab, line feed and carriage return (and lone surrogates) have no XML
    1.0 spelling, not even as a character reference, so a document holding one could not be read back by
    any XML parser. The export is refused instead of answering such a document
    """
