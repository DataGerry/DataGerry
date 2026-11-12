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
Census: every login refusal of the caller's credentials answers 401, read off the source of ``auth_helper``

A refused password, an unknown user, a portal that has no user for the login and an account with no subscription are
failed authentications - 401, whatever the channel. 403 means "authenticated, but not allowed", which the login never
answers: the census finds no ``abort(403, ...)`` in the module at all, and each credential message aborted with 401.
"""
import ast
import inspect
from typing import Any

import pytest

from cmdb.interface.rest_api.routes import auth_helper
# -------------------------------------------------------------------------------------------------------------------- #

UNAUTHORIZED: int = 401
FORBIDDEN: int = 403
ABORT_NAME: str = 'abort'
# The credential refusals, as the source spells their message argument
CREDENTIAL_MESSAGES: list[str] = [
    'CloudLoginMessage.INVALID_CREDENTIALS.value',
    'CloudLoginMessage.NO_PORTAL_ANSWER.value',
    'CloudLoginMessage.NO_SUBSCRIPTION.value',
    'CloudLoginMessage.UNKNOWN_USER.value',
    'INVALID_CREDENTIALS_MESSAGE',
]


def _aborts() -> list[tuple[Any, str]]:
    """Every `abort(<status>, <message>)` in auth_helper, as (status literal, message source)"""
    tree = ast.parse(inspect.getsource(auth_helper))
    found: list[tuple[Any, str]] = []

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == ABORT_NAME
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)):
            found.append((node.args[0].value, ast.unparse(node.args[1])))

    return found


def test_the_census_reads_the_aborts() -> None:
    """The scan finds the module's refusals at all"""
    assert len(_aborts()) >= len(CREDENTIAL_MESSAGES)


def test_no_login_refusal_answers_403() -> None:
    """403 is for a missing right; no login refusal is one"""
    assert [message for status, message in _aborts() if status == FORBIDDEN] == []


@pytest.mark.parametrize('message', CREDENTIAL_MESSAGES)
def test_each_credential_refusal_answers_401(message: str) -> None:
    """Wherever the module refuses the caller's credentials"""
    statuses = {status for status, source in _aborts() if source == message}

    assert statuses == {UNAUTHORIZED}
