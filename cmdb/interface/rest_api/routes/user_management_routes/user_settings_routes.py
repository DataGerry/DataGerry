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

The two reads answer slightly different shapes today: the single-resource read hands back the stored
document (including the stamped `public_id`), the list read the four normalised keys. Which one both
should answer is discussion-backlog #218
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import UserSettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    GetListResponse,
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetSingleResponse,
)

from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerInsertError,
    UserSettingsManagerGetError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
    UserSettingsManagerIterationError,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

user_settings_blueprint = APIBlueprint('user_settings', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@user_settings_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.validate(CmdbUserSetting.SCHEMA)
def insert_cmdb_user_setting(user_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbUserSetting into the database

    Args:
        user_id (int): public_id of CmdbUser
        data (CmdbUserSetting.SCHEMA): Data of the CmdbUserSetting which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        InsertSingleResponse: The created CmdbUserSetting with its stamped public_id
    """
    try:
        user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                                 request_user)

        # Pin the owning user to the URL so a mismatched body cannot store the setting under another id
        data[UserSettingKey.USER_ID.value] = user_id

        resource: Any = data.get(UserSettingKey.RESOURCE.value)

        # A setting is uniquely identified by (user_id, resource); reject a duplicate create explicitly
        # rather than relying on the unique index (business-rule rejection -> 400)
        if user_settings_manager.get_user_setting(user_id, resource):
            abort(400, f"A UserSetting for resource: '{resource}' already exists for this user!")

        # The stamped public_id comes back from the insert, so the created setting is answered from
        # the body that was just written instead of being read back (one query instead of two)
        new_public_id: int = user_settings_manager.insert_item(data)

        return InsertSingleResponse(
            raw={**data, UserSettingKey.PUBLIC_ID.value: new_public_id},
            result_id=new_public_id,
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except UserSettingsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_user_setting] UserSettingsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new UserSetting in the database!")
    except UserSettingsManagerGetError as err:
        LOGGER.error("[insert_cmdb_user_setting] UserSettingsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created UserSetting from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_user_setting] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating a UserSetting!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@user_settings_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_cmdb_user_settings(user_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting all CmdbUserSettings for the CmdbUser

    Args:
        user_id (int): public_id of CmdbUser
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetListResponse: All the readable CmdbUserSettings of the target CmdbUser, with the count in
            the X-Total-Count header. A stored document that cannot be read is left out and reported
            in the log rather than failing the whole read
    """
    try:
        user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                                 request_user)

        # Already normalised by the manager, which also skips (and reports) a document it cannot read
        user_settings: list[dict[str, Any]] = user_settings_manager.get_user_settings(user_id=user_id)

        return GetListResponse(results=user_settings, body=request_wants_body()).make_response()
    except UserSettingsManagerIterationError as err:
        LOGGER.error("[get_cmdb_user_settings] UserSettingsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve UserSettings from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_user_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving UserSettings!")


@user_settings_blueprint.route('/<string:resource>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_cmdb_user_setting(user_id: int, resource: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbUserSetting

    Args:
        user_id (int): public_id of CmdbUser
        resource (str): name of the resource
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetSingleResponse: The requested CmdbUserSetting
    """
    try:
        user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                                 request_user)

        requested_user_setting = user_settings_manager.get_user_setting(user_id, resource)

        if requested_user_setting:
            return GetSingleResponse(requested_user_setting, body=request_wants_body()).make_response()

        abort(404, f"The requested UserSetting for resource: '{resource}' was not found!")
    except HTTPException as http_err:
        raise http_err
    except UserSettingsManagerGetError as err:
        LOGGER.error("[get_cmdb_user_setting] UserSettingsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserSetting for resource: '{resource}' from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_user_setting] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the UserSetting for resource: {resource}!")


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@user_settings_blueprint.route('/<string:resource>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@user_settings_blueprint.validate(CmdbUserSetting.SCHEMA)
def update_cmdb_user_setting(user_id: int, resource: str, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbUserSetting or create it if it does not exist

    Args:
        user_id (int): public_id of CmdbUser
        resource (str): name of the resource
        data (dict): The new data of the CmdbUserSetting
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        UpdateSingleResponse: With update result of the new updated user setting.
    """
    try:
        user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                                 request_user)

        # Pin the owning user + resource to the URL so a mismatched body cannot target another record
        data[UserSettingKey.USER_ID.value] = user_id
        data[UserSettingKey.RESOURCE.value] = resource

        to_update_user_setting = user_settings_manager.get_user_setting(user_id, resource)

        # If it does not exist, create it
        if not to_update_user_setting:
            user_settings_manager.insert_item(data)
        else:
            user_settings_manager.update_user_setting(user_id, resource, CmdbUserSetting.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except UserSettingsManagerGetError as err:
        LOGGER.error("[update_cmdb_user_setting] UserSettingsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserSetting for resource: '{resource}' from the database!")
    except UserSettingsManagerInsertError as err:
        LOGGER.error("[update_cmdb_user_setting] UserSettingsManagerInsertError: %s", err, exc_info=True)
        abort(400, f"Failed to create the UserSetting for resource: '{resource}' in the database!")
    except UserSettingsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_user_setting] UserSettingsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the UserSetting for resource: '{resource}' in the database!")
    except Exception as err:
        LOGGER.error("[update_cmdb_user_setting] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the UserSetting for resource: {resource}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@user_settings_blueprint.route('/<string:resource>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def delete_cmdb_user_setting(user_id: int, resource: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbUserSetting

    Args:
        user_id (int): public_id of CmdbUser
        resource (str): name of the resource
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbUserSetting data
    """
    try:
        user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                                 request_user)

        to_delete_user_setting = user_settings_manager.get_user_setting(user_id, resource)

        if not to_delete_user_setting:
            abort(404, f"The UserSetting for resource: '{resource}' was not found!")

        user_settings_manager.delete_user_setting(user_id=user_id, resource=resource)

        return DeleteSingleResponse(to_delete_user_setting).make_response()
    except HTTPException as http_err:
        raise http_err
    except UserSettingsManagerGetError as err:
        LOGGER.error("[delete_cmdb_user_setting] UserSettingsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserSetting for resource: '{resource}' from the database!")
    except UserSettingsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_user_setting] UserSettingsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the UserSetting for resource: '{resource}' from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_user_setting] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the UserSetting for resource: {resource}!")
