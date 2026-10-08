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
Implementation of all API routes for CmdbUserSettings

A setting is addressed by its **resource** under its user (`/users/<user_id>/settings/<resource>`) -
there is no public_id in any of these paths, because `(user_id, resource)` is the identity (see
`CmdbUserSetting`). Both write routes pin `user_id` (and PUT also `resource`) to the URL, so a
mismatched body cannot store a setting under another id.

**A user's settings are their own.** Every route asks for ``base.user-management.user.edit`` with the owner carve-out
(``protect(..., excepted={'public_id': 'user_id'})``): the user the path names reaches them without a right, anyone
else needs the right to edit users. The seeded ``user`` group does not hold it, so a default user reaches only their
own settings - which is all the frontend ever asks for.

**Every route answers one shape** - the four keys `resource`, `user_id`, `payloads`, `setting_type`
(`user_settings_helper.serialize_user_setting`). The `public_id` the shared insert path stamps on the stored
document is a storage artifact: no route answers it in a setting, and the create reports it only as the
envelope's `result_id`, the field every insert response carries.

**The unique `(resource, user_id)` index decides a race.** A create that loses it answers the same 400 as its
pre-check; an update-or-create that loses it - the setting appeared between its read and its insert - updates
the setting instead.
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response

from cmdb.manager import UserSettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    abort_if_too_large,
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    GetListResponse,
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetSingleResponse,
)
from cmdb.interface.rest_api.routes.routes_helper import abort_if_duplicate, request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_helper import serialize_user_setting
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_constants import (
    OWNER_EXCEPTION,
    USER_SETTINGS_RIGHT,
    UserSettingMessage,
)
from cmdb.utils import find_cause

from cmdb.errors.database import DocumentDuplicateKeyError
from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerInsertError,
    UserSettingsManagerGetError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
    UserSettingsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

