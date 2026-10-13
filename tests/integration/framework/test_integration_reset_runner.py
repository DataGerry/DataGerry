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
Integration tests of running a configuration reset against a real MongoDB

On a scratch database of its own: every target is emptied and what the reset keeps is still there afterwards, an
attached file goes with its chunks while an unattached one keeps its own, the counters come back DOWN to the highest
id still stored (0, or the kept root / predefined id) while the media library's counter is left alone, and a second
run deletes nothing and leaves the same state - the re-run safety the reset relies on
"""
from typing import Any, Iterator

import pytest
from bson import ObjectId

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.configuration_transfer import RESET_TARGETS, find_non_empty_targets, run_reset
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_CHUNKS_SUFFIX,
    GRIDFS_CHUNK_FILE_KEY,
    GRIDFS_FILES_SUFFIX,
    MediaFileKey,
    MediaFileMetadataKey,
    OBJECT_REFERENCE_TYPE,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-reset-runner'
PUBLIC_ID_KEY: str = 'public_id'
MONGO_ID_KEY: str = '_id'
COUNTER_KEY: str = 'counter'
PREDEFINED_KEY: str = SectionTemplateKey.PREDEFINED.value
MEDIA_FILES: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
MEDIA_CHUNKS: str = f'{MediaFile.COLLECTION}{GRIDFS_CHUNKS_SUFFIX}'

LEFT_OVER_IDS: tuple[int, int] = (2, 3)
STALE_COUNTER: int = 50
MEDIA_COUNTER: int = 9
KEPT_PREDEFINED_ID: int = 1
CHUNKS_PER_FILE: int = 2

ATTACHED_FILE_IDS: tuple[ObjectId, ObjectId] = (ObjectId(), ObjectId())
KEPT_FILE_ID: ObjectId = ObjectId()


def _media_file(file_id: ObjectId, public_id: int, reference_type: str | None) -> dict[str, Any]:
    """A GridFS file document"""
    return {MONGO_ID_KEY: file_id, PUBLIC_ID_KEY: public_id,
            MediaFileKey.METADATA.value: {MediaFileMetadataKey.REFERENCE_TYPE.value: reference_type}}


def _chunks(file_id: ObjectId) -> list[dict[str, Any]]:
    """The chunk documents of one file"""
    return [{GRIDFS_CHUNK_FILE_KEY: file_id, 'n': index} for index in range(CHUNKS_PER_FILE)]


# What the reset keeps, per collection
KEPT: dict[str, list[dict[str, Any]]] = {
    CmdbLocation.COLLECTION: [{PUBLIC_ID_KEY: RootLocationDefault.PUBLIC_ID}],
    CmdbSectionTemplate.COLLECTION: [{PUBLIC_ID_KEY: KEPT_PREDEFINED_ID, PREDEFINED_KEY: True}],
    CmdbReportCategory.COLLECTION: [{PUBLIC_ID_KEY: KEPT_PREDEFINED_ID, PREDEFINED_KEY: True}],
    MEDIA_FILES: [_media_file(KEPT_FILE_ID, 1, None)],
    MEDIA_CHUNKS: _chunks(KEPT_FILE_ID),
    CmdbUser.COLLECTION: [{PUBLIC_ID_KEY: CmdbUser.ADMIN_PUBLIC_ID}],
}

# The highest id a counter must come back down to
EXPECTED_COUNTERS: dict[str, int] = {
    CmdbType.COLLECTION: 0,
    CmdbLocation.COLLECTION: RootLocationDefault.PUBLIC_ID,
    CmdbSectionTemplate.COLLECTION: KEPT_PREDEFINED_ID,
    CmdbReportCategory.COLLECTION: KEPT_PREDEFINED_ID,
}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A seeded database of this module's own: two left-overs per target, the kept documents, stale counters"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    database = client[scratch]

    for target in RESET_TARGETS:
        if target.gridfs_bucket:
            database[target.collection].insert_many([
                _media_file(file_id, public_id, OBJECT_REFERENCE_TYPE)
                for file_id, public_id in zip(ATTACHED_FILE_IDS, LEFT_OVER_IDS)
            ])
            database[MEDIA_CHUNKS].insert_many([chunk for file_id in ATTACHED_FILE_IDS for chunk in _chunks(file_id)])
        else:
            database[target.collection].insert_many([{PUBLIC_ID_KEY: public_id} for public_id in LEFT_OVER_IDS])
            database[PUBLIC_ID_COUNTER_COLLECTION].insert_one({MONGO_ID_KEY: target.counter,
                                                               COUNTER_KEY: STALE_COUNTER})

    for collection, rows in KEPT.items():
        database[collection].insert_many(rows)

    database[PUBLIC_ID_COUNTER_COLLECTION].insert_one({MONGO_ID_KEY: MediaFile.COLLECTION, COUNTER_KEY: MEDIA_COUNTER})

    yield scratch

    client.drop_database(scratch)


def _counter(database_manager: MongoDatabaseManager, scratch: str, counter_id: str) -> int:
    """The stored value of one counter"""
    return database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, scratch).find_one(
        {MONGO_ID_KEY: counter_id}
    )[COUNTER_KEY]


def _count(database_manager: MongoDatabaseManager, scratch: str, collection: str) -> int:
    """The number of documents in one collection"""
    return database_manager.get_collection(collection, scratch).count_documents({})


def test_every_target_is_emptied_and_reported(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Two documents deleted per target, nothing left over afterwards"""
    manager: BaseManager = BaseManager(CmdbType.COLLECTION, database_manager, scratch)

    report: dict[str, int] = run_reset(manager)

    assert report == {target.collection: len(LEFT_OVER_IDS) for target in RESET_TARGETS}
    assert not find_non_empty_targets(manager)


