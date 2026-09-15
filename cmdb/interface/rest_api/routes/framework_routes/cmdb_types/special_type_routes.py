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
from cmdb.manager import ExtendableOptionsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.extendable_option_model import OptionType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_constants import (
    SPECIAL_TYPE_PARAM,
    AVAILABLE_PARAM,
)
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
        special_type: str | None = request.args.get(SPECIAL_TYPE_PARAM)

        if not special_type:
            abort(400, "No SpecialType provided to check if it exists!")

        if not SpecialType.is_valid(special_type):
            abort(400, f"The provided SpecialType: {special_type} is not valid!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        special_type_exists: bool = types_manager.check_special_type_exists(special_type)

        return DefaultResponse(special_type_exists).make_response()
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

    With ``?available=true`` only the SpecialTypes not yet assigned to any CmdbType are returned,
    otherwise the full set of SpecialTypes is returned

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        DefaultResponse: The SpecialTypes (all, or only the unused ones when ?available=true)
    """
    try:
        only_available: bool = request.args.get(AVAILABLE_PARAM, default="false").lower() == "true"

        special_types: dict[str, Any] = {}

        if only_available:
            types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

            existing: list[Any] = types_manager.get_distinct(
                TypeSchemaKey.SPECIAL_TYPE,
                {TypeSchemaKey.SPECIAL_TYPE: {"$exists": True}}
            )

            special_types = SpecialType.get_unused_types(existing)
        else:
            special_types = SpecialType.get_special_types()

        return DefaultResponse(special_types).make_response()
    except Exception as err:
        LOGGER.error("[get_special_types] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while retrieving SpecialTypes!")


def get_cable_type_values(request_user: CmdbUser) -> list[str]:
    """
    Reads every CABLE_TYPE option value the installation currently offers

    The CABLE blueprint's cable-type select carries inline options rather than pointing at the
    CmdbExtendableOption list, because a stored CmdbType field has no 'option_type' key to point with.
    Reading the values here - and not inside SchemaProvider - is what keeps that layer a pure function
    with no database behind it.

    Every existing value is read, not just the predefined ones, so a customer who already extended the
    list gets their own values in the type they create. An empty result is a legitimate answer: the
    Cable type is then created with an empty select rather than refused or back-filled

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        list[str]: The CABLE_TYPE option values, empty when the list holds nothing
    """
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
        ManagerType.EXTENDABLE_OPTIONS, request_user,
    )

    return extendable_options_manager.get_option_values(OptionType.CABLE_TYPE.value)


@special_types_blueprint.route('/schema', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_special_type_schema(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the field/section schema of a single SpecialType

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        DefaultResponse: The schema dict for the requested SpecialType
    """
    try:
        special_type: str | None = request.args.get(SPECIAL_TYPE_PARAM)

        if not special_type:
            abort(400, "No 'special_type' provided!")

        if not SpecialType.is_valid(special_type):
            abort(400, f"The provided SpecialType: {special_type} is not valid!")

        # Only the CABLE blueprint needs a value from the database; every other one is static
        cable_type_values: list[str] | None = (
            get_cable_type_values(request_user) if special_type == SpecialType.CABLE else None
        )

        schema: dict[str, Any] = SchemaProvider().get_schema(special_type, cable_type_values)

        return DefaultResponse(schema).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_special_type_schema] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while retrieving a SpecialType schema!")
