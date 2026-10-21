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
Integration tests for `route_utils.resolve_token_user` against a real MongoDB

A stored user document the model cannot read - no `user_name`, or a creation date nothing can parse - is the
server's fault: the read answers 500 with its own message, never the 401 that would log the user out. A readable
user is answered, and an id the database does not hold stays the 401
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.interface.route_utils import INVALID_USER_MESSAGE, USER_UNREADABLE_MESSAGE, resolve_token_user
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

READABLE_ID: int = 97101
NO_NAME_ID: int = 97102
BAD_DATE_ID: int = 97103
UNKNOWN_ID: int = 97109
USER_IDS: list[int] = [READABLE_ID, NO_NAME_ID, BAD_DATE_ID]


def _claims(public_id: int) -> dict[str, Any]:
    """Decoded claims naming `public_id` (on premise: no tenant)"""
    return {'DATAGERRY': {'value': {'user': {'public_id': public_id}}}}


def _user(public_id: int) -> dict[str, Any]:
    """A complete stored user"""
    return {'public_id': public_id, 'user_name': f'resolve-{public_id}', 'active': True, 'group_id': ADMIN_GROUP_ID,
            'registration_time': datetime.now(timezone.utc)}


@pytest.fixture(autouse=True)
def _users(database_manager: MongoDatabaseManager, database_name: str):
    """One readable and two unreadable stored users - removed after"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': USER_IDS}})
    no_name: dict[str, Any] = _user(NO_NAME_ID)
    del no_name['user_name']
    users.insert_many([_user(READABLE_ID), no_name, {**_user(BAD_DATE_ID), 'registration_time': 'not a date'}])
    yield
    users.delete_many({'public_id': {'$in': USER_IDS}})


@pytest.mark.usefixtures('rest_api_app_context')
def test_a_readable_user_is_answered() -> None:
    """The control"""
    assert resolve_token_user(_claims(READABLE_ID)).public_id == READABLE_ID


@pytest.mark.usefixtures('rest_api_app_context')
@pytest.mark.parametrize('public_id', [NO_NAME_ID, BAD_DATE_ID], ids=['no-user-name', 'bad-date'])
def test_an_unreadable_stored_user_is_a_500(public_id: int) -> None:
    """The model refuses the document: a server fault, not a logout"""
    with pytest.raises(HTTPException) as refused:
        resolve_token_user(_claims(public_id))

    assert (refused.value.code, refused.value.description) == (
        HTTPStatus.INTERNAL_SERVER_ERROR, USER_UNREADABLE_MESSAGE)


@pytest.mark.usefixtures('rest_api_app_context')
def test_an_unknown_user_is_a_401() -> None:
    """Nothing stored under the id"""
    with pytest.raises(HTTPException) as refused:
        resolve_token_user(_claims(UNKNOWN_ID))

    assert (refused.value.code, refused.value.description) == (HTTPStatus.UNAUTHORIZED, INVALID_USER_MESSAGE)
