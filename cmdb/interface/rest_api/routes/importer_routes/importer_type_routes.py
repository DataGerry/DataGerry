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

The blueprint is mounted by init_rest_api at `/import/type`, so this module is self-contained: it can
be imported without an application context and without a parent import blueprint

Both routes take the same multipart upload (a JSON list of exported CmdbTypes) and follow the same
partial-report contract: every entry is processed independently and the response body is a mapping of
the failed entries to their error message, so a single bad entry never discards the rest of the batch.
An empty mapping therefore means the whole upload was applied. The per-entry work lives in
importer_type_helper
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    parse_uploaded_types,
    resolve_error_key,
    create_type_from_entry,
    update_type_from_entry,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import feature_locked
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

importer_type_blueprint = APIBlueprint('importer_type', __name__)

LOGGER: Logger = getLogger(__name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@importer_type_blueprint.route('/create/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_type_blueprint.protect(auth=True, right='base.import.type.*')
def add_type(request_user: CmdbUser) -> Response:
    """
    Adds new CmdbTypes based on uploaded JSON data

    A fresh public_id and creation timestamp are assigned to each imported type, so any public_id in
    the upload is ignored, and the requesting user becomes the author. Entries that cannot be
    imported are collected instead of aborting the request; the remaining entries are still inserted

    Args:
        request_user (CmdbUser): The user making the request, used for permission validation

    Raises:
        HTTPException: 400 if no upload file was provided, 500 on an unexpected error

    Returns:
        Response: A Flask Response object containing the error collection dictionary. The dictionary
                  maps each failed type (by its assigned public_id, else by its position in the
                  upload) to an error message. An empty dictionary means every type was imported
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        new_type_list = parse_uploaded_types(request)
        error_collection: dict[str, Any] = {}
        # The licence state is per request, not per entry - resolve it once for the whole batch
        ipam_locked: bool = feature_locked(LicenseFeature.IPAM, request_user)

        for index, new_type_data in enumerate(new_type_list):
            import_error = create_type_from_entry(new_type_data, types_manager, request_user.public_id, ipam_locked)

            if import_error:
                error_collection[resolve_error_key(new_type_data, index)] = import_error

        return DefaultResponse(error_collection).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[add_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating Types from imported data!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@importer_type_blueprint.route('/update/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_type_blueprint.protect(auth=True, right='base.import.type.*')
def update_type(request_user: CmdbUser) -> Response:
    """
    Updates existing CmdbTypes based on uploaded JSON data

    Updates are applied by public_id. Each type must already exist, otherwise an error is recorded for
    it. The requesting user is recorded as the editor of every type it replaces, while the stored
    author and creation time are left untouched. Entries that cannot be updated are collected instead
    of aborting the request; the remaining entries are still updated

    Args:
        request_user (CmdbUser): The user making the request, used for permission and context

    Raises:
        HTTPException: 400 if no upload file was provided, 500 on an unexpected error

    Returns:
        Response: A Flask Response object containing the error collection dictionary. The dictionary
                  maps each failed type (by its public_id, else by its position in the upload) to an
                  error message. An empty dictionary means every type was updated
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        update_type_list = parse_uploaded_types(request)
        error_collection: dict[str, Any] = {}
        # The licence state is per request, not per entry - resolve it once for the whole batch
        ipam_locked: bool = feature_locked(LicenseFeature.IPAM, request_user)

        for index, update_type_data in enumerate(update_type_list):
            update_error = update_type_from_entry(update_type_data, types_manager, request_user.public_id, ipam_locked)

            if update_error:
                error_collection[resolve_error_key(update_type_data, index)] = update_error

        return DefaultResponse(error_collection).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating Types from imported data!")
