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
Implementation of SupportedExporterExtension
"""
import logging
from typing import Any

from cmdb.utils.helpers import load_class
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          SupportedExporterExtension - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class SupportedExporterExtension:
    """Maintains a list of supported export formats (CSV, JSON, XLSX, XML)."""

    DEFAULT_EXTENSIONS: list[str] = [
        "CsvExportFormat",
        "JsonExportFormat",
        "XlsxExportFormat",
        "XmlExportFormat"
    ]

    def __init__(self, extensions: list | None = None):
        """
        Initializes the SupportedExporterExtension with a default or custom list of extensions.

        Args:
            extensions (list): Additional export formats to include
        """
        self.extensions = self.DEFAULT_EXTENSIONS + (extensions or [])


    def get_extensions(self) -> list:
        """
        Retrieve a list of supported export extensions

        Returns:
            list: A list of file extensions supported for export
        """
        return self.extensions


    def convert_to(self) -> list[dict[str, Any]]:
        """
        Converts the supported export extensions into a list of dictionaries 
        that includes relevant information about each format

        Returns:
            list[dict[str, Any]]: A list of dictionaries representing supported export formats
        """
        extension_list = []

        for type_element in self.get_extensions():
            type_element_class = load_class(f'cmdb.framework.exporter.format.{type_element}')

            extension_list.append({
                'extension': type_element,
                'label': type_element_class.LABEL,
                'icon': type_element_class.ICON,
                'multiTypeSupport': type_element_class.MULTITYPE_SUPPORT,
                'helperText': type_element_class.DESCRIPTION,
                'active': type_element_class.ACTIVE
            })

        return extension_list
