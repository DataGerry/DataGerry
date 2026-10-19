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
Functional coverage for what a route answers when the types, locations or users manager fails

The three managers catch only the failures their calls raise. A database failure - the ``BaseManager*Error`` of the
call - is still the manager's own error and the route's 400. A programming error reaches the route's generic tail
and answers 500 instead of being dressed up as that 400.

The login is pinned on its own: an unreadable stored user and a failed user read are still refused like an unknown
user (401), a bug in the read is the server's (500)
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.locations_manager import LocationsManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 97201
UNREADABLE_USER_ID: int = 97202
UNREADABLE_USER_NAME: str = 'narrowed-manager-unreadable'

LOGIN_URL: str = '/auth/login'
ADMIN_CREDENTIALS: dict[str, str] = {'user_name': 'admin', 'password': 'admin'}
BUG: str = 'a programming error'

# route, the manager and delegate under it, and the typed failure that delegate raises
CASES: list[tuple[str, type, str, type[Exception]]] = [
    (f'/types/{TYPE_ID}', TypesManager, 'get_one', BaseManagerGetError),
    ('/types/', TypesManager, 'iterate_query', BaseManagerIterationError),
    (f'/locations/{RootLocationDefault.PUBLIC_ID}', LocationsManager, 'get_one', BaseManagerGetError),
    ('/locations/tree/roots', LocationsManager, 'get_many', BaseManagerGetError),
    ('/users/', UsersManager, 'iterate_query', BaseManagerIterationError),
]
CASE_IDS: list[str] = ['type', 'types', 'location', 'location-tree-roots', 'users']


@pytest.fixture(autouse=True)
def _seeded_type(database_manager: MongoDatabaseManager, database_name: str):
    """A type; removed again afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(make_type_doc(TYPE_ID, 'narrowed-manager-status'))

    yield

    types.delete_many({'public_id': TYPE_ID})


@pytest.fixture(name='unreadable_user')
def _unreadable_user(database_manager: MongoDatabaseManager, database_name: str):
    """
    A user document the model cannot read - no 'active' key - written past the validator, the way a drifted
    document got there. Only the login tests seed it: one such user fails the whole users listing as its 400
    """
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': UNREADABLE_USER_ID})
    users.insert_one({'public_id': UNREADABLE_USER_ID, 'user_name': UNREADABLE_USER_NAME, 'password': 'x'},
                     bypass_document_validation=True)

    yield

    users.delete_many({'public_id': UNREADABLE_USER_ID})


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_the_route_answers_without_a_failure(rest_api, url: str, manager: type, delegate: str,
                                             typed: type[Exception]) -> None:
    """The control: each route answers 200 as it stands"""
    del manager, delegate, typed

    assert rest_api.get(url).status_code == HTTPStatus.OK


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_programming_error_answers_500(rest_api, url: str, manager: type, delegate: str,
                                         typed: type[Exception]) -> None:
    """Not the 400 a failed read gets: the bug is the server's"""
    del typed

    with patch.object(manager, delegate, side_effect=TypeError(BUG)):
        response = rest_api.get(url)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_database_failure_still_answers_400(rest_api, url: str, manager: type, delegate: str,
                                              typed: type[Exception]) -> None:
    """The call's own failure is the manager's error, which the route answers 400 with a message"""
    with patch.object(manager, delegate, side_effect=typed('the read failed')):
        response = rest_api.get(url)

    body: dict[str, Any] = response.get_json()

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body['message']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        LOGIN                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheLoginUserRead:
    """What the login answers when the user read under it fails"""

    def test_the_control_logs_in(self, rest_api) -> None:
        """The seeded admin logs in as it stands"""
        assert rest_api.post(LOGIN_URL, json=ADMIN_CREDENTIALS).status_code == HTTPStatus.OK

    def test_an_unreadable_stored_user_is_refused_like_an_unknown_one(self, rest_api, unreadable_user) -> None:
        """The model's declared error is the read's failure, which the login refuses - not a 500"""
        del unreadable_user

        response = rest_api.post(LOGIN_URL, json={'user_name': UNREADABLE_USER_NAME, 'password': 'x'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_failed_user_read_is_refused(self, rest_api) -> None:
        """A database failure under the login still refuses it"""
        with patch.object(UsersManager, 'get_one_by', side_effect=BaseManagerGetError('the read failed')):
            response = rest_api.post(LOGIN_URL, json=ADMIN_CREDENTIALS)

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_bug_in_the_user_read_is_the_servers(self, rest_api) -> None:
        """Not a refused login: nothing about the credentials was judged"""
        with patch.object(UsersManager, 'get_one_by', side_effect=TypeError(BUG)):
            response = rest_api.post(LOGIN_URL, json=ADMIN_CREDENTIALS)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
