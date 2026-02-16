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
Implementation of all API routes for Type Imports
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from bson import json_util
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.importer_routes.import_routes import importer_blueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import NestedBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.manager.types_manager import (
    TypesManagerInsertError,
)
# -------------------------------------------------------------------------------------------------------------------- #

importer_type_blueprint = NestedBlueprint(importer_blueprint, url_prefix='/type')

LOGGER: Logger = getLogger(__name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@importer_type_blueprint.route('/create/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def add_type(request_user: CmdbUser) -> Response:
    """
    Adds new CmdbTypes based on uploaded JSON data. Generates new public IDs and creation timestamps for 
    each imported type, and inserts them into the database

    Args:
        request_user (CmdbUser): The user making the request, used for permission validation.

    Returns:
        Response: A Flask Response object containing an error collection dictionary.
                  The dictionary maps any type public_id to an error message if the insertion failed.
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        error_collection: dict[str, Any] = {}
        upload = request.form.get('uploadFile')
        new_type_list = json.loads(upload, object_hook=json_util.object_hook)

        for new_type_data in new_type_list:
            try:
                new_type_data['public_id'] = types_manager.get_new_type_public_id()
                new_type_data['creation_time'] = datetime.now(timezone.utc)
            except Exception as err:
                LOGGER.error("[add_type] Exception: %s. Type: %s.", err, type(err), exc_info=True)
                abort(400)

            try:
                type_instance = CmdbType.from_data(new_type_data)
                types_manager.insert_type(type_instance)
            except (TypesManagerInsertError, Exception) as err:
                LOGGER.error("[add_type] Exception: %s. Type: %s.", err, type(err), exc_info=True)
                error_collection.update({"public_id": new_type_data['public_id'], "message": err})

        return DefaultResponse(error_collection).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[add_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating Types from imported data!")


@importer_type_blueprint.route('/update/', methods=['POST'])
@insert_request_user
def update_type(request_user: CmdbUser):
    """
    Updates existing CmdbTypes based on uploaded JSON data. Each type must already exist 
    otherwise, an error will be recorded. Updates are applied by public ID.

    Args:
        request_user (CmdbUser): The user making the request, used for permission and context

    Returns:
        Response: A Flask Response object containing an error collection dictionary.
                  The dictionary maps public_ids to error messages if the update failed.
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        error_collection = {}
        upload = request.form.get('uploadFile')
        data_dump = json.loads(upload, object_hook=json_util.object_hook)

        for add_data_dump in data_dump:
            try:
                update_type_instance = CmdbType.from_data(add_data_dump)
            except Exception as err:
                LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
                abort(400, "Failed to create a Type instance from the provided data!")
            try:
                types_manager.get_type(update_type_instance.public_id)
                types_manager.update_type(update_type_instance.public_id, update_type_instance)
            except Exception as err:
                LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
                error_collection.update({"public_id": add_data_dump['public_id'], "message": err})

        return DefaultResponse(error_collection).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating Types from imported data!")
