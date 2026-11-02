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
Functional tests: the caller's group is read once per request, through the real REST app

Counted at the driver on ``management.groups``: a route that asks several right questions - the start assistant's
offer asks three - reads the caller's group once; the user update reads it once (``protect`` and the route's own
"may this caller administer users" share the read) plus once more for a different question, whether the group the
user is written into exists; an ordinary protected route reads it once
"""
from collections import Counter
from http import HTTPStatus
from typing import Any, Callable, Iterator
from unittest.mock import patch

import pymongo.collection
import pytest

from cmdb.models.group_model import CmdbUserGroup
# -------------------------------------------------------------------------------------------------------------------- #

OFFER_URL: str = '/start_assistant/offer'
OBJECTS_URL: str = '/objects/'
ADMIN_URL: str = '/users/1'
SUCCESS: tuple[HTTPStatus, ...] = (HTTPStatus.OK, HTTPStatus.ACCEPTED)


@pytest.fixture(name='group_reads')
def fixture_group_reads() -> Iterator[Callable[[Callable[[], Any]], tuple[Any, int]]]:
    """Runs a request and answers its response and the reads of management.groups it made"""
    counted: Counter = Counter()
    real_find, real_find_one = pymongo.collection.Collection.find, pymongo.collection.Collection.find_one

    def _find(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counted[collection.name] += 1
        return real_find(collection, *args, **kwargs)

    def _find_one(collection: Any, *args: Any, **kwargs: Any) -> Any:
        counted[collection.name] += 1
        return real_find_one(collection, *args, **kwargs)

    def _run(request: Callable[[], Any]) -> tuple[Any, int]:
        counted.clear()
        with patch.object(pymongo.collection.Collection, 'find', _find), \
                patch.object(pymongo.collection.Collection, 'find_one', _find_one):
            response = request()
        return response, counted[CmdbUserGroup.COLLECTION]

    yield _run


def test_the_offer_reads_the_group_once_for_its_three_rights(rest_api, group_reads) -> None:
    """Two start-assistant rights and base.* - one read"""
    response, reads = group_reads(lambda: rest_api.get(OFFER_URL))

    assert response.status_code == HTTPStatus.OK
    assert reads == 1


def test_an_ordinary_protected_route_reads_the_group_once(rest_api, group_reads) -> None:
    """protect's one question"""
    response, reads = group_reads(lambda: rest_api.get(OBJECTS_URL))

    assert response.status_code == HTTPStatus.OK
    assert reads == 1


def test_the_user_update_reads_the_callers_group_once(rest_api, group_reads) -> None:
    """protect and the route's administrator question share one read; the target group's existence is the other"""
    stored: dict[str, Any] = rest_api.get(ADMIN_URL).get_json()['result']
    body: dict[str, Any] = {key: value for key, value in stored.items() if key != 'password'}

    response, reads = group_reads(lambda: rest_api.put(ADMIN_URL, json=body))

    assert response.status_code in SUCCESS
    assert reads == 2
