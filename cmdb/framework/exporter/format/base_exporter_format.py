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
Implementation of the BaseExporterFormat
"""
import json
from typing import Any

from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterOptionKey
# -------------------------------------------------------------------------------------------------------------------- #

# RenderResult keys read while exporting (these live on the render result / type information / object
# information, not on the field definition, so they are not covered by FieldKey / CmdbObjectKey)
REFERENCE_KEY: str = 'reference'
REFERENCE_SUMMARIES_KEY: str = 'summaries'
TYPE_INFO_LABEL_KEY: str = 'type_label'
TYPE_INFO_NAME_KEY: str = 'type_name'
TYPE_INFO_ID_KEY: str = 'type_id'
OBJECT_INFO_ID_KEY: str = 'object_id'


class BaseExporterFormat:
    """
    Base class for exporter formats

    Subclasses set the metadata class attributes below and implement `export`. Objects are always
    instantiated without arguments (`SomeFormat()`), so there is no `__init__` to override.

    Attributes:
        FILE_EXTENSION (str): The file extension for the export format
        MIME_TYPE (str): The HTTP Content-Type used when streaming the export (set by every subclass)
        LABEL (str): Label for the exporter format
        MULTITYPE_SUPPORT (bool): Indicates if multiple types are supported
        ICON (str): Icon representation of the format
        DESCRIPTION (str): Description of the exporter format
        ACTIVE (bool): Status indicating if the format is active
    """
    FILE_EXTENSION = None
    MIME_TYPE = None
    LABEL = None
    MULTITYPE_SUPPORT = False
    ICON = None
    DESCRIPTION = None
    ACTIVE = None


    @staticmethod
    def resolve_export_view(args: tuple) -> tuple[str, dict | None]:
        """
        Determines the requested export view and any render-view column metadata from the export args

        Returns the requested `view` (defaulting to the NATIVE view) and, only when the view is RENDER
        and the caller supplied `metadata`, the parsed metadata override dict (otherwise None). Column /
        header overrides therefore require the render view; how a format treats a render view given
        without metadata is left to the individual format.

        Args:
            args (tuple): The positional export args; `args[0]` (if present) is the options dict

        Returns:
            tuple[str, dict | None]: (requested view, parsed metadata override or None)
        """
        options = args[0] if args else {}
        view = options.get(ExporterOptionKey.VIEW.value, ExporterConfigType.NATIVE.value)
        raw_metadata = options.get(ExporterOptionKey.METADATA.value)

        if raw_metadata and view.upper() == ExporterConfigType.RENDER.value:
            return view, json.loads(raw_metadata)

        return view, None


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
    def summary_renderer(obj, field: dict, view: str = 'native') -> Any:
        """
        Resolves the exported value of a single field for the given view

        In the NATIVE view (the default) the field's raw stored value is returned. In the RENDER view a
        reference field is rendered to a human-readable summary line
        (`<type_label> #<type_id> | <summary values…>`); all other fields still return their raw value.

        Args:
            obj: The rendered object providing `type_information` (used for reference fields)
            field (dict): The field to resolve
            view (str): The view type, `'native'` or `'render'`. Defaults to `'native'`

        Returns:
            Any: The rendered reference summary string, or the field's raw value (which may be None)
        """
        if not isinstance(field, dict):
            return ""

        # In the RENDER view a reference field is shown as its resolved summary line
        is_render_view = view.upper() == ExporterConfigType.RENDER.value

        if is_render_view and field.get(FieldKey.TYPE.value) == FieldType.REFERENCE.value:
            type_info = obj.type_information
            summary_line = f'{type_info[TYPE_INFO_LABEL_KEY]} #{type_info[TYPE_INFO_ID_KEY]}'

            reference = field.get(REFERENCE_KEY)
            summaries = reference.get(REFERENCE_SUMMARIES_KEY, []) if reference else []

            summary_values = [line[FieldKey.VALUE.value] for line in summaries]

            if summary_values:
                summary_line += f' | {" | ".join(summary_values)}'

            return summary_line

        return field.get(FieldKey.VALUE.value, None)
