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
    def __init__(self, err: str) -> None:
        """
        Raised to catch all Exporter related errors
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
