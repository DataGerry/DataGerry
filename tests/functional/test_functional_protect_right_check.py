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
Functional coverage of the right check `APIBlueprint.protect` runs, over HTTP

`insert_request_user` authenticates and resolves the user; `protect`, below it, checks the route's
right on that same user. So a protected request reads the user once, a user without the right gets
403, a user acting on their own record passes the `excepted` carve-out, and a group that cannot be
read is answered as the outage it is - 500 - rather than as a missing right
"""
from datetime import datetime, timezone
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints.api_blueprint_constants import RIGHT_CHECK_FAILED_MESSAGE
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_URL: str = '/types/?limit=1'
TYPES_RIGHT_REFUSAL: str = 'User has not the required right base.framework.type.view'

RIGHTLESS_GROUP_ID: int = 93950
RIGHTLESS_USER_ID: int = 93951
RIGHTLESS_USER_NAME: str = 'protect-rightless'


@pytest.fixture(name='rightless_user')
def fixture_rightless_user(database_manager: MongoDatabaseManager, database_name: str):
    """An active user whose group holds no right at all."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups.delete_many({'public_id': RIGHTLESS_GROUP_ID})
    users.delete_many({'public_id': RIGHTLESS_USER_ID})
    groups.insert_one({'public_id': RIGHTLESS_GROUP_ID, 'name': 'protect-no-rights', 'label': 'No Rights',
                       'rights': []})
    users.insert_one({'public_id': RIGHTLESS_USER_ID, 'user_name': RIGHTLESS_USER_NAME, 'active': True,
                      'group_id': RIGHTLESS_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=RIGHTLESS_USER_ID, user_name=RIGHTLESS_USER_NAME, active=True,
                   group_id=RIGHTLESS_GROUP_ID)

    users.delete_many({'public_id': RIGHTLESS_USER_ID})
    groups.delete_many({'public_id': RIGHTLESS_GROUP_ID})


def test_a_protected_request_reads_the_user_once(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """insert_request_user reads it; the right check uses what it was handed"""
    reads: list[int] = []
    original = UsersManager.get_user

    def _counting_get_user(self, public_id: int):
        reads.append(public_id)
        return original(self, public_id)

    monkeypatch.setattr(UsersManager, 'get_user', _counting_get_user)

    response = rest_api.get(PROTECTED_URL)

    assert response.status_code == HTTPStatus.OK
    assert len(reads) == 1


def test_a_user_without_the_right_is_refused(rest_api, rightless_user: CmdbUser) -> None:
    """The right check still refuses: 403 naming the right"""
    response = rest_api.get(PROTECTED_URL, user=rightless_user)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == TYPES_RIGHT_REFUSAL


def test_a_user_reading_their_own_record_passes_the_carve_out(rest_api, rightless_user: CmdbUser) -> None:
    """GET /users/<own id> carries `excepted={'public_id': 'public_id'}`; another user's id does not match"""
    own = rest_api.get(f'/users/{RIGHTLESS_USER_ID}', user=rightless_user)
    other = rest_api.get('/users/1', user=rightless_user)

    assert own.status_code == HTTPStatus.OK
    assert other.status_code == HTTPStatus.FORBIDDEN


def test_a_group_that_cannot_be_read_is_a_500_not_a_403(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An outage during the check is not reported as a missing right"""
    def _failing_get_group(_self, _public_id: int):
        raise GroupsManagerGetError('the group read failed')

    monkeypatch.setattr(GroupsManager, 'get_group', _failing_get_group)

    response = rest_api.get(PROTECTED_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] == RIGHT_CHECK_FAILED_MESSAGE
