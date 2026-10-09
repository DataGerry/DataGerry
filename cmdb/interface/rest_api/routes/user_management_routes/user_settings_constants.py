# DATAGERRY - OpenSource Enterprise CMDB
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
Constants of the CmdbUserSetting REST routes

Who may use them (``USER_SETTINGS_RIGHT`` + ``OWNER_EXCEPTION``) and what they answer when a request is refused or a
write fails. The ``{resource}`` placeholders are filled from the route's own argument (``handle_manager_errors``)
"""
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import UserAccessRight
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'USER_SETTINGS_RIGHT',
    'OWNER_EXCEPTION',
    'UserSettingMessage',
]

# The owner of the settings in the path reaches them without a right; anyone else needs the right to edit users
USER_SETTINGS_RIGHT: str = UserAccessRight.EDIT.value

# `protect`'s carve-out: the caller's public_id equal to the route's user_id
OWNER_EXCEPTION: dict[str, str] = {'public_id': 'user_id'}


class UserSettingMessage:
    """What the settings routes answer"""
    EXISTS = "A UserSetting for resource: '{resource}' already exists for this user!"
    NOT_FOUND = "The UserSetting for resource: '{resource}' was not found!"
    INSERT_FAILED = "Failed to insert the new UserSetting in the database!"
    CHECK_FAILED = "Failed to check whether the UserSetting exists already!"
    LIST_FAILED = "Failed to retrieve UserSettings from the database!"
    GET_FAILED = "Failed to retrieve the UserSetting for resource: '{resource}' from the database!"
    CREATE_FAILED = "Failed to create the UserSetting for resource: '{resource}' in the database!"
    UPDATE_FAILED = "Failed to update the UserSetting for resource: '{resource}' in the database!"
    DELETE_FAILED = "Failed to delete the UserSetting for resource: '{resource}' from the database!"
