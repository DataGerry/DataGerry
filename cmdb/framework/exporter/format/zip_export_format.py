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
Implementation of ZipExportFormat
"""
from logging import Logger, getLogger
from itertools import groupby
import io
import zipfile

from cmdb.utils.helpers import load_class
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_ID_KEY,
    TYPE_INFO_NAME_KEY,
)
from cmdb.framework.exporter.exporter_constants import EXPORT_FORMAT_MODULE_PREFIX, ExporterOptionKey
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ZipExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ZipExportFormat(BaseExporterFormat):
    """
    The ZIP export format class

    Packs an underlying format (`classname`): the objects are grouped by type and each type is exported
    with the inner format into its own file inside the archive.

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "zip"
    MIME_TYPE = "application/zip"
    LABEL = "ZIP"
    MULTITYPE_SUPPORT = True
    ICON = "file-archive"
    DESCRIPTION = "Export Zipped Files"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> io.BytesIO:
        """
        Exports the objects as a ZIP archive with one inner file per type

        The inner export format is chosen by the `classname` option; the objects are grouped by type id
        and each group is serialized by the inner format into its own archive entry
        (`<type_name>_ID_<type_id>.<inner_extension>`). An empty object list yields a valid empty archive.
        The inner format is exported in its default (NATIVE) view - `view` / `metadata` are not forwarded.

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Optional export parameters dict; `classname` selects the inner format

        Returns:
            io.BytesIO: An in-memory ZIP archive positioned at the start
        """
        options = args[0] if args else {}
        inner_format = self._load_inner_format(options)

        zipped_file = io.BytesIO()

        with zipfile.ZipFile(zipped_file, "a", zipfile.ZIP_DEFLATED, False) as archive:
            for type_id, group in self._group_by_type(data):
                objects = list(group)
                entry_name = self._zip_entry_name(
                    objects[0].type_information[TYPE_INFO_NAME_KEY], type_id, inner_format.FILE_EXTENSION
                )
                content = inner_format.export(objects)
                archive.writestr(entry_name, self._to_bytes_or_str(content))

        zipped_file.seek(0)

        return zipped_file


    def _load_inner_format(self, options: dict) -> BaseExporterFormat:
        """
        Loads and instantiates the inner export format named by the `classname` option

        The `classname` is validated against the supported-formats whitelist by the export route before
        this format runs (`exporter_helper.resolve_export_format`), so the dynamic load is safe here.

        Args:
            options (dict): The export options dict carrying the `classname` of the inner format

        Returns:
            BaseExporterFormat: The instantiated inner export format
        """
        classname = options.get(ExporterOptionKey.CLASSNAME.value, "")

        return load_class(f'{EXPORT_FORMAT_MODULE_PREFIX}{classname}')()


    @staticmethod
    def _group_by_type(data: list[RenderResult]):
        """
        Groups the objects by their type id (sorted by type id, without mutating the input)

        Args:
            data (list[RenderResult]): The objects to be exported

        Returns:
            An iterator of `(type_id, objects_iterator)` pairs, one per type
        """
        ordered = sorted(data, key=lambda obj: obj.type_information[TYPE_INFO_ID_KEY])

        return groupby(ordered, key=lambda obj: obj.type_information[TYPE_INFO_ID_KEY])


    @staticmethod
    def _zip_entry_name(type_name: str, type_id: int, file_extension: str) -> str:
        """
        Builds the archive entry file name for one type's export

        Args:
            type_name (str): The type's name
            type_id (int): The type's public id
            file_extension (str): The inner format's file extension

        Returns:
            str: The archive entry name, e.g. `router_ID_5.json`
        """
        return f'{type_name}_ID_{type_id}.{file_extension}'


    @staticmethod
    def _to_bytes_or_str(content) -> str | bytes:
        """
        Normalizes an inner format's export output into something writable into the archive

        Inner formats return either a `str`/`bytes` payload or a file-like object (e.g. a `StringIO`);
        the latter is read out via `getvalue()`.

        Args:
            content: The inner format's export output

        Returns:
            str | bytes: The archive-writable payload
        """
        if isinstance(content, (str, bytes)):
            return content

        return content.getvalue()
