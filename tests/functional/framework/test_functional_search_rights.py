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
Who may search: the audience of `GET|POST /search/` and `GET /search/quick/count/`

**The rule: searching is reading objects, so it asks for the object-view right.** A search answers
rendered CmdbObjects and the quick count answers how many there are, so both ask for
``SearchRight.VIEW`` (``base.framework.object.view``). Without it, a group refused on every `/objects/`
read could still read the same objects through the search box.

Pinned three ways: a group without the right is refused on both routes, naming it; the right alone is
enough; and for every group the search answers what the object list answers - the two surfaces never
disagree about who may read objects
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.search.search_constants import SearchFormType, SearchQueryKey, SearchRight
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SEARCH_URL: str = '/search/'
QUICK_COUNT_URL: str = '/search/quick/count/'
OBJECT_LIST_URL: str = '/objects/?limit=1'

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

TYPE_VIEW_RIGHT: str = 'base.framework.type.view'
SEARCH_TERM: str = 'search-rights-term'

TYPE_VIEWER_GROUP_ID: int = 47801
OBJECT_VIEWER_GROUP_ID: int = 47802
TYPE_VIEWER_USER_ID: int = 47811
OBJECT_VIEWER_USER_ID: int = 47812
DEFAULT_USER_ID: int = 47813

ALL_GROUP_IDS: list[int] = [TYPE_VIEWER_GROUP_ID, OBJECT_VIEWER_GROUP_ID]
ALL_USER_IDS: list[int] = [TYPE_VIEWER_USER_ID, OBJECT_VIEWER_USER_ID, DEFAULT_USER_ID]

TYPE_VIEWER: str = 'type-viewer'
OBJECT_VIEWER: str = 'object-viewer'
DEFAULT_USER: str = 'default-user'


def _search_body() -> str:
    """A one-term TEXT search."""
    return json.dumps([{'searchText': SEARCH_TERM, 'searchForm': SearchFormType.TEXT.value}])


def _call_search(rest_api, user: CmdbUser):
    """POSTs the search as `user`."""
    return rest_api.post(SEARCH_URL, data=_search_body(), content_type='application/json', user=user)


def _call_quick_count(rest_api, user: CmdbUser):
    """Asks for the quick count as `user`."""
    return rest_api.get(QUICK_COUNT_URL, query_string={SearchQueryKey.SEARCH_VALUE.value: SEARCH_TERM}, user=user)


SEARCH_ROUTES: list[tuple[str, Any]] = [('search', _call_search), ('quick-count', _call_quick_count)]
ROUTE_IDS: list[str] = [route[0] for route in SEARCH_ROUTES]


def _insert_user(database_manager: MongoDatabaseManager, database_name: str, public_id: int,
                 group_id: int) -> CmdbUser:
    """Stores an active user in `group_id` and answers the model the test client sends as."""
    user_name: str = f'search-rights-{public_id}'
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': public_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
    })

    return CmdbUser(public_id=public_id, user_name=user_name, active=True, group_id=group_id)


@pytest.fixture(name='users', scope='module')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A type-viewer (no object right), an object-viewer (that right alone) and a default-group user."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})

    _purge()
    groups.insert_many([
        {'public_id': TYPE_VIEWER_GROUP_ID, 'name': 'search-type-viewers', 'label': 'Type viewers',
         'rights': [TYPE_VIEW_RIGHT]},
        {'public_id': OBJECT_VIEWER_GROUP_ID, 'name': 'search-object-viewers', 'label': 'Object viewers',
         'rights': [SearchRight.VIEW.value]},
    ])

    yield {
        TYPE_VIEWER: _insert_user(database_manager, database_name, TYPE_VIEWER_USER_ID, TYPE_VIEWER_GROUP_ID),
        OBJECT_VIEWER: _insert_user(database_manager, database_name, OBJECT_VIEWER_USER_ID, OBJECT_VIEWER_GROUP_ID),
        DEFAULT_USER: _insert_user(database_manager, database_name, DEFAULT_USER_ID, USER_GROUP_ID),
    }

    _purge()


class TestAGroupWithoutTheRightIsRefused:
    """A group that may read types but not objects cannot search them either."""

    @pytest.mark.parametrize('label, call', SEARCH_ROUTES, ids=ROUTE_IDS)
    def test_the_route_refuses_it_naming_the_right(self, rest_api, users: dict[str, CmdbUser], label: str,
                                                   call: Any) -> None:
        """403 naming the object-view right"""
        del label

        response = call(rest_api, users[TYPE_VIEWER])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=SearchRight.VIEW.value)

    def test_without_a_token_both_routes_answer_401(self, rest_api) -> None:
        """The right is checked on an authenticated user - without a token the answer stays 401, not 403"""
        no_token: dict[str, str] = {'HTTP_AUTHORIZATION': ''}

        quick = rest_api.get(QUICK_COUNT_URL, environ_overrides=no_token)
        search = rest_api.post(SEARCH_URL, data=_search_body(), content_type='application/json',
                               environ_overrides=no_token)

        assert (quick.status_code, search.status_code) == (HTTPStatus.UNAUTHORIZED, HTTPStatus.UNAUTHORIZED)


class TestTheRightAloneIsEnough:
    """The object-view right needs nothing beside it; the seeded user group holds it."""

    @pytest.mark.parametrize('label, call', SEARCH_ROUTES, ids=ROUTE_IDS)
    @pytest.mark.parametrize('who', [OBJECT_VIEWER, DEFAULT_USER])
    def test_the_route_answers(self, rest_api, users: dict[str, CmdbUser], who: str, label: str,
                               call: Any) -> None:
        """200 for a group holding exactly the right, and for the default group"""
        del label

        assert call(rest_api, users[who]).status_code == HTTPStatus.OK


class TestSearchAndTheObjectListAgree:
    """For every group, the search answers what the object list answers."""

    @pytest.mark.parametrize('label, call', SEARCH_ROUTES, ids=ROUTE_IDS)
    @pytest.mark.parametrize('who', [TYPE_VIEWER, OBJECT_VIEWER, DEFAULT_USER])
    def test_the_same_audience(self, rest_api, users: dict[str, CmdbUser], who: str, label: str,
                               call: Any) -> None:
        """Allowed to list objects exactly when allowed to search them"""
        del label

        list_status: int = rest_api.get(OBJECT_LIST_URL, user=users[who]).status_code

        assert (call(rest_api, users[who]).status_code == HTTPStatus.FORBIDDEN) \
            == (list_status == HTTPStatus.FORBIDDEN)