user_settings_blueprint = APIBlueprint('user_settings', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@user_settings_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.protect(auth=True, right=USER_SETTINGS_RIGHT, excepted=OWNER_EXCEPTION)
@user_settings_blueprint.validate(build_write_schema(CmdbUserSetting.SCHEMA))
@handle_route_errors("while creating a UserSetting")
@handle_manager_errors({
    UserSettingsManagerGetError: UserSettingMessage.CHECK_FAILED,
    UserSettingsManagerInsertError: UserSettingMessage.INSERT_FAILED,
})
def insert_cmdb_user_setting(user_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbUserSetting into the database

    Args:
        user_id (int): public_id of the CmdbUser the setting belongs to
        data (CmdbUserSetting.SCHEMA): Data of the CmdbUserSetting which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 for another user's settings without ``base.user-management.user.edit``; 400 for an
                       invalid body, a setting for the resource that exists already (also when a concurrent create
                       won), or a failed read or write; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The created CmdbUserSetting in the routes' one shape (``raw``), and the stamped
            storage id as ``result_id``
    """
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    # Pin the owning user to the URL so a mismatched body cannot store the setting under another id
    data[UserSettingKey.USER_ID.value] = user_id

    resource: Any = data.get(UserSettingKey.RESOURCE.value)
    exists_message: str = UserSettingMessage.EXISTS.format(resource=resource)

    # A setting is uniquely identified by (user_id, resource); the read answers the ordinary case readably,
    # the unique index the concurrent one
    if user_settings_manager.get_user_setting(user_id, resource):
        abort(400, exists_message)

    try:
        new_public_id: int = user_settings_manager.insert_item(data)
    except UserSettingsManagerInsertError as err:
        abort_if_too_large(err)
        abort_if_duplicate(err, exists_message)

    # Answered from the body that was just written instead of being read back (one query instead of two).
    # The stamped id is the envelope's result_id only - it is not part of a setting
    return InsertSingleResponse(raw=serialize_user_setting(data), result_id=new_public_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@user_settings_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.protect(auth=True, right=USER_SETTINGS_RIGHT, excepted=OWNER_EXCEPTION)
@handle_route_errors("while retrieving the UserSettings")
@handle_manager_errors({UserSettingsManagerIterationError: UserSettingMessage.LIST_FAILED})
def get_cmdb_user_settings(user_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting all CmdbUserSettings for the CmdbUser

    Args:
        user_id (int): public_id of the CmdbUser the settings belong to
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 for another user's settings without ``base.user-management.user.edit``; 400 when the read
                       fails, 503 past the query time budget, 500 on an unexpected error

    Returns:
        GetListResponse: All the readable CmdbUserSettings of the target CmdbUser, with the count in
            the X-Total-Count header. A stored document that cannot be read is left out and reported
            in the log rather than failing the whole read
    """
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    # Already normalised by the manager, which also skips (and reports) a document it cannot read
    user_settings: list[dict[str, Any]] = user_settings_manager.get_user_settings(user_id=user_id)

    return GetListResponse(results=user_settings, body=request_wants_body()).make_response()


@user_settings_blueprint.route('/<string:resource>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.protect(auth=True, right=USER_SETTINGS_RIGHT, excepted=OWNER_EXCEPTION)
@handle_route_errors("while retrieving the UserSetting for resource: {resource}")
@handle_manager_errors({UserSettingsManagerGetError: UserSettingMessage.GET_FAILED})
def get_cmdb_user_setting(user_id: int, resource: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbUserSetting

    Args:
        user_id (int): public_id of the CmdbUser the setting belongs to
        resource (str): name of the resource
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 for another user's settings without ``base.user-management.user.edit``; 404 when there is
                       no such setting, 400 when the read fails, 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbUserSetting in the routes' one shape - normalised like the list read
    """
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    requested_user_setting = user_settings_manager.get_user_setting(user_id, resource)

    if not requested_user_setting:
        abort(404, UserSettingMessage.NOT_FOUND.format(resource=resource))

    return GetSingleResponse(serialize_user_setting(requested_user_setting), body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@user_settings_blueprint.route('/<string:resource>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.protect(auth=True, right=USER_SETTINGS_RIGHT, excepted=OWNER_EXCEPTION)
@user_settings_blueprint.validate(build_write_schema(CmdbUserSetting.SCHEMA))
@handle_route_errors("while updating the UserSetting for resource: {resource}")
@handle_manager_errors({
    UserSettingsManagerGetError: UserSettingMessage.GET_FAILED,
    UserSettingsManagerInsertError: UserSettingMessage.CREATE_FAILED,
    UserSettingsManagerUpdateError: UserSettingMessage.UPDATE_FAILED,
})
def update_cmdb_user_setting(user_id: int, resource: str, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbUserSetting or create it if it does not exist

    The whole setting is written (no partial update). A setting that appears between the read and the insert - a
    concurrent request created it - is updated instead of refused

    Args:
        user_id (int): public_id of the CmdbUser the setting belongs to
        resource (str): name of the resource
        data (dict): The new data of the CmdbUserSetting
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 for another user's settings without ``base.user-management.user.edit``; 400 for an
                       invalid body or a failed read or write, 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The stored CmdbUserSetting - ``resource``, ``user_id``, ``payloads`` and
            ``setting_type``, the shape the list read answers
    """
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    # Pin the owning user + resource to the URL so a mismatched body cannot target another record
    data[UserSettingKey.USER_ID.value] = user_id
    data[UserSettingKey.RESOURCE.value] = resource

    to_update_user_setting = user_settings_manager.get_user_setting(user_id, resource)
    user_setting: CmdbUserSetting = CmdbUserSetting.from_data(data)

    if to_update_user_setting:
        user_settings_manager.update_user_setting(user_id, resource, user_setting)
    else:
        try:
            user_settings_manager.insert_item(data)
        except UserSettingsManagerInsertError as err:
            abort_if_too_large(err)

            # Another request created it meanwhile: the unique index refused this insert, so update instead
            if find_cause(err, DocumentDuplicateKeyError) is None:
                raise

            user_settings_manager.update_user_setting(user_id, resource, user_setting)

    # The setting as the model reads it, in the routes' one shape
    return UpdateSingleResponse(serialize_user_setting(CmdbUserSetting.to_json(user_setting))).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@user_settings_blueprint.route('/<string:resource>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.protect(auth=True, right=USER_SETTINGS_RIGHT, excepted=OWNER_EXCEPTION)
@handle_route_errors("while deleting the UserSetting for resource: {resource}")
@handle_manager_errors({
    UserSettingsManagerGetError: UserSettingMessage.GET_FAILED,
    UserSettingsManagerDeleteError: UserSettingMessage.DELETE_FAILED,
})
def delete_cmdb_user_setting(user_id: int, resource: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbUserSetting

    Args:
        user_id (int): public_id of the CmdbUser the setting belongs to
        resource (str): name of the resource
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 for another user's settings without ``base.user-management.user.edit``; 404 when there is
                       no such setting, 400 when the read or the delete fails, 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbUserSetting in the routes' one shape
    """
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    to_delete_user_setting = user_settings_manager.get_user_setting(user_id, resource)

    if not to_delete_user_setting:
        abort(404, UserSettingMessage.NOT_FOUND.format(resource=resource))

    user_settings_manager.delete_user_setting(user_id=user_id, resource=resource)

    return DeleteSingleResponse(serialize_user_setting(to_delete_user_setting)).make_response()
