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
The request contract of ``POST /auth/login``

The login body is checked before any credential is: a malformed body is a 400 naming the field, so it reveals
nothing about accounts. Both login names are strings - which is also what keeps a JSON object (``{"$ne": ...}``)
from ever reaching the user lookup as a query
"""
from typing import Any

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['LoginKey', 'LOGIN_REQUEST_SCHEMA', 'CloudLoginMessage']


class LoginKey(BaseStrEnum):
    """
    The keys of a login body

    USER_NAME and PASSWORD are the credentials. SUBSCRIPTION is cloud mode's second step: the subscription the user
    chose from the list the first step answered, sent back whole - only its ID decides
    """
    USER_NAME = 'user_name'
    PASSWORD = 'password'
    SUBSCRIPTION = 'subscription'
    SUBSCRIPTION_ID = 'id'


# Non-empty strings for the credentials; the subscription is an object carrying its id, and the other keys the
# frontend sends back with it (name, short_id) are allowed and kept
LOGIN_REQUEST_SCHEMA: dict[str, Any] = {
    LoginKey.USER_NAME.value: {'type': 'string', 'required': True, 'empty': False},
    LoginKey.PASSWORD.value: {'type': 'string', 'required': True, 'empty': False},
    LoginKey.SUBSCRIPTION.value: {
        'type': 'dict',
        'required': False,
        'nullable': True,
        'allow_unknown': True,
        'schema': {
            LoginKey.SUBSCRIPTION_ID.value: {'required': True, 'nullable': False},
        },
    },
}


class CloudLoginMessage(BaseStrEnum):
    """
    What the cloud login answers when it refuses: the caller's credentials and account (401 / 403 / 400), and the
    faults that are not the caller's - the Service Portal's and the server's own (500). A database outage is never
    one of these: it reaches the app's handlers (503 / 423)
    """
    NO_PORTAL_ANSWER = 'Invalid user data. Failed to login!'
    INVALID_CREDENTIALS = 'Invalid credentials!'
    NO_SUBSCRIPTION = 'The user has no assigned subscription!'
    SUBSCRIPTION_NOT_FOUND = 'Target subscription not found!'
    UNKNOWN_USER = 'Invalid user or password. Could not login!'
    PORTAL_NOT_CONFIGURED = 'No access token found!'
    PORTAL_TIMEOUT = 'Login request timed out!'
    PORTAL_REQUEST_FAILED = 'Login failed due a malformed request!'
    USER_UNREADABLE = "Could not login because user can't be retrieved from database!"
    USER_NOT_STORED = "Could not login because user can't be inserted in database!"
