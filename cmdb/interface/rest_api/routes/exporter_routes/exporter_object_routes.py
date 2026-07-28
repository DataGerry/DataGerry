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
Implementation of all API routes for CmdbObject exports

Exposes two endpoints under the `/exporter` blueprint: `GET /exporter/extensions` (the catalogue of
supported export formats) and `GET /exporter/` (the actual object export). The export format is resolved
and validated by `exporter_helper.resolve_export_format`, then dynamically loaded and driven by
`BaseExportWriter`, which streams the result back as a file download.
"""
from logging import Logger, getLogger
from flask import abort, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.framework.exporter.config.exporter_config import ExporterConfig
from cmdb.framework.exporter.writer.base_export_writer import BaseExportWriter
from cmdb.framework.exporter.writer.supported_exporter_extension import SupportedExporterExtension
from cmdb.framework.exporter.exporter_constants import EXPORT_FORMAT_MODULE_PREFIX
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.exporter_routes.exporter_helper import resolve_export_format
from cmdb.utils.helpers import load_class
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.exporter import ExporterError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

exporter_blueprint = APIBlueprint('exporter', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@exporter_blueprint.route('/extensions', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@exporter_blueprint.protect(auth=True, right='base.export.object.*')
def get_export_file_types(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    Endpoint to retrieve the supported export file types/extensions.

    This route returns a list of the file types that the system can export.
    The file types are returned in a format that is suitable for use in the
    application, based on the implementation in the `SupportedExporterExtension` class.

    Returns:
        DefaultResponse: The response object containing the supported export file types
    """
    try:
        return DefaultResponse(SupportedExporterExtension().convert_to()).make_response()
    except Exception as err:
        LOGGER.error("[get_export_file_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving export file types!")


@exporter_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@exporter_blueprint.protect(auth=True, right='base.export.object.*')
@exporter_blueprint.parse_collection_parameters(view='native')
def export_objects(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Export objects based on the provided parameters and the requesting user's permissions.

    This function handles the export of data objects in different formats (e.g., JSON, ZIP) based on the
    provided parameters. It first determines the export format class, loads it dynamically, and then processes
    the export according to the user's permissions and the current cloud mode setting. 

    Args:
        params (CollectionParameters): Parameters defining the export options and format
        request_user (CmdbUser): The user requesting the export, used for permission checks and database context

    Returns:
        Response: The export data in the chosen format (e.g., a JSON or ZIP file)

    Raises:
        400 Bad Request: If the requested export format is not supported, if the objects cannot be
            retrieved, or if the export cannot be produced as asked for - a CSV of a selection
            spanning several types, an unusable `metadata` override, or a Type whose field names
            would collide in a tabular column (every ExporterError)
        403 Forbidden: If the user is not permitted to read the objects being exported
        500 Internal Server Error: If the resolved export format module cannot be imported, or on any
            other unexpected error
    """
    # Resolves + validates the format (aborts 400 on an unsupported one) before any DB work
    export_format = resolve_export_format(params.optional)

    try:
        _config = ExporterConfig(parameters=params, options=params.optional)
        exporter_class = load_class(f'{EXPORT_FORMAT_MODULE_PREFIX}{export_format}')()

        db_name = None
        if current_app.cloud_mode:
            db_name = request_user.database

        exporter = BaseExportWriter(exporter_class, _config)

        exporter.from_database(current_app.database_manager, request_user, AccessControlPermission.READ, db_name)

        return exporter.export()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[export_objects] AccessDeniedError: %s", err)
        abort(403, "No permission to export the Objects!")
    except ObjectsManagerIterationError as err:
        LOGGER.error("[export_objects] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Objects to export!")
    except ExporterError as err:
        # The export cannot be produced as asked for (mixed types in a CSV, an unusable metadata
        # override, colliding column names) - the request is at fault, not the server
        LOGGER.error("[export_objects] ExporterError: %s", err)
        abort(400, str(err))
    except ModuleNotFoundError as err:
        LOGGER.error("[export_objects] ModuleNotFoundError: %s", err, exc_info=True)
        abort(500, f"Module not found for export format: {export_format}!")
    except Exception as err:
        LOGGER.error("[export_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Objects!")
