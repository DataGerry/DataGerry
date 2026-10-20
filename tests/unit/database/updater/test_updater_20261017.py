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
Unit tests for cmdb.database.updater.versions.updater_20261017

The migration takes the ids of deleted CmdbObjects out of the media files attached to them. Its run against a real
database is its own integration test; this module owns the frozen literals, the pipelines, the batching, which ids
count as deleted, the order and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261017 as module
from cmdb.database.updater.versions.updater_20261017 import (
    Update20261017,
    batches,
    detach_update,
    referenced_ids_pipeline,
)
from cmdb.framework.media_library.media_file_keys import (
    MEDIA_FILE_REFERENCE_PATH,
    MEDIA_FILE_REFERENCE_TYPE_PATH,
    OBJECT_REFERENCE_TYPE,
)
from cmdb.manager.media_files_manager import MEDIA_FILES_COLLECTION, build_detach_objects_update
from cmdb.models.object_model import CmdbObject
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261017
DATABASE_NAME: str = 'cmdb-unit'
REFERENCED_IDS: list[int] = [12, 5, 9]
EXISTING_IDS: list[int] = [9]
DELETED_IDS: list[int] = [5, 12]
MODIFIED: int = 4


def _updater(referenced: list[int] | None = None,
             existing: list[int] | None = None) -> tuple[Update20261017, MagicMock]:
    """The migration over a mocked database manager"""
    dbm = MagicMock()
    dbm.aggregate_all.return_value = [{module.REFERENCED_IDS_KEY: referenced}] if referenced is not None else []
    dbm.find.side_effect = lambda *_args, **_kwargs: iter([{'public_id': object_id} for object_id in existing or []])
    dbm.update_many_raw.return_value = MagicMock(modified_count=MODIFIED)
    updater = Update20261017.__new__(Update20261017)
    updater.dbm = dbm
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.MEDIA_FILES_COLLECTION, MEDIA_FILES_COLLECTION),
    (module.OBJECTS_COLLECTION, CmdbObject.COLLECTION),
    (module.REFERENCE_PATH, MEDIA_FILE_REFERENCE_PATH),
    (module.REFERENCE_TYPE_PATH, MEDIA_FILE_REFERENCE_TYPE_PATH),
    (module.OBJECT_REFERENCE_TYPE, OBJECT_REFERENCE_TYPE),
], ids=['files', 'objects', 'reference', 'reference-type', 'object-kind'])
def test_the_frozen_literals_still_match_the_model(frozen: Any, live: Any) -> None:
    """Frozen on purpose; a drift would mean the migration no longer touches what the application stores"""
    assert frozen == live


def test_the_detach_update_is_the_one_the_object_delete_runs() -> None:
    """The migration does to old orphans exactly what the delete now does"""
    assert detach_update(DELETED_IDS) == build_detach_objects_update(DELETED_IDS)


def test_the_referenced_ids_pipeline() -> None:
    """Object attachments only, each reference as a list, integer entries only, every id once"""
    assert referenced_ids_pipeline() == [
        {'$match': {'metadata.reference_type': 'object', 'metadata.reference': {'$ne': None}}},
        {'$project': {'_id': 0, 'references': {'$cond': [
            {'$isArray': '$metadata.reference'}, '$metadata.reference', ['$metadata.reference'],
        ]}}},
        {'$unwind': '$references'},
        {'$match': {'references': {'$type': ['int', 'long']}}},
        {'$group': {'_id': None, 'ids': {'$addToSet': '$references'}}},
    ]


@pytest.mark.parametrize('ids, size, expected', [
    ([], 2, []), ([1], 2, [[1]]), ([1, 2], 2, [[1, 2]]), ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]]),
], ids=['none', 'one', 'exact', 'remainder'])
def test_batches(ids: list[int], size: int, expected: list[list[int]]) -> None:
    """Consecutive, in order, none larger than the size"""
    assert batches(ids, size) == expected


class TestFindDeletedObjectIds:
    """A referenced id whose object no longer exists"""

    def test_answers_the_referenced_ids_without_an_object_ascending(self) -> None:
        """Existence read in one projected batch"""
        updater, dbm = _updater(REFERENCED_IDS, EXISTING_IDS)

        assert updater.find_deleted_object_ids() == DELETED_IDS
        dbm.find.assert_called_once_with(
            module.OBJECTS_COLLECTION, DATABASE_NAME, {'public_id': {'$in': sorted(REFERENCED_IDS)}},
            projection={'public_id': 1, '_id': 0},
        )

    def test_nothing_referenced_reads_no_object(self) -> None:
        """The aggregation answered no group"""
        updater, dbm = _updater(None)

        assert not updater.find_deleted_object_ids()
        dbm.find.assert_not_called()

    def test_the_existence_read_is_batched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One read per batch"""
        monkeypatch.setattr(module, 'ID_BATCH_SIZE', 2)
        updater, dbm = _updater(REFERENCED_IDS, [])

        assert updater.find_deleted_object_ids() == sorted(REFERENCED_IDS)
        assert dbm.find.call_count == 2


class TestDetach:
    """One update per batch of ids, on object attachments only"""

    def test_each_batch_is_one_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The counts summed"""
        monkeypatch.setattr(module, 'ID_BATCH_SIZE', 1)
        updater, dbm = _updater()

        assert updater.detach(DELETED_IDS) == MODIFIED * len(DELETED_IDS)
        assert dbm.update_many_raw.call_args_list == [call(
            module.MEDIA_FILES_COLLECTION, DATABASE_NAME,
            {'metadata.reference_type': 'object', 'metadata.reference': {'$in': [object_id]}},
            detach_update([object_id]),
        ) for object_id in DELETED_IDS]

    def test_no_ids_update_nothing(self) -> None:
        """Nothing to take out"""
        updater, dbm = _updater()

        assert updater.detach([]) == 0
        dbm.update_many_raw.assert_not_called()


class TestStartUpdate:
    """Find, detach, then bump the version"""

    def test_the_version_is_bumped_after_the_detach(self) -> None:
        """Only once everything went through"""
        updater, dbm = _updater(REFERENCED_IDS, EXISTING_IDS)

        updater.start_update()

        dbm.update_many_raw.assert_called_once()
        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_a_failure_is_raised_carrying_the_error_and_the_version_stays(self) -> None:
        """The exception itself, not its text"""
        updater, dbm = _updater(REFERENCED_IDS, EXISTING_IDS)
        failure = RuntimeError('db')
        dbm.update_many_raw.side_effect = failure

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        assert caught.value.args[0] is failure
        updater.increase_updater_version.assert_not_called()

    def test_creation_date_and_description(self) -> None:
        """The registered version"""
        updater, _ = _updater()

        assert updater.creation_date() == CREATION_DATE
        assert updater.description()
