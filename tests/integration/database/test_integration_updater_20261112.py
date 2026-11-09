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
Integration test for cmdb.database.updater.versions.updater_20261112 against a real MongoDB

Seeds an object whose section counter sits below its row ids (row id 0 included, as stored ones hold), one whose
second section has no counter, one in line and one holding a row id two rows share - runs the migration twice and
reads them back: the counters are raised, nothing else changes, the shared id is left (reported only), the second run
a no-op
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261112 import Update20261112
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

STALE: int = 946101
NO_COUNTER: int = 946102
IN_LINE: int = 946103
SHARED_ID: int = 946104
SEEDED: list[int] = [STALE, NO_COUNTER, IN_LINE, SHARED_ID]


def _rows(*row_ids: int) -> list[dict[str, Any]]:
    """Rows holding the given ids"""
    return [{'multi_data_id': row_id, 'data': [{'name': 'nic', 'value': f'eth{row_id}'}]} for row_id in row_ids]


def _object(public_id: int, *sections: dict[str, Any]) -> dict[str, Any]:
    """An object of no particular type holding the given sections"""
    return {'public_id': public_id, 'type_id': 1, 'fields': [], 'multi_data_sections': list(sections)}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded objects, removed afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': SEEDED}})
    objects.insert_many([
        _object(STALE, {'section_id': 'nics', 'highest_id': 0, 'values': _rows(0, 1)}),
        _object(NO_COUNTER, {'section_id': 'nics', 'highest_id': 1, 'values': _rows(1)},
                {'section_id': 'disks', 'values': _rows(4)}),
        _object(IN_LINE, {'section_id': 'nics', 'highest_id': 7, 'values': _rows(2)}),
        _object(SHARED_ID, {'section_id': 'nics', 'highest_id': 2, 'values': _rows(2, 2)}),
    ])

    yield objects

    objects.delete_many({'public_id': {'$in': SEEDED}})


def _sections(objects: Any) -> dict[int, Any]:
    """Every seeded object's sections"""
    return {document['public_id']: document['multi_data_sections']
            for document in objects.find({'public_id': {'$in': SEEDED}}, {'_id': 0})}


def test_the_migration_raises_the_counters_and_is_rerun_safe(database_manager: MongoDatabaseManager,
                                                            database_name: str, objects: Any) -> None:
    """Counters raised, rows untouched, the shared id left, the second run a no-op"""
    before: dict[int, Any] = _sections(objects)

    Update20261112(database_manager, database_name).start_update()
    after: dict[int, Any] = _sections(objects)

    assert after[STALE] == [{**before[STALE][0], 'highest_id': 1}]
    assert after[NO_COUNTER] == [before[NO_COUNTER][0], {**before[NO_COUNTER][1], 'highest_id': 4}]
    assert after[IN_LINE] == before[IN_LINE]
    assert after[SHARED_ID] == before[SHARED_ID]

    Update20261112(database_manager, database_name).start_update()

    assert _sections(objects) == after
