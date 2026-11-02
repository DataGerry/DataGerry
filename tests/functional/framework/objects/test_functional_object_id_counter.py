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
Functional tests: how often an object write touches the public_id counters, counted at the driver

An id drawn from a counter is reserved by the draw itself (one ``find_one_and_update``), so its insert leaves the
counter alone; only an id the caller chose raises the counter, with one atomic ``$max``. An update therefore costs
one reservation per edit log and nothing else, and a create costs one reservation for the object and one for its log
"""
from collections import Counter
from http import HTTPStatus
from typing import Any, Iterator

import pymongo.collection
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.models.object_model import CmdbObject

from tests.functional.framework.objects.objects_route_helpers import (
    BULK_OBJECT_IDS,
    BULK_UPDATED_VALUE,
    ROUTE_URL,
    drop_object,
    insert_object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

SEED_VALUE: str = 'seed'
CREATED_VALUE: str = 'created'
#: An id the caller chooses on create - above every id the suite draws, below nothing it relies on
SUPPLIED_OBJECT_ID: int = 9431
RESERVE: str = 'find_one_and_update'
RAISE: str = 'update_one'
PEEK: str = 'find'
#: One edit log per target, each reserving its id
LOG_RESERVATIONS_PER_TARGET: int = 1
#: A create with a drawn id: the object's reservation and its log's
CREATE_RESERVATIONS: int = 2
#: A create with a supplied id: only its log reserves
SUPPLIED_CREATE_RESERVATIONS: int = 1


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The bulk targets, all of the package's one type"""
    for public_id in BULK_OBJECT_IDS:
        insert_object_doc(database_manager, database_name, public_id, SEED_VALUE)
    yield
    for public_id in BULK_OBJECT_IDS:
        drop_object(database_manager, database_name, public_id)


@pytest.fixture(name='counter_ops')
def fixture_counter_ops(monkeypatch: pytest.MonkeyPatch) -> Counter:
    """Counts every reserve, raise and peek the driver runs on the counter collection"""
    ops: Counter = Counter()

    def _counting(name: str) -> None:
        original = getattr(pymongo.collection.Collection, name)

        def _wrapper(collection: Any, *args: Any, **kwargs: Any) -> Any:
            if collection.name == PUBLIC_ID_COUNTER_COLLECTION:
                ops[name] += 1
            return original(collection, *args, **kwargs)

        monkeypatch.setattr(pymongo.collection.Collection, name, _wrapper)

    for name in (RESERVE, RAISE, PEEK):
        _counting(name)

    return ops


def _object_counter(database_manager: MongoDatabaseManager, database_name: str) -> int:
    """The objects' counter as stored"""
    document: dict[str, Any] = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name).find_one(
        {'_id': CmdbObject.COLLECTION})

    return document['counter']


def test_a_bulk_update_reserves_one_id_per_log_and_nothing_else(rest_api, counter_ops: Counter) -> None:
    """Three targets, three edit logs: three reservations, no raise and no peek"""
    response = rest_api.put(f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}',
                            json=object_payload(BULK_OBJECT_IDS[0], BULK_UPDATED_VALUE),
                            query_string={'objectIDs': BULK_OBJECT_IDS})

    assert response.status_code == HTTPStatus.ACCEPTED
    assert counter_ops == Counter({RESERVE: LOG_RESERVATIONS_PER_TARGET * len(BULK_OBJECT_IDS)})


def test_a_create_with_a_drawn_id_only_reserves(rest_api, counter_ops: Counter, database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
    """The object's id and its log's are both drawn - neither insert raises a counter afterwards"""
    payload: dict[str, Any] = object_payload(SUPPLIED_OBJECT_ID, CREATED_VALUE)
    del payload['public_id']

    response = rest_api.post(f'{ROUTE_URL}/', json=payload)

    try:
        assert response.status_code == HTTPStatus.OK
        assert counter_ops == Counter({RESERVE: CREATE_RESERVATIONS})
    finally:
        drop_object(database_manager, database_name, response.get_json())


def test_a_create_with_a_supplied_id_raises_the_counter_to_it(rest_api, counter_ops: Counter,
                                                              database_manager: MongoDatabaseManager,
                                                              database_name: str) -> None:
    """The supplied id is not drawn, so the counter is raised to it - one $max, next to the log's reservation"""
    try:
        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(SUPPLIED_OBJECT_ID, CREATED_VALUE))

        assert response.status_code == HTTPStatus.OK
        assert counter_ops == Counter({RESERVE: SUPPLIED_CREATE_RESERVATIONS, RAISE: 1})
        assert _object_counter(database_manager, database_name) >= SUPPLIED_OBJECT_ID
    finally:
        drop_object(database_manager, database_name, SUPPLIED_OBJECT_ID)
