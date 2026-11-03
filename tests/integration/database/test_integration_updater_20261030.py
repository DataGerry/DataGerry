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
Integration tests for cmdb.database.updater.versions.updater_20261030 against a real MongoDB

Seeds two Types carrying one SpecialType (one with objects) and ordinary Types storing null, with the special_type
index dropped, as on a database the rule has not reached yet; runs the migration and asserts:
  - a duplicate is reported with both Types' ids, names and object counts, nothing is written, the index is not built
  - once the duplicate is gone, a run builds the partial unique index: many ordinary Types may store null or '', a
    second Type of a SpecialType is refused
  - a second run changes nothing
"""
import logging
from typing import Any, Iterator

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions import updater_20261030 as module
from cmdb.database.updater.versions.updater_20261030 import Update20261030
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

NAME: str = TypeSchemaKey.NAME.value
PUBLIC_ID: str = TypeSchemaKey.PUBLIC_ID.value
SPECIAL: str = TypeSchemaKey.SPECIAL_TYPE.value
INDEX: str = module.SPECIAL_TYPE_INDEX
FIRST_ID: int = 98901
SECOND_ID: int = 98902
ORDINARY_IDS: list[int] = [98903, 98904]
LATE_ID: int = 98905
EMPTY_IDS: list[int] = [98906, 98907]
OBJECT_IDS: list[int] = [98911, 98912, 98913]
CABLE: str = SpecialType.CABLE.value
SEEDED_IDS: list[int] = [FIRST_ID, SECOND_ID, LATE_ID, *ORDINARY_IDS, *EMPTY_IDS]


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two CABLE Types (the second with objects) and two ordinary ones, without the special_type index"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({PUBLIC_ID: {'$in': SEEDED_IDS}})
        objects.delete_many({PUBLIC_ID: {'$in': OBJECT_IDS}})

    _purge()
    # The collection is the session's: a CABLE Type another module left behind would be a real duplicate here
    leftovers: list[Any] = [row[NAME] for row in collection.find({SPECIAL: CABLE}, {NAME: 1})]
    assert not leftovers, f"another module left CABLE types in the session: {leftovers}"
    had_index: bool = INDEX in collection.index_information()

    if had_index:
        collection.drop_index(INDEX)

    collection.insert_many(
        [{PUBLIC_ID: FIRST_ID, NAME: 'upd-cable-a', SPECIAL: CABLE},
         {PUBLIC_ID: SECOND_ID, NAME: 'upd-cable-b', SPECIAL: CABLE}]
        + [{PUBLIC_ID: type_id, NAME: f'upd-plain-{type_id}', SPECIAL: None} for type_id in ORDINARY_IDS])
    objects.insert_many([{PUBLIC_ID: object_id, 'type_id': SECOND_ID} for object_id in OBJECT_IDS])
    yield collection
    _purge()

    # Leave the index as the session had it
    if not had_index and INDEX in collection.index_information():
        collection.drop_index(INDEX)


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration."""
    Update20261030(database_manager, database_name).start_update()


def _markers(types: Any) -> dict[int, Any]:
    """The seeded Types' markers by public_id"""
    return {row[PUBLIC_ID]: row[SPECIAL] for row in types.find({PUBLIC_ID: {'$in': SEEDED_IDS}})}


def test_a_duplicate_is_reported_and_nothing_written(database_manager, database_name, types,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    """Both Types named with their object counts; markers and index untouched"""
    before: dict[int, Any] = _markers(types)

    with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
        _run(database_manager, database_name)

    report: str = ' '.join(record.getMessage() for record in caplog.records)
    assert f"type {FIRST_ID} 'upd-cable-a' (0 objects)" in report
    assert f"type {SECOND_ID} 'upd-cable-b' ({len(OBJECT_IDS)} objects)" in report
    assert _markers(types) == before
    assert INDEX not in types.index_information()


def test_once_resolved_the_partial_index_is_built(database_manager, database_name, types) -> None:
    """Null and '' are left out; a second SpecialType holder is refused"""
    types.delete_one({PUBLIC_ID: SECOND_ID})

    _run(database_manager, database_name)

    assert types.index_information()[INDEX].get('unique') is True
    types.insert_one({PUBLIC_ID: LATE_ID, NAME: 'upd-plain-late', SPECIAL: None})
    types.insert_many([{PUBLIC_ID: type_id, NAME: f'upd-empty-{type_id}', SPECIAL: ''} for type_id in EMPTY_IDS])
    with pytest.raises(DuplicateKeyError):
        types.insert_one({PUBLIC_ID: SECOND_ID, NAME: 'upd-cable-late', SPECIAL: CABLE})


def test_a_second_run_changes_nothing(database_manager, database_name, types) -> None:
    """Re-run safe"""
    types.delete_one({PUBLIC_ID: SECOND_ID})
    _run(database_manager, database_name)
    before: dict[str, Any] = types.index_information()[INDEX]

    _run(database_manager, database_name)

    assert types.index_information()[INDEX] == before
