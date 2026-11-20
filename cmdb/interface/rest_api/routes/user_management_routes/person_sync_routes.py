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
The routes of the user -> person sync: its settings, the user group mappings, a resync, and a user's person

Every ``/person_sync`` route checks ``base.user-management.sync.edit`` - one right for both syncs and the mappings.
The reads answer at the ADMIN level, the writes at SUPER_ADMIN (the tenant's setup). ``GET /users/<user_id>/person``
belongs to the users: ``base.user-management.user.view``, a user reaching its own; the person's Type ACL decides
whether its id is answered. What each write does is ``person_sync_routes_helper``'s
"""
from typing import Any

from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.person_sync_constants import GroupMappingKey, PersonSyncKey
from cmdb.framework.person_sync.sync_engine import SyncResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse, UpdateSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import UserAccessRight
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_route_constants import (
    GROUP_MAPPING_SCHEMA,
    GROUP_SYNC_SCHEMA,
    PERSON_SYNC_EDIT_RIGHT,
    USER_SYNC_SCHEMA,
    PersonSyncAnswerKey,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_relocation_helper import (
    relocation_counts,
    relocations_view,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_routes_helper import (
    check_user_sync,
    group_sync_view,
    left_members_view,
    map_group,
    pass_counts,
    read_mappings,
    read_settings,
    resync,
    store_group_sync,
    store_user_sync,
    unmap_group,
    user_person_link,
    user_sync_view,
)
# -------------------------------------------------------------------------------------------------------------------- #

person_sync_blueprint = APIBlueprint('person_sync', __name__)
user_person_blueprint = APIBlueprint('user_person', __name__)

# ---------------------------------------------------- USER SYNC ----------------------------------------------------- #

@person_sync_blueprint.route('/users', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@handle_route_errors("while retrieving the user sync settings")
def get_user_sync(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the user sync's settings

    Args:
        request_user (CmdbUser): The caller

    Returns:
        GetSingleResponse: ``active``, ``default_type_id`` and ``type_overrides`` - off and unchosen when never set
    """
    return GetSingleResponse(user_sync_view(read_settings(request_user)), body=request_wants_body()).make_response()


@person_sync_blueprint.route('/users', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@person_sync_blueprint.validate(USER_SYNC_SCHEMA)
@handle_route_errors("while storing the user sync settings")
def update_user_sync(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route for the user sync's settings, written whole

    A person whose Type changes moves first, keeping its id; one that cannot move (``POST /person_sync/users/check``)
    refuses the change - unless ``on_blocked`` is ``copy``: a deactivated copy stays, a new person is created, and the
    mapped person groups take the new one. Switched on (or changed while on), every user is then mirrored before the
    settings are stored; switched off, the user group sync goes off with it and every synced person is deactivated,
    kept linked and locked

    Args:
        data (dict[str, Any]): ``active``, ``default_type_id``, ``type_overrides``; ``on_blocked`` (``cancel`` or
            ``copy``, not stored)
        request_user (CmdbUser): The caller, credited with the sync's writes

    Raises:
        HTTPException: 400 naming every problem of the settings - a target Type missing, without PERSON, deactivated
            or requiring a field the sync cannot fill, an override for a missing user or a user overridden twice -
            the persons that cannot move (with ``cancel``), or a Type the pass cannot write into; 500 when the
            relocation failed (undone) or the pass failed midway (the settings stay as they were - storing them
            again finishes it)

    Returns:
        UpdateSingleResponse: The stored user sync settings, with ``created`` / ``edited`` counts of everything
            written and ``moved`` / ``copied`` counts of the relocation
    """
    settings, result, relocations = store_user_sync(request_user, data)

    return UpdateSingleResponse(user_sync_view(settings),
                                extra=pass_counts(result) | relocation_counts(relocations)).make_response()


@person_sync_blueprint.route('/users/check', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@person_sync_blueprint.validate(USER_SYNC_SCHEMA)
@handle_route_errors("while checking the user sync settings")
def check_user_sync_route(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route judging new user sync settings without storing them: every person whose Type would change, and
    what keeps each from moving

    A person moves keeping its id unless it holds a value the new Type cannot keep, is referenced in a field or a
    reference section that does not allow the new Type, sits on an object relation side that does not allow it, or is
    placed in the location tree - such a person is copied (``on_blocked: copy``) or the change is cancelled

    Args:
        data (dict[str, Any]): The settings ``PUT /person_sync/users`` would store
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 naming every problem of the settings

    Returns:
        GetSingleResponse: ``relocations`` (``{user_id, person_id, from_type_id, to_type_id, blockers}``) and the
            number ``blocked``
    """
    return GetSingleResponse(relocations_view(check_user_sync(request_user, data))).make_response()

# ---------------------------------------------------- GROUP SYNC ---------------------------------------------------- #

@person_sync_blueprint.route('/groups', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@handle_route_errors("while retrieving the user group sync settings")
def get_group_sync(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the user group sync's switch and every user group mapping

    Args:
        request_user (CmdbUser): The caller

    Returns:
        GetSingleResponse: ``active`` and ``mappings`` (``{user_group_id, person_group_id}`` in user group order)
    """
    view: dict[str, Any] = group_sync_view(read_settings(request_user), read_mappings(request_user))

    return GetSingleResponse(view, body=request_wants_body()).make_response()


@person_sync_blueprint.route('/groups', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@person_sync_blueprint.validate(GROUP_SYNC_SCHEMA)
@handle_route_errors("while storing the user group sync settings")
def update_group_sync(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route for the user group sync's switch

    Switched on, every mapped person group takes its user group's name and synced members; switched off, the mapped
    person groups are unlocked and kept as they are

    Args:
        data (dict[str, Any]): ``active``
        request_user (CmdbUser): The caller, credited with the sync's writes

    Raises:
        HTTPException: 400 when switched on without the user sync or without a Type carrying PERSON_GROUP, or for a
            Type the pass cannot write into; 500 when the pass failed midway

    Returns:
        UpdateSingleResponse: ``active`` and ``mappings``, with ``created`` and ``edited`` counts of the pass
    """
    settings, result = store_group_sync(request_user, data[PersonSyncKey.ACTIVE.value])
    view: dict[str, Any] = group_sync_view(settings, read_mappings(request_user))

    return UpdateSingleResponse(view, extra=pass_counts(result)).make_response()


@person_sync_blueprint.route('/groups/<int:user_group_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@person_sync_blueprint.validate(GROUP_MAPPING_SCHEMA)
@handle_route_errors("while mapping user group {user_group_id}")
def update_group_mapping(user_group_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route mapping a user group to an existing person group or to one created for it

    Args:
        user_group_id (int): The user group
        data (dict[str, Any]): ``person_group_id`` of an existing person group, or ``type_id`` of a Type carrying
            PERSON_GROUP to create one in - exactly one
        request_user (CmdbUser): The caller, credited with the writes

    Raises:
        HTTPException: 404 for a missing user group; 400 for a body with none or both keys, a user group mapped
            already, an object that is missing, no person group or mapped already, a Type missing, without
            PERSON_GROUP, deactivated or requiring a field the sync cannot fill; 403 when the caller may not READ and
            UPDATE the person group's Type, or CREATE in the chosen Type; 500 when the sync failed (nothing kept)

    Returns:
        UpdateSingleResponse: ``{user_group_id, person_group_id}``, and ``left``: the synced persons the group sync
            took out of the group because the user group does not hold them
    """
    person_group_id, result = map_group(request_user, user_group_id, data)

    return UpdateSingleResponse({GroupMappingKey.USER_GROUP_ID.value: user_group_id,
                                 GroupMappingKey.PERSON_GROUP_ID.value: person_group_id},
                                extra={PersonSyncAnswerKey.LEFT.value: left_members_view(result)}).make_response()


@person_sync_blueprint.route('/groups/<int:user_group_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@handle_route_errors("while unmapping user group {user_group_id}")
def delete_group_mapping(user_group_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route unmapping a user group - its person group stays, its name and members kept, unlocked

    Args:
        user_group_id (int): The user group
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when the user group is mapped to no person group

    Returns:
        UpdateSingleResponse: ``{user_group_id, person_group_id}`` of the mapping removed
    """
    person_group_id: int = unmap_group(request_user, user_group_id)

    return UpdateSingleResponse({GroupMappingKey.USER_GROUP_ID.value: user_group_id,
                                 GroupMappingKey.PERSON_GROUP_ID.value: person_group_id}).make_response()

# ------------------------------------------------------ RESYNC ------------------------------------------------------ #

@person_sync_blueprint.route('/resync', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@person_sync_blueprint.protect(auth=True, right=PERSON_SYNC_EDIT_RIGHT)
@handle_route_errors("while resyncing the users")
def post_resync(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route running the reconciliation pass on the stored settings

    Args:
        request_user (CmdbUser): The caller, credited with the sync's writes

    Raises:
        HTTPException: 400 while the user sync is off, or for a Type the pass cannot write into; 500 when the pass
            failed midway (running it again finishes it)

    Returns:
        UpdateSingleResponse: ``created`` and ``edited`` counts
    """
    result: SyncResult = resync(request_user)

    return UpdateSingleResponse(pass_counts(result)).make_response()

# -------------------------------------------------- USER -> PERSON -------------------------------------------------- #

@user_person_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@user_person_blueprint.protect(auth=True, right=UserAccessRight.VIEW.value, excepted={'public_id': 'user_id'})
@handle_route_errors("while retrieving the person of user {user_id}")
def get_user_person(user_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for a user's person - the object mirroring it

    Args:
        user_id (int): The user
        request_user (CmdbUser): The caller - the user itself needs no right

    Raises:
        HTTPException: 404 for a missing user; 403 when the person is in a Type the caller may not READ

    Returns:
        GetSingleResponse: ``user_id``, ``person_id`` and ``type_id`` - both None while the user has no person
    """
    return GetSingleResponse(user_person_link(request_user, user_id), body=request_wants_body()).make_response()
