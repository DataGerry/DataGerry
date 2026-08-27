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
Dict-key enum for a stored CmdbUser document
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class CmdbUserKey(BaseStrEnum):
    """
    Keys of a stored CmdbUser document

    `CmdbUser.from_data` reads these and `CmdbUser.to_json` writes them, so the two halves of the
    round-trip are defined once here instead of being spelled out twice. Use these members instead of
    bare string literals when reading or building a user document, so a typo becomes an AttributeError
    rather than a silently dropped field

    PASSWORD is the stored password digest. It is part of the DOCUMENT - `to_json` is what
    `UsersManager.insert_user` / `update_user` persist - but it must never reach a client; the routes
    serialise with `CmdbUser.to_public_json` for that reason

    Attributes:
        PUBLIC_ID: Unique identifier of the CmdbUser
        USER_NAME: Login name; unique, backed by the collection's only index
        ACTIVE: Whether the CmdbUser may authenticate
        GROUP_ID: public_id of the CmdbUserGroup the CmdbUser belongs to
        REGISTRATION_TIME: When the CmdbUser was created
        AUTHENTICATOR: Name of the auth provider that owns this CmdbUser
        DATABASE: Name of the database the CmdbUser belongs to (cloud mode)
        API_LEVEL: The CmdbUser's ApiLevel
        CONFIG_ITEMS_LIMIT: Maximum number of CmdbObjects the subscription allows
        EMAIL: Email address of the CmdbUser
        PASSWORD: The stored password digest - never serialised to a client
        IMAGE: Profile image reference
        FIRST_NAME: Given name, optional
        LAST_NAME: Family name, optional
    """
    PUBLIC_ID = 'public_id'
    USER_NAME = 'user_name'
    ACTIVE = 'active'
    GROUP_ID = 'group_id'
    REGISTRATION_TIME = 'registration_time'
    AUTHENTICATOR = 'authenticator'
    DATABASE = 'database'
    API_LEVEL = 'api_level'
    CONFIG_ITEMS_LIMIT = 'config_items_limit'
    EMAIL = 'email'
    PASSWORD = 'password'
    IMAGE = 'image'
    FIRST_NAME = 'first_name'
    LAST_NAME = 'last_name'
