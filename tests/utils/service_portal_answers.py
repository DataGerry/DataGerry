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
The two answers of the DataGerry Service Portal, in the shape the portal sends them

A test stubbing the portal builds its answer here instead of writing a dict by hand, so a stub cannot carry a field
the portal never sends. The two endpoints differ in one way that matters to the backend:

* the LOGIN answer (``/datagerry/auth``, no key) lists EVERY subscription of the account - and names no tenant
  database at the top level; a caller has to pick a subscription
* the API-KEY answer (``/datagerry/auth/subscription``, with ``x-api-key``) lists exactly ONE subscription: the one
  the key belongs to

Both carry the account's ``email``, ``user_name`` and ``password``; the login answer also its ``api_level``
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['portal_subscription', 'portal_login_answer', 'portal_api_key_answer']

DEFAULT_SUBSCRIPTION_ID: int = 1
DEFAULT_SUBSCRIPTION_NAME: str = 'subscription'
DEFAULT_API_LEVEL: int = 1
DEFAULT_CONFIG_ITEM_LIMIT: int = 1000


def portal_subscription(
        database: str,
        *,
        api_level: int = DEFAULT_API_LEVEL,
        config_item_limit: int = DEFAULT_CONFIG_ITEM_LIMIT,
        api_key: str | None = None,
        subscription_id: int = DEFAULT_SUBSCRIPTION_ID,
        name: str = DEFAULT_SUBSCRIPTION_NAME,
    ) -> dict[str, Any]:
    """
    One entry of an answer's ``subscriptions`` list

    Args:
        database (str): The tenant database the subscription is bound to
        api_level (int): The subscription's API level
        config_item_limit (int): How many CmdbObjects the subscription allows
        api_key (str | None): The subscription's API key; left out when None
        subscription_id (int): The subscription's id, which the frontend sends back to pick one
        name (str): The subscription's display name

    Returns:
        dict[str, Any]: The subscription entry
    """
    subscription: dict[str, Any] = {
        'id': subscription_id,
        'name': name,
        'database': database,
        'api_level': api_level,
        'config_item_limit': config_item_limit,
    }

    if api_key is not None:
        subscription['api_key'] = api_key

    return subscription


def portal_login_answer(
        email: str,
        user_name: str,
        password: str,
        subscriptions: list[dict[str, Any]],
        *,
        api_level: int = DEFAULT_API_LEVEL,
    ) -> dict[str, Any]:
    """
    The portal's answer to a login without a key: the account and every one of its subscriptions

    Args:
        email (str): The account's email, as the portal stores it
        user_name (str): The account's user name
        password (str): The ``password`` field the portal answers with
        subscriptions (list[dict[str, Any]]): Every subscription of the account (``portal_subscription``)
        api_level (int): The account's API level

    Returns:
        dict[str, Any]: The answer - with no top-level ``database``
    """
    return {
        'email': email,
        'user_name': user_name,
        'password': password,
        'api_level': api_level,
        'subscriptions': list(subscriptions),
    }


def portal_api_key_answer(email: str, user_name: str, password: str, subscription: dict[str, Any]) -> dict[str, Any]:
    """
    The portal's answer to a request carrying an ``x-api-key``: the account and the ONE subscription of that key

    Args:
        email (str): The account's email, as the portal stores it
        user_name (str): The account's user name
        password (str): The ``password`` field the portal answers with
        subscription (dict[str, Any]): The subscription the key belongs to (``portal_subscription``)

    Returns:
        dict[str, Any]: The answer
    """
    return {
        'email': email,
        'user_name': user_name,
        'password': password,
        'subscriptions': [subscription],
    }