def test_what_the_reset_keeps_is_still_there(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Root location, predefined template and category, the unattached file with its chunks, the admin"""
    run_reset(BaseManager(CmdbType.COLLECTION, database_manager, scratch))

    for collection, rows in KEPT.items():
        assert _count(database_manager, scratch, collection) == len(rows), collection


def test_an_attached_file_goes_with_its_chunks(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """No chunk of a deleted file is left; the kept file's chunks are untouched"""
    run_reset(BaseManager(CmdbType.COLLECTION, database_manager, scratch))
    chunks = database_manager.get_collection(MEDIA_CHUNKS, scratch)

    assert chunks.count_documents({GRIDFS_CHUNK_FILE_KEY: {'$in': list(ATTACHED_FILE_IDS)}}) == 0
    assert chunks.count_documents({GRIDFS_CHUNK_FILE_KEY: KEPT_FILE_ID}) == CHUNKS_PER_FILE


def test_counters_come_back_down_to_what_is_kept(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Every plain target's counter is the highest id still stored; the media counter keeps its value"""
    run_reset(BaseManager(CmdbType.COLLECTION, database_manager, scratch))

    for collection, expected in EXPECTED_COUNTERS.items():
        assert _counter(database_manager, scratch, collection) == expected, collection

    assert all(_counter(database_manager, scratch, target.counter) == EXPECTED_COUNTERS.get(target.collection, 0)
               for target in RESET_TARGETS if target.counter)
    assert _counter(database_manager, scratch, MediaFile.COLLECTION) == MEDIA_COUNTER


def test_a_second_run_deletes_nothing_and_changes_nothing(database_manager: MongoDatabaseManager,
                                                          scratch: str) -> None:
    """Re-run safe: the second run reports zeros and the kept state and counters stay as the first run left them"""
    manager: BaseManager = BaseManager(CmdbType.COLLECTION, database_manager, scratch)
    run_reset(manager)
    counters_after_first: list[dict[str, Any]] = list(
        database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, scratch).find({}, sort=[(MONGO_ID_KEY, 1)])
    )

    assert set(run_reset(manager).values()) == {0}
    assert list(database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, scratch).find(
        {}, sort=[(MONGO_ID_KEY, 1)])) == counters_after_first


def test_a_run_finishes_what_a_failed_run_left(database_manager: MongoDatabaseManager, scratch: str,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that fails at the types stops there - the types survive; running again finishes the reset"""
    manager: BaseManager = BaseManager(CmdbType.COLLECTION, database_manager, scratch)
    original = BaseManager.delete_many_from_other_collection

    def _failing_on_types(self, collection: str, filter_query: dict[str, Any]):
        if collection == CmdbType.COLLECTION:
            raise RuntimeError('types unavailable')

        return original(self, collection, filter_query)

    monkeypatch.setattr(BaseManager, 'delete_many_from_other_collection', _failing_on_types)

    with pytest.raises(RuntimeError):
        run_reset(manager)

    assert _count(database_manager, scratch, CmdbType.COLLECTION) == len(LEFT_OVER_IDS)

    monkeypatch.undo()
    run_reset(manager)

    assert not find_non_empty_targets(manager)
