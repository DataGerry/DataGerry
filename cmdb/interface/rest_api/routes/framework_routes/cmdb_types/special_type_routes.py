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
Implementation of all API routes for handling SpecialTypes
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

special_types_blueprint = APIBlueprint('special_types', __name__)

# --------------------------------------------------- CRUD - GET ----------------------------------------------------- #

@special_types_blueprint.route('/exist', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def check_special_type_exist(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to check if a SpecialType exists

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        bool: True if the SpecialType exists in db else False
    """
    try:
        special_type: str | None = request.args.get('special_type')

        if not special_type:
            abort(400, "No SpecialType provided to check if it exists!")

        if not SpecialType.is_valid(special_type):
            abort(400, f"The provided SpecialType: {special_type} is not valid!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        matching_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': special_type})

        return DefaultResponse(bool(matching_type)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[check_special_type_exist] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while checking if SpecialType exists!")


@special_types_blueprint.route('/', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_special_types(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve SpecialTypes

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        dict[str, Any]: True if the SpecialType exists in db else False
    """
    try:
        only_available: str | None = request.args.get('available', default="false").lower() == "true"

        special_types: dict[str, Any] = {}

        if only_available:
            types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

            existing: list[Any] = types_manager.get_distinct(
                "special_type",
                {"special_type": {"$exists": True}}
            )

            special_types = SpecialType.get_unused_types(existing)
        else:
            special_types = SpecialType.get_special_types()

        return DefaultResponse(special_types).make_response()
    except Exception as err:
        LOGGER.error("[check_special_type_exist] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while retrieving SpecialTypes!")


@special_types_blueprint.route('/schema', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_special_type_schema(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve SpecialTypes

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        dict[str, Any]: True if the SpecialType exists in db else False
    """
    try:
        special_type: str | None = request.args.get('special_type')

        if not special_type:
            abort(400, "No 'special_type' provided!")

        if not SpecialType.is_valid(special_type):
            abort(400, f"The provided SpecialType: {special_type} is not valid!")

        schema: dict[str, Any] = SchemaProvider().get_schema(special_type)

        return DefaultResponse(schema).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[check_special_type_exist] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while retrieving a SpecialType schema!")
