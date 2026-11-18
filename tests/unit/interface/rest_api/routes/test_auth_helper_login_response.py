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
Unit tests for `auth_helper.make_login_response` - the answer of both login flows

Pinned: the login answer carries the rights of all the user's groups, taken from `route_utils.request_groups` - the
union `protect` judges the user's requests by - and a group read that fails is a 500 with its own message, never the
401 of wrong credentials
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes import auth_helper
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.auth_helper'
USER: SimpleNamespace = SimpleNamespace(public_id=7, group_ids=[2, 5])
TOKEN: bytes = b'the-token'
ISSUED_AT: int = 1757000000
EXPIRES_AT: int = 1757003600
RIGHTS: list[dict[str, Any]] = [{'name': 'base.framework.object.view'}]


def _make(request_groups: MagicMock) -> MagicMock:
    """Runs make_login_response with request_groups and LoginResponse replaced; answers the LoginResponse mock"""
    with Flask(__name__).test_request_context(), \
         patch(f'{PATH}.request_groups', request_groups), \
         patch(f'{PATH}.LoginResponse') as login_response:
        auth_helper.make_login_response(USER, TOKEN, ISSUED_AT, EXPIRES_AT)

    return login_response


def test_the_answer_carries_the_users_effective_rights() -> None:
    """The union of the user's own groups, handed to the LoginResponse with the token"""
    request_groups = MagicMock()
    request_groups.return_value.rights_json.return_value = RIGHTS

    login_response = _make(request_groups)

    request_groups.assert_called_once_with(USER)
    login_response.assert_called_once_with(USER, TOKEN, ISSUED_AT, EXPIRES_AT, RIGHTS)


def test_an_unreadable_group_is_a_500_with_its_message() -> None:
    """The server's fault - and no LoginResponse is built"""
    with pytest.raises(HTTPException) as refused:
        _make(MagicMock(side_effect=GroupsManagerGetError('unreadable')))

    assert refused.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert refused.value.description == auth_helper.LOGIN_GROUPS_UNREADABLE_MESSAGE
