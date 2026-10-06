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
Integration tests for the ISMS all-or-nothing bulk update against a real MongoDB

The real ImpactCategoryManager under ``update_multiple_items``: one ordered bulk write stores every item; a
refused request leaves the stored categories - and with them the impact fan-out's ``$addToSet`` - working; and
a bulk write that really fails part-way is undone, the item it had already applied put back
"""
from typing import Any

import pytest
from pymongo import UpdateOne
from werkzeug.exceptions import HTTPException

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.models.isms_model import IsmsImpactCategory
from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    IMPACT_CATEGORY_LABEL,
    MAX_ISMS_BULK_UPDATE_ITEMS,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import update_multiple_items, write_bulk_update
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_A: int = 95561
CATEGORY_B: int = 95562
ALL_CATEGORY_IDS: list[int] = [CATEGORY_A, CATEGORY_B]
NEW_IMPACT_ID: int = 95569
WRITE_SCHEMA: dict[str, Any] = build_write_schema(IsmsImpactCategory.SCHEMA)


def _category(public_id: int, sort: int, **overrides: Any) -> dict[str, Any]:
    """A whole stored IsmsImpactCategory"""
    doc: dict[str, Any] = {'public_id': public_id, 'name': f'category-{public_id}', 'impact_descriptions': [],
                           'sort': sort}
    doc.update(overrides)

    return doc


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The impact-category collection with the two categories seeded, purged around each test"""
    collection = database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_CATEGORY_IDS}})
    collection.insert_many([_category(CATEGORY_A, 0), _category(CATEGORY_B, 1)])

    yield collection

    collection.delete_many({'public_id': {'$in': ALL_CATEGORY_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ImpactCategoryManager:
    """The real manager"""
    return ImpactCategoryManager(database_manager)


def _stored(collection) -> dict[int, dict[str, Any]]:
    """The two categories as stored"""
    return {doc['public_id']: doc for doc in collection.find({'public_id': {'$in': ALL_CATEGORY_IDS}}, {'_id': 0})}


def _bulk(manager: ImpactCategoryManager, data: Any) -> list[dict[str, Any]]:
    """The impact-category route's call"""
    return update_multiple_items(manager, IsmsImpactCategory, data, WRITE_SCHEMA, IMPACT_CATEGORY_LABEL,
                                 MAX_ISMS_BULK_UPDATE_ITEMS)


def test_a_reorder_stores_every_item(collection, manager: ImpactCategoryManager) -> None:
    """Both sorts swapped by one bulk write"""
    results = _bulk(manager, [_category(CATEGORY_A, 1), _category(CATEGORY_B, 0)])

    assert [entry['status'] for entry in results] == ['success', 'success']
    assert {public_id: doc['sort'] for public_id, doc in _stored(collection).items()} == {CATEGORY_A: 1,
                                                                                           CATEGORY_B: 0}


def test_a_refused_request_keeps_the_impact_fan_out_working(collection, manager: ImpactCategoryManager) -> None:
    """The string is never stored, so adding a new impact's description entry still works"""
    with pytest.raises(HTTPException):
        _bulk(manager, [_category(CATEGORY_A, 0, impact_descriptions='zzz')])

    manager.update_many({'public_id': CATEGORY_A}, {'impact_descriptions': {'impact_id': NEW_IMPACT_ID}},
                        add_to_set=True)

    assert _stored(collection)[CATEGORY_A]['impact_descriptions'] == [{'impact_id': NEW_IMPACT_ID}]


def test_a_stored_string_is_what_broke_the_fan_out(collection, manager: ImpactCategoryManager) -> None:
    """The failure the schema now prevents: $addToSet refuses a field that is not an array"""
    collection.update_one({'public_id': CATEGORY_A}, {'$set': {'impact_descriptions': 'zzz'}})

    with pytest.raises(BaseManagerUpdateError):
        manager.update_many({'public_id': CATEGORY_A}, {'impact_descriptions': {'impact_id': NEW_IMPACT_ID}},
                            add_to_set=True)


def test_a_bulk_write_failing_part_way_is_undone(collection, manager: ImpactCategoryManager) -> None:
    """The first operation lands, the second fails on the immutable _id - and the first is put back"""
    before = _stored(collection)
    operations = [
        UpdateOne({'public_id': CATEGORY_A}, {'$set': {'name': 'renamed', 'sort': 9}}),
        UpdateOne({'public_id': CATEGORY_B}, {'$set': {'_id': 'not-its-id'}}),
    ]

    with pytest.raises(BaseManagerUpdateError):
        write_bulk_update(manager, operations, before, IMPACT_CATEGORY_LABEL)

    assert _stored(collection) == before
