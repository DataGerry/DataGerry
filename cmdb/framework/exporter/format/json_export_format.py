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
Implementation of JsonExportFormat
"""
from logging import Logger, getLogger
import json

from cmdb.database.database_utils import default
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_LABEL_KEY,
    OBJECT_INFO_ID_KEY,
)
from cmdb.framework.exporter.exporter_constants import ExporterMetadataKey
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Default identity columns emitted for each object (public_id + active flag + the type's label)
DEFAULT_HEADER: list[str] = [CmdbObjectKey.PUBLIC_ID.value, CmdbObjectKey.ACTIVE.value, TYPE_INFO_LABEL_KEY]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               JsonExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonExportFormat(BaseExporterFormat):
    """
    The JSON export format for exporting data as a .json file

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "json"
    MIME_TYPE = "application/json"
    LABEL = "JSON"
    MULTITYPE_SUPPORT = True
    ICON = "file-code"
    DESCRIPTION = "Export as JSON"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> str:
        """
        Exports a list of RenderResult objects as a JSON-formatted string

        In the RENDER view a supplied `metadata` override selects the header and columns; otherwise the
        default header and every field are emitted. An empty object list yields `[]`.

        Args:
            data (list[RenderResult]): The objects to export
            *args: Optional export parameters dict (`view`, `metadata`)

        Returns:
            str: A JSON string of the exported objects (identity header, fields and MDS)
        """
        view, metadata = BaseExporterFormat.resolve_export_view(args)

        header = list(DEFAULT_HEADER)
        selected_columns = None

        if metadata:
            header = metadata.get(ExporterMetadataKey.HEADER.value, header)
            selected_columns = metadata.get(ExporterMetadataKey.COLUMNS.value, [])

        output = []

        for obj in data:
            columns = obj.fields

            # A metadata override restricts the exported fields to the selected column names
            if selected_columns is not None:
                columns = [field for field in columns if field[FieldKey.NAME.value] in selected_columns]

            output_element = self._create_output_element(obj, header)
            output_element[CmdbObjectKey.FIELDS.value] = self._get_fields(obj, columns, view)

            multi_data_sections = obj.multi_data_sections if obj.multi_data_sections else []
            if multi_data_sections:
                key = CmdbObjectKey.MULTI_DATA_SECTIONS.value
                output_element[key] = BaseExporterFormat.serialize_multi_data_sections(multi_data_sections)

            output.append(output_element)

        return json.dumps(output, default=default, ensure_ascii=False, indent=2)


    def _create_output_element(self, obj: RenderResult, header: list[str]) -> dict:
        """
        Creates the identity part of an output element from the header

        Args:
            obj (RenderResult): The object being exported
            header (list[str]): The identity column names to include

        Returns:
            dict: The identity fields keyed by header name (`public_id` -> object_id, `type_label` from
                  the type information, everything else from the object information)
        """
        output_element = {}

        for head in header:
            if head == CmdbObjectKey.PUBLIC_ID.value:
                output_element[head] = obj.object_information.get(OBJECT_INFO_ID_KEY)
            elif head == TYPE_INFO_LABEL_KEY:
                output_element[head] = obj.type_information.get(head)
            else:
                output_element[head] = obj.object_information.get(head)

        return output_element


    def _get_fields(self, obj: RenderResult, columns: list[dict], view: str) -> list[dict]:
        """
        Serializes the object's fields for the given view

        Args:
            obj (RenderResult): The object being exported
            columns (list[dict]): The field definitions to serialize
            view (str): The export view passed to the field summary renderer

        Returns:
            list[dict]: One `{name, value}` dict per field
        """
        fields = []

        for field in columns:
            fields.append({
                FieldKey.NAME.value: field.get(FieldKey.NAME.value),
                FieldKey.VALUE.value: BaseExporterFormat.summary_renderer(obj, field, view)
            })

        return fields
