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
Functional coverage for what the category and group routes answer when their manager fails, and for the right check

The categories and groups managers catch only the failures their calls raise. A database failure - the
``BaseManager*Error`` of the call - is still the manager's own error and the route's 400; a programming error reaches
the route's generic tail and answers 500. The category tree answers a failed read 500 with its own message, and a
read stopped on its time budget 503.

The right check every protected route runs (``APIBlueprint.protect``) answers a failed group read 500, but a lock
timeout or a lost connection is "try again": the app-wide handlers answer 423 / 503.

Two category behaviours are pinned end to end: deleting a CmdbType takes its id out of every category, and a search
over several matching categories finds the objects of all of them
"""
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.search.search_constants import SearchFormType, SearchResultKey, SearchResultMapKey
from cmdb.manager.categories_manager import CategoriesManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.models.category_model import CmdbCategory
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError, DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerIterationError

from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORIES_URL: str = '/categories/'
TREE_URL: str = '/categories/?view=tree'
GROUPS_URL: str = '/groups/'
SEARCH_URL: str = '/search/'
BUG: str = 'a programming error'
QUERY_TIME_LIMIT_MS: int = 10_000

FIRST_TYPE_ID: int = 97301
SECOND_TYPE_ID: int = 97302
DELETED_TYPE_ID: int = 97303
FIRST_OBJECT_ID: int = 97311
SECOND_OBJECT_ID: int = 97312
FIRST_CATEGORY_ID: int = 97321
SECOND_CATEGORY_ID: int = 97322
HOLDER_CATEGORY_ID: int = 97323
TYPE_IDS: list[int] = [FIRST_TYPE_ID, SECOND_TYPE_ID, DELETED_TYPE_ID]
OBJECT_IDS: list[int] = [FIRST_OBJECT_ID, SECOND_OBJECT_ID]
CATEGORY_IDS: list[int] = [FIRST_CATEGORY_ID, SECOND_CATEGORY_ID, HOLDER_CATEGORY_ID]

# Both searchable categories carry it in their label; the holder category does not
SEARCH_LABEL: str = 'Statusprobe'

# route, the manager and delegate under it, and the typed failure that delegate raises
CASES: list[tuple[str, type, str, type[Exception]]] = [
    (CATEGORIES_URL, CategoriesManager, 'iterate_query', BaseManagerIterationError),
    (GROUPS_URL, GroupsManager, 'iterate_query', BaseManagerIterationError),
]
CASE_IDS: list[str] = ['categories', 'groups']


def _category(public_id: int, label: str, types: list[int]) -> dict[str, Any]:
    """A stored category document"""
    return {'public_id': public_id, 'name': f'status-{public_id}', 'label': label, 'parent': None,
            'meta': {'icon': '', 'order': 0}, 'types': types}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Three types, one object each for the first two, two searchable categories and one holding the third type"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        categories.delete_many({'public_id': {'$in': CATEGORY_IDS}})

    _purge()
    types.insert_many([make_type_doc(type_id, f'status-type-{type_id}') for type_id in TYPE_IDS])
    objects.insert_many([
        make_object_doc(FIRST_OBJECT_ID, FIRST_TYPE_ID, [{'type': 'text', 'name': 'dg-name', 'value': 'first'}]),
        make_object_doc(SECOND_OBJECT_ID, SECOND_TYPE_ID, [{'type': 'text', 'name': 'dg-name', 'value': 'second'}]),
    ])
    categories.insert_many([
        _category(FIRST_CATEGORY_ID, f'{SEARCH_LABEL} One', [FIRST_TYPE_ID]),
        _category(SECOND_CATEGORY_ID, f'{SEARCH_LABEL} Two', [SECOND_TYPE_ID]),
        _category(HOLDER_CATEGORY_ID, 'Holder', [DELETED_TYPE_ID, FIRST_TYPE_ID + SECOND_TYPE_ID]),
    ])

    yield categories

    _purge()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   MANAGER FAILURES                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
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

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message']


class TestTheCategoryTree:
    """What ?view=tree answers when its reads fail"""

    def test_the_control_answers_200(self, rest_api) -> None:
        """The tree as it stands"""
        assert rest_api.get(TREE_URL).status_code == HTTPStatus.OK

    def test_a_failed_read_is_the_trees_500(self, rest_api) -> None:
        """The tree's own message, not the generic tail's"""
        with patch.object(CategoriesManager, 'aggregate_query', side_effect=BaseManagerIterationError('down')):
            response = rest_api.get(TREE_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'tree' in response.get_json()['message']

    def test_a_read_stopped_on_its_time_budget_answers_503(self, rest_api) -> None:
        """A slow query is "try again later", not a broken tree"""
        timeout = DocumentQueryTimeLimitError('too slow', QUERY_TIME_LIMIT_MS)
        stopped = BaseManagerIterationError(timeout)
        # What `raise ... from err` sets in the database layer - the chain the route follows
        stopped.__cause__ = timeout

        with patch.object(CategoriesManager, 'aggregate_query', side_effect=stopped):
            response = rest_api.get(TREE_URL)

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_a_programming_error_answers_500(self, rest_api) -> None:
        """A bug reaches the generic tail"""
        with patch.object(CategoriesManager, 'aggregate_query', side_effect=TypeError(BUG)):
            response = rest_api.get(TREE_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestTheCategoryListTransientFailures:
    """The listing is on the shared route tail, so a transient failure reaches the app-wide handlers"""

    @pytest.mark.parametrize('failure, status', [
        (DocumentNetworkError('connection lost'), HTTPStatus.SERVICE_UNAVAILABLE),
        (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED),
    ], ids=['network', 'lock-timeout'])
    def test_a_transient_failure_is_answered_by_its_handler(self, rest_api, failure: Exception,
                                                            status: HTTPStatus) -> None:
        """Not the listing's 500"""
        with patch.object(CategoriesManager, 'iterate_query', side_effect=failure):
            assert rest_api.get(CATEGORIES_URL).status_code == status


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    THE RIGHT CHECK                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRightCheck:
    """What a protected route answers when reading the caller's group fails"""

    @pytest.mark.parametrize('failure, status', [
        (DocumentNetworkError('connection lost'), HTTPStatus.SERVICE_UNAVAILABLE),
        (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED),
    ], ids=['network', 'lock-timeout'])
    def test_a_transient_failure_is_try_again(self, rest_api, failure: Exception, status: HTTPStatus) -> None:
        """Answered by the app-wide handlers - not as a failed check"""
        with patch.object(GroupsManager, 'get_group', side_effect=failure):
            assert rest_api.get(CATEGORIES_URL).status_code == status

    def test_any_other_failure_is_a_failed_check(self, rest_api) -> None:
        """A failed check is not a missing right: 500, never 403"""
        with patch.object(GroupsManager, 'get_group', side_effect=TypeError(BUG)):
            assert rest_api.get(CATEGORIES_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CATEGORY BEHAVIOURS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeletingATypeCleansItsCategory:
    """DELETE /types/<id> takes the id out of the category that held it"""

    def test_no_category_lists_the_deleted_type(self, rest_api, seeded) -> None:
        """The other entry of the holding category stays"""
        response = rest_api.delete(f'/types/{DELETED_TYPE_ID}')

        assert response.status_code == HTTPStatus.ACCEPTED
        assert seeded.count_documents({'types': DELETED_TYPE_ID}) == 0
        assert seeded.find_one({'public_id': HOLDER_CATEGORY_ID})['types'] == [FIRST_TYPE_ID + SECOND_TYPE_ID]


def _found_object_ids(body: dict[str, Any]) -> set[int]:
    """The object ids of a search answer"""
    return {entry[SearchResultMapKey.RESULT.value]['object_information']['object_id']
            for entry in body[SearchResultKey.RESULTS.value]}


def _category_search(label: str) -> str:
    """The POST body of one category parameter"""
    return json.dumps([{'searchText': label, 'searchForm': SearchFormType.CATEGORY.value,
                        'settings': {'categories': [FIRST_CATEGORY_ID]}}])


class TestTheCategorySearch:
    """A category parameter finds the objects of every category its label matches"""

    def test_two_matching_categories_find_the_objects_of_both(self, rest_api, seeded) -> None:
        """Their types are one union - never two disjoint sets ANDed to nothing"""
        del seeded

        response = rest_api.post(f'{SEARCH_URL}?limit=0', data=_category_search(SEARCH_LABEL),
                                 content_type='application/json')

        assert response.status_code == HTTPStatus.OK
        assert set(OBJECT_IDS) <= _found_object_ids(response.get_json())

    def test_a_label_no_category_carries_finds_nothing(self, rest_api, seeded) -> None:
        """The filter narrows to no type, instead of being ignored"""
        del seeded

        response = rest_api.post(f'{SEARCH_URL}?limit=0', data=_category_search('no category is called this'),
                                 content_type='application/json')

        assert response.status_code == HTTPStatus.OK
        assert not _found_object_ids(response.get_json())
