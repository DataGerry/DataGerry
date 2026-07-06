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
Implementation of all API routes for DataGerry Assistant
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    CategoriesManager,
)
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import RootBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.framework_routes.special_helper import has_framework_data
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant

from cmdb.errors.manager.categories_manager import CategoriesManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

special_blueprint = RootBlueprint('special_rest', __name__, url_prefix='/special')

# -------------------------------------------------------------------------------------------------------------------- #

@special_blueprint.route('/intro', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def show_datagerry_assistant(request_user: CmdbUser) -> Response:
    """
    Checks if the DataGerry assistant should be displayed when starting DataGerry

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: True if there are no types, categories and objects in the database else False
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        show_assistant: bool = not has_framework_data(categories_manager, types_manager, objects_manager)

        return DefaultResponse(show_assistant).make_response()
    except (CategoriesManagerGetError, TypesManagerGetError, ObjectsManagerGetError) as err:
        LOGGER.error("[show_datagerry_assistant] Error: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Failed to check prerequisites to display DataGerry Assistant!")
    except Exception as err:
        LOGGER.error("[show_datagerry_assistant] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while checking Assistant status!")


@special_blueprint.route('/profiles', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@special_blueprint.parse_assistant_parameters()
@insert_request_user
def create_initial_profiles(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates all profiles selected in the assistant

    Args:
        data (dict[str, Any]): Parsed query parameters; the 'data' key holds the profile names as a
                               single '#'-separated string
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: DefaultResponse wrapping the list of created CmdbType public_ids
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES,
                                                                                         request_user)

        profile_data = data.get('data')

        if not profile_data:
            abort(400, "No profiles were provided!")

        profiles: list[str] = profile_data.split('#')

        # Only execute if there are no categories, types and objects in the database
        if has_framework_data(categories_manager, types_manager, objects_manager):
            abort(400, "There are objects, types, or categories in the database which prevents this action!")

        profile_assistant = ProfileAssistant(categories_manager, types_manager, section_templates_manager)
        created_ids = profile_assistant.create_profiles(profiles)

        return DefaultResponse(created_ids).make_response()
    except HTTPException as http_err:
        raise http_err
    except ProfileCreationError as err:
        LOGGER.error("[create_initial_profiles] Error: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Failed to create initial Profiles!")
    except (CategoriesManagerGetError, TypesManagerGetError, ObjectsManagerGetError) as err:
        LOGGER.error("[create_initial_profiles] Error: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Failed to check prerequisites if the DataGerry Assistant can be executed!")
    except Exception as err:
        LOGGER.error("[create_initial_profiles] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating initial Profiles!")
