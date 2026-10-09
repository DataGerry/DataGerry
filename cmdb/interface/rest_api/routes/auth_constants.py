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

__all__: list[str] = ['LoginKey', 'LOGIN_REQUEST_SCHEMA']


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
