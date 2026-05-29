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
Integration tests for sorting by a value inside the ``fields`` array

Real-MongoDB exercise of BaseQueryBuilder's ``fields.<name>`` sort branch: seeds
five CmdbObject documents whose ``Name`` field values cover lowercase and uppercase
starts (so the assertion would fail with default MongoDB binary collation), runs
``ObjectsManager.iterate`` ascending and descending, and verifies the returned
``public_id`` order matches the case-insensitive expectation
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

NAME_FIELD: str = 'name-field'
SORT_KEY: str = f'fields.{NAME_FIELD}'
TYPE_ID: int = 9001
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
SEED_OBJECTS: list[tuple[int, str]] = [
    (9101, 'Umbrella'),
    (9102, 'becon'),
    (9103, 'asdf'),
    (9104, 'Comapny11'),
    (9105, 'Company1'),
]
EXPECTED_ASCENDING_IDS: list[int] = [9103, 9102, 9104, 9105, 9101]
EXPECTED_DESCENDING_IDS: list[int] = [9101, 9105, 9104, 9102, 9103]
ASCENDING: int = 1
DESCENDING: int = -1


def _seed_doc(public_id: int, name_value: str) -> dict[str, Any]:
    """Builds a minimal but CmdbObject-compatible doc with a single sortable text field."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': name_value}],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Inserts the seed docs before the tests in this module and removes them after."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.insert_many([_seed_doc(public_id, value) for public_id, value in SEED_OBJECTS])
    yield
    collection.delete_many({'public_id': {'$in': [public_id for public_id, _ in SEED_OBJECTS]}})


class TestObjectsSortByFieldValue:
    """``ObjectsManager.iterate`` with ``sort=fields.<name>`` returns docs ordered by the field value."""

    @pytest.mark.parametrize(
        'order,expected_ids',
        [
            (ASCENDING, EXPECTED_ASCENDING_IDS),
            (DESCENDING, EXPECTED_DESCENDING_IDS),
        ],
    )
    def test_iterate_orders_results_by_field_value(
        self,
        database_manager: MongoDatabaseManager,
        order: int,
        expected_ids: list[int],
    ) -> None:
        """The aggregation projects the field's value out of the ``fields`` array and sorts on it."""
        manager = ObjectsManager(database_manager)
        params = BuilderParameters(
            criteria=[{'$match': {'type_id': TYPE_ID}}],
            sort=SORT_KEY,
            order=order,
        )

        result = manager.iterate(params)

        returned_ids = [doc.public_id for doc in result.results]
        assert returned_ids == expected_ids
