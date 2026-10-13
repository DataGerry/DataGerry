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
Unit tests for cmdb.framework.configuration_transfer.reset_runner

Pure tests: no Mongo, no Flask. What is pinned here: a plain target is one delete by its criteria followed by its
counter reset (none without a counter), a GridFS target is deleted in bounded rounds - each round's chunks before
its file documents, until a read finds nothing - and the run walks the targets in order, reports the count per
collection and stops at the first failure
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.framework.configuration_transfer import RESET_TARGETS, ResetTarget, clear_target, run_reset
from cmdb.framework.configuration_transfer.reset_runner import MONGO_ID_KEY, delete_gridfs_target
from cmdb.framework.media_library.media_file_keys import GRIDFS_CHUNKS_SUFFIX, GRIDFS_CHUNK_FILE_KEY
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

PLAIN: ResetTarget = ResetTarget('plain.collection', {'kind': 'plain'}, 'plain.counter')
UNCOUNTED: ResetTarget = ResetTarget('uncounted.collection', {'kind': 'uncounted'})
BUCKET: str = 'bucket'
GRIDFS: ResetTarget = ResetTarget(f'{BUCKET}.files', {'kind': 'attached'}, gridfs_bucket=BUCKET)
CHUNKS: str = f'{BUCKET}{GRIDFS_CHUNKS_SUFFIX}'
PLAIN_DELETED: int = 7
UNCOUNTED_DELETED: int = 3


def _deleting_manager(deleted: dict[str, int]) -> MagicMock:
    """A manager whose cross-collection delete answers a deleted count per collection"""
    manager: MagicMock = MagicMock()
    manager.delete_many_from_other_collection.side_effect = \
        lambda collection, criteria: MagicMock(deleted_count=deleted.get(collection, 0))

    return manager


def _rounds(*rounds: list[str]) -> MagicMock:
    """A manager whose file reads answer the given rounds of file ids, then nothing"""
    manager: MagicMock = _deleting_manager({})
    manager.get_many_from_other_collection.side_effect = [[{MONGO_ID_KEY: file_id} for file_id in ids]
                                                          for ids in (*rounds, [])]
    manager.delete_many_from_other_collection.side_effect = \
        lambda collection, criteria: MagicMock(deleted_count=len(criteria[MONGO_ID_KEY]['$in'])
                                               if collection == GRIDFS.collection else 0)

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     plain targets                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_plain_target_is_deleted_by_its_criteria_then_counted_back() -> None:
    """One delete by the target's criteria, then the counter set back from the same collection"""
    manager: MagicMock = _deleting_manager({PLAIN.collection: PLAIN_DELETED})

    assert clear_target(manager, PLAIN) == PLAIN_DELETED

    assert manager.mock_calls == [
        call.delete_many_from_other_collection(PLAIN.collection, PLAIN.criteria),
        call.reset_public_id_counter_of(PLAIN.collection, PLAIN.counter),
    ]


def test_a_target_without_a_counter_leaves_the_counters_alone() -> None:
    """No counter -> no counter reset"""
    manager: MagicMock = _deleting_manager({UNCOUNTED.collection: UNCOUNTED_DELETED})

    assert clear_target(manager, UNCOUNTED) == UNCOUNTED_DELETED
    manager.reset_public_id_counter_of.assert_not_called()


def test_the_criteria_handed_to_the_delete_are_a_copy() -> None:
    """A delete that changes its filter does not change the reset list"""
    manager: MagicMock = MagicMock()
    manager.delete_many_from_other_collection.side_effect = lambda collection, criteria: criteria.clear() or \
        MagicMock(deleted_count=0)

    clear_target(manager, PLAIN)

    assert PLAIN.criteria == {'kind': 'plain'}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    GridFS targets                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_gridfs_target_deletes_chunks_before_files_per_round() -> None:
    """Each round: read a bounded batch of ids, delete their chunks, then their file documents"""
    manager: MagicMock = _rounds(['a', 'b'], ['c'])

    assert delete_gridfs_target(manager, GRIDFS, batch_size=2) == 3

    read: call = call.get_many_from_other_collection(GRIDFS.collection, direction=1, limit=2,
                                                     projection={MONGO_ID_KEY: 1}, criteria=GRIDFS.criteria)
    assert manager.mock_calls == [
        read,
        call.delete_many_from_other_collection(CHUNKS, {GRIDFS_CHUNK_FILE_KEY: {'$in': ['a', 'b']}}),
        call.delete_many_from_other_collection(GRIDFS.collection, {MONGO_ID_KEY: {'$in': ['a', 'b']}}),
        read,
        call.delete_many_from_other_collection(CHUNKS, {GRIDFS_CHUNK_FILE_KEY: {'$in': ['c']}}),
        call.delete_many_from_other_collection(GRIDFS.collection, {MONGO_ID_KEY: {'$in': ['c']}}),
        read,
    ]


def test_a_gridfs_target_with_nothing_attached_deletes_nothing() -> None:
    """The first read is empty -> no delete at all, 0 deleted"""
    manager: MagicMock = _rounds()

    assert delete_gridfs_target(manager, GRIDFS) == 0
    manager.delete_many_from_other_collection.assert_not_called()


def test_clear_target_routes_a_gridfs_target_through_gridfs_and_keeps_its_counter() -> None:
    """A GridFS target is deleted in rounds and, without a counter, sets nothing back"""
    manager: MagicMock = _rounds(['a'])

    assert clear_target(manager, GRIDFS) == 1
    manager.reset_public_id_counter_of.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        the run                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_run_reset_reports_the_count_per_collection_in_order() -> None:
    """Every target cleared, in order, its count under its collection"""
    manager: MagicMock = _deleting_manager({PLAIN.collection: PLAIN_DELETED, UNCOUNTED.collection: UNCOUNTED_DELETED})

    report: dict[str, int] = run_reset(manager, (UNCOUNTED, PLAIN))

    assert list(report.items()) == [(UNCOUNTED.collection, UNCOUNTED_DELETED), (PLAIN.collection, PLAIN_DELETED)]


def test_run_reset_stops_at_the_first_failure() -> None:
    """A failing target raises; the targets after it are not touched"""
    manager: MagicMock = MagicMock()
    failure: BaseManagerDeleteError = BaseManagerDeleteError('boom')
    manager.delete_many_from_other_collection.side_effect = failure

    with pytest.raises(BaseManagerDeleteError) as exc_info:
        run_reset(manager, (PLAIN, UNCOUNTED))

    assert exc_info.value is failure
    assert [entry.args[0] for entry in manager.delete_many_from_other_collection.call_args_list] == [PLAIN.collection]
    manager.reset_public_id_counter_of.assert_not_called()


def test_run_reset_walks_the_reset_list_by_default() -> None:
    """Without targets every reset target is cleared, in list order"""
    manager: MagicMock = _deleting_manager({})
    manager.get_many_from_other_collection.return_value = []

    report: dict[str, Any] = run_reset(manager)

    assert list(report) == [target.collection for target in RESET_TARGETS]
