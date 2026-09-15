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
Unit tests for cmdb.interface.rest_api.routes.exporter_routes.exporter_type_constants

The type export declares its own JSON mimetype and file extension instead of importing them from
JsonExportFormat, so that it stays decoupled from the object export engine. That duplication is
deliberate, but it can drift - these tests pin the two copies to each other. If the object format ever
changes its mimetype or extension, this is the reminder to make the same call for the type export.
"""
from cmdb.framework.exporter.format.json_export_format import JsonExportFormat
from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_constants import (
    TYPE_EXPORT_MIMETYPE,
    TYPE_EXPORT_FILE_EXTENSION,
    TYPE_EXPORT_JSON_INDENT,
)
# -------------------------------------------------------------------------------------------------------------------- #


def test_mimetype_matches_the_json_export_format() -> None:
    """The type export's mimetype is the same one the object JSON format declares."""
    assert TYPE_EXPORT_MIMETYPE == JsonExportFormat.MIME_TYPE


def test_file_extension_matches_the_json_export_format() -> None:
    """The type export's file extension is the same one the object JSON format declares."""
    assert TYPE_EXPORT_FILE_EXTENSION == JsonExportFormat.FILE_EXTENSION


def test_json_indent_keeps_the_export_pretty_printed() -> None:
    """The indent stays a positive int - 0 or None would minify the export."""
    assert isinstance(TYPE_EXPORT_JSON_INDENT, int)
    assert TYPE_EXPORT_JSON_INDENT > 0
