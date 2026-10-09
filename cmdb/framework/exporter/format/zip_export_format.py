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
from collections.abc import Iterator
from logging import Logger, getLogger
from itertools import groupby
from typing import Any
import io
import zipfile

from cmdb.utils import load_class
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_ID_KEY,
    TYPE_INFO_NAME_KEY,
)
from cmdb.framework.exporter.exporter_constants import (
    EXPORT_FORMAT_MODULE_PREFIX,
    ZIP_ENTRY_FALLBACK_NAME,
    ExporterOptionKey,
)
from cmdb.framework.exporter.export_filename_helper import sanitize_filename_part
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
    with the inner format into its own file inside the archive. The inner format is handed the request's
    options, so each packed file reads exactly like a direct export of that type in that format - view,
    column selection and human-readable flag included.

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "zip"
    MIME_TYPE = "application/zip"
    LABEL = "ZIP"
    MULTITYPE_SUPPORT = True
    ICON = "file-archive"
    DESCRIPTION = "Export Zipped Files"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args: Any) -> io.BytesIO:
        """
        Exports the objects as a ZIP archive with one inner file per type

        The inner export format is chosen by the `classname` option; the objects are grouped by type id
        and each group is serialized by the inner format, with the same options, into its own archive entry
        (`<type_name>_ID_<type_id>.<inner_extension>`, the name sanitized like the archive's own). An empty
        object list yields a valid empty archive.

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Optional export parameters dict; `classname` selects the inner format, the rest (`view`,
                `metadata`, `human_readable`, the writer's location names) is handed on to it

        Returns:
            io.BytesIO: An in-memory ZIP archive positioned at the start
        """
        options = args[0] if args else {}
        inner_format = self._load_inner_format(options)

        zipped_file = io.BytesIO()

        with zipfile.ZipFile(zipped_file, "a", zipfile.ZIP_DEFLATED) as archive:
            for type_id, group in self._group_by_type(data):
                objects = list(group)
                entry_name = self._zip_entry_name(
                    objects[0].type_information[TYPE_INFO_NAME_KEY], type_id, inner_format.FILE_EXTENSION
                )
                content = inner_format.export(objects, options)
                archive.writestr(entry_name, self._to_bytes_or_str(content))

        zipped_file.seek(0)

        return zipped_file


    def honours_human_readable(self, options: dict[str, Any] | None) -> bool:
        """
        Reports whether this export is a human-readable one - which the packed format decides

        Args:
            options (dict[str, Any] | None): The export options dict carrying the `classname` of the inner format

        Returns:
            bool: True when the `human_readable` option is truthy and the inner format honours it
        """
        return self._load_inner_format(options or {}).honours_human_readable(options)


    def _load_inner_format(self, options: dict[str, Any]) -> BaseExporterFormat:
        """
        Loads and instantiates the inner export format named by the `classname` option

        The `classname` is validated against the supported-formats whitelist by the export route before
        this format runs (`exporter_helper.resolve_export_format`), so the dynamic load is safe here.

        Args:
            options (dict[str, Any]): The export options dict carrying the `classname` of the inner format

        Returns:
            BaseExporterFormat: The instantiated inner export format
        """
        classname = options.get(ExporterOptionKey.CLASSNAME.value, "")

        return load_class(f'{EXPORT_FORMAT_MODULE_PREFIX}{classname}')()


    @staticmethod
    def _group_by_type(data: list[RenderResult]) -> Iterator[tuple[int, Iterator[RenderResult]]]:
        """
        Groups the objects by their type id (sorted by type id, without mutating the input)

        Args:
            data (list[RenderResult]): The objects to be exported

        Returns:
            Iterator[tuple[int, Iterator[RenderResult]]]: An iterator of `(type_id, objects_iterator)` pairs,
            one per type
        """
        ordered = sorted(data, key=lambda obj: obj.type_information[TYPE_INFO_ID_KEY])

        return groupby(ordered, key=lambda obj: obj.type_information[TYPE_INFO_ID_KEY])


    @staticmethod
    def _zip_entry_name(type_name: str, type_id: int, file_extension: str) -> str:
        """
        Builds the archive entry file name for one type's export

        The type name is reduced the way the archive's own filename is (`sanitize_filename_part`), so a
        stored name can never carry a path separator or `..` into the archive; a name with nothing usable
        left becomes `ZIP_ENTRY_FALLBACK_NAME`. The type id keeps two entries apart either way

        Args:
            type_name (str): The type's name
            type_id (int): The type's public id
            file_extension (str): The inner format's file extension

        Returns:
            str: The archive entry name, e.g. `router_ID_5.json`
        """
        name = sanitize_filename_part(type_name) or ZIP_ENTRY_FALLBACK_NAME

        return f'{name}_ID_{type_id}.{file_extension}'


    @staticmethod
    def _to_bytes_or_str(content: str | bytes | io.StringIO | io.BytesIO) -> str | bytes:
        """
        Normalizes an inner format's export output into something writable into the archive

        Inner formats return either a `str`/`bytes` payload or a file-like object (e.g. a `StringIO`);
        the latter is read out via `getvalue()`.

        Args:
            content (str | bytes | io.StringIO | io.BytesIO): The inner format's export output

        Returns:
            str | bytes: The archive-writable payload
        """
        if isinstance(content, (str, bytes)):
            return content

        return content.getvalue()
