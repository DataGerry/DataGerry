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
Integration tests for ``ObjectsManager.get_object_field_name_sets_by_type``

Real-MongoDB exercise of the DB-side aggregation backing the type clean-status route. Seeds
CmdbObjects with varying field-name sets across three type_ids, then asserts the aggregation
returns the distinct, order-independent field-name sets per type (deduplicated via $sortArray +
$addToSet), an empty set for objects with no fields, and nothing for a type with no objects
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject, CmdbObjectFieldKey
# -------------------------------------------------------------------------------------------------------------------- #

MIXED_TYPE_ID: int = 9401
EMPTY_FIELDS_TYPE_ID: int = 9402
NO_OBJECTS_TYPE_ID: int = 9403

SEEDED_OBJECT_IDS: list[int] = [9411, 9412, 9413, 9414]


def _object_doc(public_id: int, type_id: int, field_names: list[str]) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc whose fields carry the given names (value/type filled in)."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [
            {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: None,
             CmdbObjectFieldKey.TYPE.value: 'text'}
            for name in field_names
        ],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_objects_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds objects with differing field-name sets, then removes them after the module's tests."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.insert_many([
        # Same set, different field order -> must collapse to one signature
        _object_doc(9411, MIXED_TYPE_ID, ['a', 'b']),
        _object_doc(9412, MIXED_TYPE_ID, ['b', 'a']),
        # A diverging (incomplete) object -> second distinct signature
        _object_doc(9413, MIXED_TYPE_ID, ['a']),
        # An object with no fields -> empty signature
        _object_doc(9414, EMPTY_FIELDS_TYPE_ID, []),
    ])
    yield
    collection.delete_many({'public_id': {'$in': SEEDED_OBJECT_IDS}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


def test_distinct_order_independent_signatures(objects_manager: ObjectsManager) -> None:
    """Objects with the same field names in any order collapse to one set; divergence adds another."""
    result = objects_manager.get_object_field_name_sets_by_type([MIXED_TYPE_ID])

    signatures = {frozenset(field_set) for field_set in result[MIXED_TYPE_ID]}
    assert signatures == {frozenset({'a', 'b'}), frozenset({'a'})}


def test_object_with_no_fields_yields_empty_set(objects_manager: ObjectsManager) -> None:
    """An object carrying no fields contributes a single empty field-name set."""
    result = objects_manager.get_object_field_name_sets_by_type([EMPTY_FIELDS_TYPE_ID])

    assert result[EMPTY_FIELDS_TYPE_ID] == [set()]


def test_type_without_objects_is_absent(objects_manager: ObjectsManager) -> None:
    """A type with no objects does not appear in the mapping."""
    result = objects_manager.get_object_field_name_sets_by_type([NO_OBJECTS_TYPE_ID])

    assert NO_OBJECTS_TYPE_ID not in result


def test_empty_type_id_list_returns_empty_mapping(objects_manager: ObjectsManager) -> None:
    """An empty type_ids list short-circuits to an empty mapping without querying."""
    assert objects_manager.get_object_field_name_sets_by_type([]) == {}
