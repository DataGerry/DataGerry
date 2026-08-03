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
Helper functions for the CmdbObject / CmdbType export REST routes

The file serves two unrelated export paths that happen to share a route folder. `resolve_export_format`
belongs to the OBJECT export: it validates the requested format class before it is dynamically loaded
and driven by the framework export engine. `build_types_json_export_response` belongs to the TYPE
export, which has no engine behind it - it serializes the types itself and returns the attachment
"""
import json
from typing import Any
from flask import abort, Response

from cmdb.database.database_utils import default
from cmdb.models.type_model import CmdbType
from cmdb.utils.helpers import is_truthy_query_arg
from cmdb.framework.exporter.export_filename_helper import build_type_export_filename
from cmdb.framework.exporter.writer.supported_exporter_extension import SupportedExporterExtension
from cmdb.interface.rest_api.routes.exporter_routes.exporter_constants import (
    ZIP_EXPORT_FORMAT,
    DEFAULT_EXPORT_FORMAT,
    ExporterQueryParam,
)
from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_constants import (
    TYPE_EXPORT_MIMETYPE,
    TYPE_EXPORT_FILE_EXTENSION,
    TYPE_EXPORT_JSON_INDENT,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Export format classes that may be packed inside a ZIP (the built-in formats, excluding ZIP itself)
ZIPPABLE_EXPORT_FORMATS: set[str] = set(SupportedExporterExtension().get_extensions())

# Export format classes that may be dynamically loaded from cmdb.framework.exporter.format - a query
# supplied 'classname' is validated against this set so an arbitrary class cannot be imported
SUPPORTED_EXPORT_FORMATS: set[str] = ZIPPABLE_EXPORT_FORMATS | {ZIP_EXPORT_FORMAT}


def resolve_export_format(optional: dict[str, Any]) -> str:
    """
    Determines and validates the export format class name from a request's optional parameters

    A truthy `zip` flag forces the ZIP wrapper; in that case the `classname` it will pack is validated
    against `ZIPPABLE_EXPORT_FORMATS` (so the ZIP's own dynamic `load_class` of the inner format cannot
    import an arbitrary class, and zip-in-zip is rejected). Otherwise the `classname` parameter is used,
    defaulting to `DEFAULT_EXPORT_FORMAT`, and validated against `SUPPORTED_EXPORT_FORMATS`. Both paths
    guard `load_class` against arbitrary input

    Args:
        optional (dict[str, Any]): The request's optional/query parameters (`params.optional`)

    Raises:
        HTTPException: 400 if the resolved (or, for zip, the inner) format is not supported

    Returns:
        str: The validated export format class name
    """
    if is_truthy_query_arg(optional.get(ExporterQueryParam.ZIP.value)):
        inner_format = optional.get(ExporterQueryParam.CLASSNAME.value)

        if inner_format not in ZIPPABLE_EXPORT_FORMATS:
            abort(400, f"Unsupported export format: {inner_format}!")

        return ZIP_EXPORT_FORMAT

    export_format = optional.get(ExporterQueryParam.CLASSNAME.value, DEFAULT_EXPORT_FORMAT)

    if export_format not in SUPPORTED_EXPORT_FORMATS:
        abort(400, f"Unsupported export format: {export_format}!")

    return export_format


def build_types_json_export_response(types: list[CmdbType]) -> Response:
    """
    Serializes CmdbTypes into a downloadable, timestamped JSON attachment response

    Shared by both type-export routes (all types / by ids) so the serialization + download headers live
    in one place. The body is indented so the export can be read and diffed, and BSON values that plain
    json cannot encode (ObjectId, datetime, ...) are converted by the shared `default` hook. An empty
    list serializes to `[]` - a valid empty export, not an error

    A type that cannot be serialized fails the whole export rather than being skipped: an unserializable
    type is a data-integrity problem, and silently dropping it would produce an export that looks
    complete but is not

    Args:
        types (list[CmdbType]): The types to export

    Raises:
        CmdbTypeToJsonError: If any of the types could not be converted to a json compatible dict. The
                             calling routes map this to an HTTP 500

    Returns:
        Response: A Flask response streaming the types as a `.json` file attachment
    """
    body: str = json.dumps(
        [CmdbType.to_json(type_) for type_ in types],
        default=default,
        indent=TYPE_EXPORT_JSON_INDENT,
    )
    # The number of exported types is what identifies a catalogue slice, so it names the file
    filename: str = build_type_export_filename(len(types), TYPE_EXPORT_FILE_EXTENSION)

    return Response(
        body,
        mimetype=TYPE_EXPORT_MIMETYPE,
        headers={
            # Quoted for the same reason as the object export: the name carries more than a timestamp now
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
