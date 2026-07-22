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
Implementation of all API routes for exporting CmdbTypes

Exposes `POST /export/type/` (all types) and `POST /export/type/<ids>` (a comma-separated selection).
Both serialize the types into a downloadable JSON attachment via
`exporter_helper.build_types_json_export_response`. NOTE: type export is JSON-only and lives on its own
blueprint, separate from the object export engine (tracked as discussion-backlog #65).
"""
from logging import Logger, getLogger
from flask import abort, Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.blueprints import RootBlueprint
from cmdb.interface.rest_api.routes.exporter_routes.exporter_helper import build_types_json_export_response

from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

type_export_blueprint = RootBlueprint('type_export_rest', __name__, url_prefix='/export/type')

# -------------------------------------------------------------------------------------------------------------------- #

@type_export_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_cmdb_types(request_user: CmdbUser) -> Response:
    """
    Export all CMDB types as a downloadable JSON file.

    This endpoint retrieves all available CMDB types from the system for the given user,
    serializes them into a formatted JSON file, and returns it as an HTTP response with
    appropriate headers for file download.

    Args:
        request_user (CmdbUser): The user initiating the export request

    Returns:
        Response: A Flask response object containing the exported types as a JSON attachment

    Raises:
        400 Bad Request: If the types cannot be retrieved
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        return build_types_json_export_response(types_manager.get_all_types())
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[export_cmdb_types] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Types to export!")
    except Exception as err:
        LOGGER.error("[export_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types!")


@type_export_blueprint.route('/<string:public_ids>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_cmdb_types_by_ids(public_ids: str, request_user: CmdbUser) -> Response:
    """
    Export specific CMDB types by their public IDs as a downloadable JSON file.

    This endpoint retrieves CMDB types based on a list of provided public IDs, 
    serializes them into a formatted JSON file, and returns it as an HTTP response 
    with appropriate headers for file download.

    Args:
        public_ids (str): A comma-separated string of CMDB type public IDs to export
        request_user (CmdbUser): The user initiating the export request

    Returns:
        Response: A Flask response object containing the exported types as a JSON attachment

    Raises:
        400 Bad Request: If the ids are not a comma-separated list of integers, or the types cannot be retrieved
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        query_list = []
        for raw_id in public_ids.split(","):
            try:
                query_list.append({'public_id': int(raw_id)})
            except (ValueError, TypeError) as err:
                LOGGER.error("[export_cmdb_types_by_ids] (ValueError, TypeError): %s", err, exc_info=True)
                abort(400, "IDs provided in an invalid format. They need to be a comma seperated string!")

        types = types_manager.get_types_by(sort="public_id", **{'$or': query_list})

        return build_types_json_export_response(types)
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[export_cmdb_types_by_ids] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Types to export!")
    except Exception as err:
        LOGGER.error("[export_cmdb_types_by_ids] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types by IDs!")
