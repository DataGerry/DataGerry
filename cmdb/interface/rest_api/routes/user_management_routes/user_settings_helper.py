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
Helpers of the CmdbUserSetting routes: the one shape every route answers, and the owner check of the writes

A setting's identity is ``(user_id, resource)``; the ``public_id`` the shared insert path stamps on the stored
document is a storage artifact no client reads. So every route - create, list, single read, update, delete - answers
the same four keys the list read always answered: ``resource``, ``user_id``, ``payloads``, ``setting_type``.

A setting is written only for a user that exists (``abort_if_settings_owner_missing``): user ids come from a counter,
so the next one is predictable, and a setting written for it would be the next created user's from its first login.
"""
from typing import Any

from flask import abort

from cmdb.manager import UsersManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.settings_model import UserSettingKey, normalize_user_setting_document
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import USER_NOT_FOUND_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

# Keys the stored document carries that are not part of a setting: the id the shared insert path stamps, and
# MongoDB's own
STORAGE_ONLY_KEYS: frozenset[str] = frozenset({UserSettingKey.PUBLIC_ID.value, '_id'})


def serialize_user_setting(document: dict[str, Any]) -> dict[str, Any]:
    """
    Answers a stored or written CmdbUserSetting document in the settings routes' one shape

    The four normalised keys (``normalize_user_setting_document``: a missing payload list becomes an empty one, the
    scope its stored value). A stored document the normaliser cannot read - one this version never wrote, e.g. a
    scope it does not know - is answered as stored, minus the stamped ``public_id``, so a client can inspect what is
    wrong with it and overwrite or delete it; the normaliser has already logged it

    Args:
        document (dict[str, Any]): A stored CmdbUserSetting document, or a validated write body

    Returns:
        dict[str, Any]: The four keys, or an unreadable document's stored keys - never ``public_id``
    """
    normalized: dict[str, Any] | None = normalize_user_setting_document(document)

    if normalized is not None:
        return normalized

    return {key: value for key, value in document.items() if key not in STORAGE_ONLY_KEYS}


def abort_if_settings_owner_missing(user_id: int, request_user: CmdbUser) -> None:
    """
    Refuses a settings write for a user that does not exist, with the 404 the user routes answer

    The caller's own settings need no read - the caller exists. Anyone else's are read once, by public_id

    Args:
        user_id (int): public_id of the user the path names
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when no user carries the public_id
        UsersManagerGetError: When the user could not be read
    """
    if user_id == request_user.public_id:
        return

    users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

    if users_manager.get_user(user_id) is None:
        abort(404, USER_NOT_FOUND_MESSAGE.format(public_id=user_id))
