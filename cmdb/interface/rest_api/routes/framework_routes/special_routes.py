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
Implementation of the API routes of the DataGerry Assistant

The assistant seeds an **empty** installation with starter CmdbTypes and their CmdbCategories for the profiles a
user selects. Two routes:

    - ``GET /special/intro``: whether to offer it - true only when the caller holds the rights to run it
      (``base.framework.type.add`` and ``base.framework.category.add``), the database has no categories, types or
      objects, and the assistant has not run here before. It carries no right of its own: every user asks it after
      login, and a user who may not run the assistant is simply never offered it
    - ``POST /special/profiles``: run it, behind both rights. The selection is validated first, then the database
      must be empty and the run claims a one-time marker (``ASSISTANT_SETTINGS_SECTION``) so a second run - also a
      concurrent one - is refused. **The run is all or nothing**: every created type and category is recorded, and a
      failure part-way deletes them again and releases the marker, so the assistant can be run again. The created
      types name the caller as their author
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    CategoriesManager,
    SettingsManager,
)
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
    parse_assistant_parameters,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.framework_routes.special_constants import (
    ASSISTANT_ALREADY_RAN_MESSAGE,
    ASSISTANT_READ_FAILED_MESSAGE,
    ASSISTANT_RESIDUE_MESSAGE,
    ASSISTANT_RIGHTS,
    ASSISTANT_SETTINGS_SECTION,
    AssistantMarkerKey,
    FRAMEWORK_DATA_EXISTS_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.special_helper import (
    assistant_has_run,
    drop_locked_profiles,
    has_framework_data,
    holds_assistant_rights,
    read_profile_selection,
)
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant

from cmdb.errors.database import DocumentGetError
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.categories_manager import CategoriesManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

special_blueprint = APIBlueprint('special_rest', __name__, url_prefix='/special')

# A failed read of what decides whether the assistant may run - the same 400 on both routes
ASSISTANT_READ_FAILURES: dict[type[Exception], str] = {
    CategoriesManagerGetError: ASSISTANT_READ_FAILED_MESSAGE,
    TypesManagerGetError: ASSISTANT_READ_FAILED_MESSAGE,
    ObjectsManagerGetError: ASSISTANT_READ_FAILED_MESSAGE,
    BaseManagerGetError: ASSISTANT_READ_FAILED_MESSAGE,
    DocumentGetError: ASSISTANT_READ_FAILED_MESSAGE,
}

# -------------------------------------------------------------------------------------------------------------------- #

@special_blueprint.route('/intro', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while checking whether to offer the DataGerry Assistant")
@handle_manager_errors(ASSISTANT_READ_FAILURES)
def show_datagerry_assistant(request_user: CmdbUser) -> Response:
    """
    Checks whether the DataGerry Assistant should be offered to the caller

    No right of its own - every user asks it after login. It answers true only when the caller holds the rights
    to run the assistant, the assistant has not run on this installation, and the database has no categories, types
    or objects; a caller without the rights is not offered it and nothing is read

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when reading what decides it fails, 500 on an unexpected error

    Returns:
        DefaultResponse: True when the assistant should be offered, else False
    """
    if not holds_assistant_rights(request_user):
        return DefaultResponse(False).make_response()

    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    if assistant_has_run(settings_manager):
        return DefaultResponse(False).make_response()

    categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, request_user)
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    show_assistant: bool = not has_framework_data(categories_manager, types_manager, objects_manager)

    return DefaultResponse(show_assistant).make_response()


@special_blueprint.route('/profiles', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@special_blueprint.protect(auth=True, right=ASSISTANT_RIGHTS[0])
@special_blueprint.protect(auth=True, right=ASSISTANT_RIGHTS[1])
@parse_assistant_parameters()
@handle_route_errors("while creating initial Profiles")
@handle_manager_errors(ASSISTANT_READ_FAILURES)
def create_initial_profiles(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates all profiles selected in the assistant

    Asks for ``base.framework.type.add`` and ``base.framework.category.add`` - it creates both. The selection must
    name known profiles only, the database must hold no categories, types or objects, and the assistant must not
    have run here before: the run claims the marker section first, so of two concurrent runs one is refused.

    **All or nothing.** Every created type and category is recorded; when the run fails part-way they are deleted
    again, newest first, and the marker is released, so the assistant can be run once more. An undo that cannot
    finish answers a 500 naming what is left. A selected profile whose license feature is not unlocked is skipped,
    so the response lists only the types actually created; they name the caller as their author

    Args:
        data (dict[str, Any]): Parsed query parameters; the 'data' key holds the profile names as a
                               single '#'-separated string
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right; 400 for no or an unknown profile, a database that is not empty,
                       an assistant that has run already, or a failed read of any of that; 500 when the creation
                       fails (everything undone) or its undo cannot finish

    Returns:
        Response: DefaultResponse wrapping the list of created CmdbType public_ids
    """
    profiles: list[str] = read_profile_selection(data)

    categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, request_user)
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES,
                                                                                     request_user)
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    if has_framework_data(categories_manager, types_manager, objects_manager):
        abort(400, FRAMEWORK_DATA_EXISTS_MESSAGE)

    claimed: bool = settings_manager.claim_section(ASSISTANT_SETTINGS_SECTION, {
        AssistantMarkerKey.CLAIMED_BY: request_user.get_public_id(),
        AssistantMarkerKey.CLAIMED_AT: datetime.now(timezone.utc),
    })

    if not claimed:
        abort(400, ASSISTANT_ALREADY_RAN_MESSAGE)

    # A profile whose license feature is locked is skipped rather than failing the whole run - the
    # assistant bypasses the route guards that would otherwise gate it (see drop_locked_profiles)
    profiles = drop_locked_profiles(profiles, request_user)

    try:
        with undone_on_failure(ASSISTANT_RESIDUE_MESSAGE) as ledger:
            created_ids: list[int] = ProfileAssistant(
                categories_manager, types_manager, section_templates_manager,
                author_id=request_user.get_public_id(), ledger=ledger,
            ).create_profiles(profiles)
    except HTTPException:
        # Only the undo answers one: it could not finish, so the database is not empty and the marker stays
        raise
    except Exception:
        # Undone cleanly: the installation is empty again, so the assistant may be run again
        settings_manager.delete_section(ASSISTANT_SETTINGS_SECTION)
        raise

    return DefaultResponse(created_ids).make_response()
