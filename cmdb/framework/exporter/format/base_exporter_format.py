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
Implementation of the BaseExporterFormat
"""
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
# -------------------------------------------------------------------------------------------------------------------- #

class BaseExporterFormat:
    """
    Base class for exporter formats

    Attributes:
        FILE_EXTENSION (str): The file extension for the export format
        LABEL (str): Label for the exporter format
        MULTITYPE_SUPPORT (bool): Indicates if multiple types are supported
        ICON (str): Icon representation of the format
        DESCRIPTION (str): Description of the exporter format
        ACTIVE (bool): Status indicating if the format is active
    """
    FILE_EXTENSION = None
    LABEL = None
    MULTITYPE_SUPPORT = False
    ICON = None
    DESCRIPTION = None
    ACTIVE = None


    def __init__(self, file_name: str = ''):
        """
        Initializes the exporter with a filename
        
        Args:
            file_name (str): The base name of the file without extension
        """
        self.file_name = f'{file_name}.{self.FILE_EXTENSION}'


    def export(self, data, *args):
        """
        Exports the given data
        
        This method must be implemented by subclasses
        
        Args:
            data: The data to export
            *args: Additional arguments for export customization
        
        Raises:
            NotImplementedError: If the method is not implemented by a subclass
        """
        raise NotImplementedError("The 'export' method must be implemented in a subclass.")


    @staticmethod
    def summary_renderer(obj, field: dict, view: str = 'native') -> str:
        """
        Renders a summary of an CmdbObject based on the given field and view type
        
        Args:
            obj: The object containing type information.
            field (dict): A dictionary representing the field to summarize
            view (str): The rendering view type. Defaults to 'native'
        
        Returns:
            str: A formatted summary string
        """
        if not isinstance(field, dict):
            return ""

        # Export only the shown fields chosen by the user
        if view.upper() == ExporterConfigType.RENDER.name and field.get('type') == 'ref':
            type_info = obj.type_information
            summary_line = f'{type_info["type_label"]} #{type_info["type_id"]}'

            reference = field.get('reference')
            summaries = reference.get('summaries', []) if reference else []

            summary_values = [line["value"] for line in summaries]

            if summary_values:
                summary_line += f' | {" | ".join(summary_values)}'

            return summary_line

        return field.get('value', None)
