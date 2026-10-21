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
Integration tests for cmdb.database.updater.versions.updater_20261010 against a real MongoDB

Seeds two types and categories holding a deleted type id, a junk entry, only real ids, and no types at all, runs the
migration, and asserts:

  - every entry that names no stored type is pulled; the real ids stay, in their order
  - a category holding only real ids, or none, is left alone
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261010 import Update20261010
from cmdb.models.category_model import CmdbCategory
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_A: int = 98501
TYPE_B: int = 98502
DELETED_TYPE: int = 98509

STALE_ID: int = 98511
JUNK_ID: int = 98512
CLEAN_ID: int = 98513
EMPTY_ID: int = 98514
ALL_CATEGORY_IDS: list[int] = [STALE_ID, JUNK_ID, CLEAN_ID, EMPTY_ID]

SEEDED_TYPES: dict[int, list[Any]] = {
    STALE_ID: [TYPE_B, DELETED_TYPE, TYPE_A],
    JUNK_ID: [{'a': 1}, TYPE_A, True],
    CLEAN_ID: [TYPE_B],
    EMPTY_ID: [],
}


@pytest.fixture(name='categories', autouse=True)
def fixture_categories(database_manager: MongoDatabaseManager, database_name: str):
    """The two types and the seeded categories - purged after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [TYPE_A, TYPE_B]}})
        categories.delete_many({'public_id': {'$in': ALL_CATEGORY_IDS}})

    _purge()
    types.insert_many([make_type_doc(TYPE_A, 'updater-20261010-a'), make_type_doc(TYPE_B, 'updater-20261010-b')])
    categories.insert_many([
        {'public_id': public_id, 'name': f'updater-20261010-{public_id}', 'parent': None, 'types': type_ids}
        for public_id, type_ids in SEEDED_TYPES.items()
    ])
    yield categories
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261010(database_manager, database_name).start_update()


def _stored_types(categories: Any) -> dict[int, list[Any]]:
    """The stored types of each seeded category"""
    return {stored['public_id']: stored['types']
            for stored in categories.find({'public_id': {'$in': ALL_CATEGORY_IDS}})}


def test_every_entry_naming_no_type_is_pulled(categories, database_manager, database_name) -> None:
    """Deleted ids and junk go; real ids stay in order; clean and empty categories untouched"""
    _run(database_manager, database_name)

    assert _stored_types(categories) == {
        STALE_ID: [TYPE_B, TYPE_A], JUNK_ID: [TYPE_A], CLEAN_ID: [TYPE_B], EMPTY_ID: [],
    }


def test_nothing_else_of_a_category_changes(categories, database_manager, database_name) -> None:
    """Only the entries are pulled"""
    before = categories.find_one({'public_id': STALE_ID}, {'_id': 0})

    _run(database_manager, database_name)

    after = categories.find_one({'public_id': STALE_ID}, {'_id': 0})
    assert after == {**before, 'types': [TYPE_B, TYPE_A]}


def test_a_second_run_changes_nothing(categories, database_manager, database_name) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    first = _stored_types(categories)

    _run(database_manager, database_name)

    assert _stored_types(categories) == first
