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
Functional coverage of a user's rights coming from several groups, over HTTP

A protected route checks the union of the caller's groups: a user whose first group holds nothing is let in by a
right of its second group, and refused (403) while that second group is not among its groups. A listed group that
no longer exists adds nothing and breaks nothing
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_URL: str = '/types/?limit=1'
TYPE_VIEW: str = 'base.framework.type.view'

EMPTY_GROUP_ID: int = 93970
VIEWER_GROUP_ID: int = 93971
MISSING_GROUP_ID: int = 93979
USER_ID: int = 93975
USER_NAME: str = 'multi-group-rights'


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """A group without rights and one holding the type view right; the test user removed before and after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [EMPTY_GROUP_ID, VIEWER_GROUP_ID]}})
        users.delete_many({'public_id': USER_ID})

    _purge()
    groups.insert_many([
        {'public_id': EMPTY_GROUP_ID, 'name': 'multi-empty', 'label': 'Empty', 'rights': []},
        {'public_id': VIEWER_GROUP_ID, 'name': 'multi-viewer', 'label': 'Viewer', 'rights': [TYPE_VIEW]},
    ])

    yield {'users': users}

    _purge()


def _user(collections: dict[str, Any], group_ids: list[int]) -> CmdbUser:
    """Stores the test user in the given groups and answers it as the client's identity"""
    collections['users'].insert_one({'public_id': USER_ID, 'user_name': USER_NAME, 'active': True,
                                     'group_ids': group_ids, 'registration_time': datetime.now(timezone.utc)})

    return CmdbUser(public_id=USER_ID, user_name=USER_NAME, active=True, group_ids=group_ids)


def test_a_right_of_the_second_group_lets_the_user_in(rest_api, collections) -> None:
    """The first group holds nothing; the second holds the route's right"""
    user = _user(collections, [EMPTY_GROUP_ID, VIEWER_GROUP_ID])

    assert rest_api.get(PROTECTED_URL, user=user).status_code == HTTPStatus.OK


def test_without_that_group_the_user_is_refused(rest_api, collections) -> None:
    """The control: the empty group alone grants nothing"""
    user = _user(collections, [EMPTY_GROUP_ID])

    assert rest_api.get(PROTECTED_URL, user=user).status_code == HTTPStatus.FORBIDDEN


def test_a_listed_group_that_is_gone_adds_nothing(rest_api, collections) -> None:
    """A deleted group beside an existing one: the existing one's rights still count"""
    user = _user(collections, [VIEWER_GROUP_ID, MISSING_GROUP_ID])

    assert rest_api.get(PROTECTED_URL, user=user).status_code == HTTPStatus.OK
