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
Integration tests for updater_20261019 against a real MongoDB

A category loses the ids of types that no longer exist and keeps the ones of types that do; a non-integer entry is
left alone; no category is deleted; a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261019 import Update20261019
from cmdb.models.category_model import CmdbCategory
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

LIVING_TYPE_ID: int = 96191
DELETED_TYPE_ID: int = 96192
SECOND_DELETED_TYPE_ID: int = 96193
JUNK_ENTRY: str = 'not-a-type-id'

MIXED_CATEGORY_ID: int = 96111
ORPHAN_ONLY_CATEGORY_ID: int = 96112
LIVING_CATEGORY_ID: int = 96113
CATEGORY_IDS: list[int] = [MIXED_CATEGORY_ID, ORPHAN_ONLY_CATEGORY_ID, LIVING_CATEGORY_ID]


def _category(public_id: int, types: list[Any]) -> dict[str, Any]:
    """A stored category document"""
    return {'public_id': public_id, 'name': f'upd-{public_id}', 'label': f'Upd {public_id}', 'parent': None,
            'meta': {'icon': '', 'order': 0}, 'types': types}


@pytest.fixture(name='categories')
def fixture_categories(database_manager: MongoDatabaseManager, database_name: str):
    """One living type and three categories listing it and two deleted ones; purged before and after"""
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        categories.delete_many({'public_id': {'$in': CATEGORY_IDS}})
        types.delete_many({'public_id': {'$in': [LIVING_TYPE_ID, DELETED_TYPE_ID, SECOND_DELETED_TYPE_ID]}})

    _purge()
    types.insert_one({'public_id': LIVING_TYPE_ID, 'name': f'upd-type-{LIVING_TYPE_ID}'})
    categories.insert_many([
        _category(MIXED_CATEGORY_ID, [LIVING_TYPE_ID, DELETED_TYPE_ID, JUNK_ENTRY, SECOND_DELETED_TYPE_ID]),
        _category(ORPHAN_ONLY_CATEGORY_ID, [DELETED_TYPE_ID]),
        _category(LIVING_CATEGORY_ID, [LIVING_TYPE_ID]),
    ])

    yield categories

    _purge()


def _types(categories: Any) -> dict[int, list[Any]]:
    """category id -> its stored types"""
    return {document['public_id']: document['types']
            for document in categories.find({'public_id': {'$in': CATEGORY_IDS}})}


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261019(database_manager, database_name).start_update()


def test_the_deleted_types_leave_the_categories(categories, database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
    """The living type and the junk entry stay; every category stays"""
    _run(database_manager, database_name)

    assert _types(categories) == {
        MIXED_CATEGORY_ID: [LIVING_TYPE_ID, JUNK_ENTRY],
        ORPHAN_ONLY_CATEGORY_ID: [],
        LIVING_CATEGORY_ID: [LIVING_TYPE_ID],
    }


def test_a_second_run_changes_nothing(categories, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    first = _types(categories)

    _run(database_manager, database_name)

    assert _types(categories) == first
