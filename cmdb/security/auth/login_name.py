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
How a submitted login is normalised and looked up

The one place that decides how the login a user typed becomes a lookup, so the entry points cannot
drift apart again:

  - **toward the Service Portal** (cloud mode) the email is stripped and lower-cased
    (``normalize_login_email``). Every cloud entry point - the login route, HTTP Basic with and without
    an ``x-api-key`` - sends the portal the same spelling, and the user cache is keyed on it
  - **toward the stored CmdbUser** the login is stripped and tried as given, then - on premise only -
    lower-cased (``login_lookup_queries``). On premise a user name is stored exactly as it was created,
    so ``Admin`` must still find ``Admin`` while ``ADMIN`` finds ``admin``. In cloud mode the lookup is
    by email and uses the address the portal answered with, which is the spelling the tenant user was
    stored under, so it is tried as given only
"""
from cmdb.models.user_model import CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'login_lookup_queries',
    'normalize_login_email',
    'strip_login',
]


def strip_login(login: str) -> str:
    """
    Removes the whitespace around a submitted login

    A login is never meant to start or end with whitespace; a trailing space picked up by a copy-paste
    or an API client would otherwise make a correct login fail

    Args:
        login (str): The login as submitted

    Returns:
        str: The login without leading and trailing whitespace
    """
    return login.strip()


def normalize_login_email(email: str) -> str:
    """
    Spells a submitted email the way every cloud entry point sends it to the Service Portal

    Args:
        email (str): The email as submitted

    Returns:
        str: The email stripped and lower-cased
    """
    return strip_login(email).lower()


def login_lookup_queries(login: str, cloud_mode: bool) -> list[dict[str, str]]:
    """
    Builds the CmdbUser lookups a login is tried with, in order

    Args:
        login (str): The login as submitted - a user name on premise, an email in cloud mode
        cloud_mode (bool): Whether the instance runs in cloud mode

    Returns:
        list[dict[str, str]]: The queries to try until one matches: the stripped login, then - on premise,
            when it differs - its lower-case form
    """
    stripped: str = strip_login(login)

    if cloud_mode:
        return [{CmdbUserKey.EMAIL.value: stripped}]

    queries: list[dict[str, str]] = [{CmdbUserKey.USER_NAME.value: stripped}]

    if stripped != stripped.lower():
        queries.append({CmdbUserKey.USER_NAME.value: stripped.lower()})

    return queries
