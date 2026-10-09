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
Unit tests for cmdb.database.updater.versions.updater_20261005

The migration stamps every CmdbObjectLog with the type of the object it records: from the live object (one
aggregation that ``$merge``s the type back), else from the log's own snapshot. Its run against real collections -
both sources, the null stamp, the double run - is its own integration test; this module owns the pipeline shape,
the snapshot reading, the batching and the failure tail
"""
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261005
from cmdb.database.updater.versions.updater_20261005 import (
    UNSTAMPED_LOG_CRITERIA,
    Update20261005,
    build_live_object_stamp_pipeline,
    build_snapshot_stamp_operation,
    type_id_from_render_state,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261005
DATABASE_NAME: str = 'cmdb-unit'
SNAPSHOT_TYPE_ID: int = 31


def _snapshot(type_information: Any) -> bytes:
    """A render_state the way the writer stores it"""
    return json.dumps({'object_information': {'object_id': 1}, 'type_information': type_information}).encode('UTF-8')


def _build_stubbed_updater(remaining: list[dict[str, Any]] | None = None) -> Any:
    """The updater with a stubbed database manager; `remaining` is what the snapshot pass finds"""
    updater = Update20261005.__new__(Update20261005)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter(remaining or [])
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater

def test_the_version_and_description_name_the_stamp() -> None:
    """The registry orders by the creation date; the description names the key it writes"""
    updater = _build_stubbed_updater()

    assert updater.creation_date() == CREATION_DATE
    assert "'type_id'" in updater.description()

# --------------------------------------------------- the selection -------------------------------------------------- #

def test_only_unstamped_object_logs_are_selected() -> None:
    """Object logs without the key - a stamped one (value or null) is never visited again"""
    assert UNSTAMPED_LOG_CRITERIA == {'log_type': OBJECT_LOG_TYPE, 'type_id': {'$exists': False}}

# -------------------------------------------------- the live-object pass -------------------------------------------- #

def test_the_live_pass_joins_the_object_and_merges_its_type_back() -> None:
    """match -> lookup -> keep the joined -> project the type -> merge onto the same log"""
    pipeline: list[dict[str, Any]] = build_live_object_stamp_pipeline()

    assert [next(iter(stage)) for stage in pipeline] == ['$match', '$lookup', '$match', '$project', '$merge']
    assert pipeline[0] == {'$match': UNSTAMPED_LOG_CRITERIA}
    assert pipeline[1]['$lookup']['from'] == CmdbObject.COLLECTION
    assert (pipeline[1]['$lookup']['localField'], pipeline[1]['$lookup']['foreignField']) == ('object_id', 'public_id')
    assert pipeline[-1] == {'$merge': {
        'into': CmdbMetaLog.COLLECTION, 'on': '_id', 'whenMatched': 'merge', 'whenNotMatched': 'discard',
    }}


def test_the_live_pass_only_keeps_a_log_whose_object_has_a_numeric_type() -> None:
    """A gone object (empty join) is left for the snapshot pass"""
    assert build_live_object_stamp_pipeline()[2] == {
        '$match': {'logged_object.0.type_id': {'$type': 'number'}},
    }


def test_the_live_pass_writes_only_the_type() -> None:
    """The projection carries _id (the merge key) and the type - nothing else of the log is rewritten"""
    projection: dict[str, Any] = build_live_object_stamp_pipeline()[3]['$project']

    assert set(projection) == {'_id', 'type_id'}

# --------------------------------------------------- the snapshot pass ---------------------------------------------- #

@pytest.mark.parametrize('render_state, expected', [
    (_snapshot({'type_id': SNAPSHOT_TYPE_ID}), SNAPSHOT_TYPE_ID),
    (_snapshot({'type_id': SNAPSHOT_TYPE_ID}).decode('UTF-8'), SNAPSHOT_TYPE_ID),
    (bytearray(_snapshot({'type_id': SNAPSHOT_TYPE_ID})), SNAPSHOT_TYPE_ID),
    (b'not json', None),
    (b'[1, 2]', None),
    (_snapshot(None), None),
    (_snapshot({'type_label': 'x'}), None),
    (_snapshot({'type_id': '31'}), None),
    (_snapshot({'type_id': True}), None),
    (None, None),
    (12, None),
], ids=['bytes', 'text', 'bytearray', 'not-json', 'not-an-object', 'no-type-block', 'no-type-id', 'text-type-id',
        'boolean-type-id', 'missing', 'number'])
def test_the_snapshot_names_its_type_or_none(render_state: Any, expected: int | None) -> None:
    """Only a whole-number type_information.type_id counts - a boolean is no type id"""
    assert type_id_from_render_state(render_state) == expected


def test_a_snapshot_write_repeats_the_selection() -> None:
    """A log stamped meanwhile is not overwritten"""
    operation = build_snapshot_stamp_operation({'_id': 'abc', 'render_state': _snapshot({'type_id': SNAPSHOT_TYPE_ID})})

    assert operation._filter == {'_id': 'abc', **UNSTAMPED_LOG_CRITERIA}  # pylint: disable=protected-access
    assert operation._doc == {'$set': {'type_id': SNAPSHOT_TYPE_ID}}  # pylint: disable=protected-access


def test_an_unreadable_snapshot_stamps_null() -> None:
    """The log leaves with the key, so a second run does not visit it again"""
    operation = build_snapshot_stamp_operation({'_id': 'abc', 'render_state': b'broken'})

    assert operation._doc == {'$set': {'type_id': None}}  # pylint: disable=protected-access

# ---------------------------------------------------- start_update -------------------------------------------------- #

def test_the_live_pass_runs_first_and_is_consumed() -> None:
    """The aggregation runs on the logs collection with the pipeline, then the remaining logs are read"""
    updater = _build_stubbed_updater()

    updater.start_update()

    updater.dbm.aggregate.assert_called_once_with(
        CmdbMetaLog.COLLECTION, DATABASE_NAME, build_live_object_stamp_pipeline(),
    )
    assert updater.dbm.find.call_args.kwargs['filter'] == UNSTAMPED_LOG_CRITERIA
    assert updater.dbm.find.call_args.kwargs['projection'] == {'_id': 1, 'render_state': 1}
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_nothing_left_writes_nothing() -> None:
    """Every log had a live object"""
    updater = _build_stubbed_updater([])

    updater.start_update()

    updater.dbm.bulk_write.assert_not_called()


def test_the_snapshot_pass_writes_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five remaining logs in batches of two: three writes of 2, 2 and 1"""
    monkeypatch.setattr(updater_20261005, 'SNAPSHOT_BATCH_SIZE', 2)
    remaining = [{'_id': index, 'render_state': _snapshot({'type_id': index})} for index in range(5)]
    updater = _build_stubbed_updater(remaining)

    updater.start_update()

    batches = [call.args[2] for call in updater.dbm.bulk_write.call_args_list]
    # pylint: disable-next=protected-access
    stamped = [operation._doc['$set']['type_id'] for batch in batches for operation in batch]

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert stamped == [0, 1, 2, 3, 4]


@pytest.mark.parametrize('failing', ['aggregate', 'find', 'bulk_write'])
def test_a_failure_is_wrapped_with_the_error_itself_and_leaves_the_version(failing: str) -> None:
    """The wrapper carries the exception (args[0] and __cause__); the version is not bumped"""
    updater = _build_stubbed_updater([{'_id': 1, 'render_state': _snapshot({'type_id': 1})}])
    failure = RuntimeError('down')
    getattr(updater.dbm, failing).side_effect = failure

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.args[0] is failure
    assert exc_info.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()
