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
"""
import json
import datetime
import time
from logging import Logger, getLogger
from flask import abort, Response
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

type_export_blueprint = RootBlueprint('type_export_rest', __name__, url_prefix='/export/type')

# -------------------------------------------------------------------------------------------------------------------- #

@type_export_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_cmdb_types(request_user: CmdbUser):
    """
    Export all CMDB types as a downloadable JSON file.

    This endpoint retrieves all available CMDB types from the system for the given user,
    serializes them into a formatted JSON file, and returns it as an HTTP response with
    appropriate headers for file download.

    Args:
        request_user (CmdbUser): The user initiating the export request

    Returns:
        Response: A Flask response object containing the exported types as a JSON attachment
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        type_list = [CmdbType.to_json(type) for type in types_manager.get_all_types()]
        resp = json.dumps(type_list, default=default, indent=2)
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d-%H_%M_%S')

        return Response(
            resp,
            mimetype="text/json",
            headers={
                "Content-Disposition": f"attachment; filename={timestamp}.json"
            }
        )
    except Exception as err:
        LOGGER.error("[export_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types!")


@type_export_blueprint.route('/<string:public_ids>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_cmdb_types_by_ids(public_ids, request_user: CmdbUser):
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
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        query_list = []
        for key, value in {'public_id': public_ids}.items():
            for v in value.split(","):
                try:
                    query_list.append({key: int(v)})
                except (ValueError, TypeError) as err:
                    LOGGER.error("[export_cmdb_types_by_ids] (ValueError, TypeError): %s", err, exc_info=True)
                    abort(400, "IDs provided in an invalid format. They need to be a comma seperated string!")

        type_list_data = json.dumps([CmdbType.to_json(type_) for type_ in
                                    types_manager.get_types_by(sort="public_id", **{'$or': query_list})],
                                    default=default, indent=2)

        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d-%H_%M_%S')

        return Response(
            type_list_data,
            mimetype="text/json",
            headers={
                "Content-Disposition": f"attachment; filename={timestamp}.json"
            }
        )
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[export_cmdb_types_by_ids] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types by IDs!")
