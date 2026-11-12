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
Unit tests for cmdb.database.updater.versions.updater_20261115

The migration stamps every CmdbObjectRelationLog with the types of its two objects: from the live object, else from
the object's own logs, else null. Its run against real collections - every source, the null stamp, the double run -
is its own integration test; this module owns the selection, the object-id collection, the pipeline shape, the
write shape, the batching and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261115
from cmdb.database.updater.versions.updater_20261115 import (
    UNSTAMPED_LOG_CRITERIA,
    Update20261115,
    build_logged_type_pipeline,
    build_stamp_operation,
    collect_object_ids,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261115
DATABASE_NAME: str = 'cmdb-unit'

LIVE_PARENT_ID: int = 11
LIVE_CHILD_ID: int = 12
GONE_OBJECT_ID: int = 13
LOST_OBJECT_ID: int = 14
LIVE_PARENT_TYPE: int = 21
LIVE_CHILD_TYPE: int = 22
LOGGED_TYPE: int = 23


def _log(mongo_id: str, parent_id: Any, child_id: Any) -> dict[str, Any]:
    """A relation log as the selection reads it"""
    return {'_id': mongo_id, 'object_relation_parent_id': parent_id, 'object_relation_child_id': child_id}


def _build_stubbed_updater(remaining: list[dict[str, Any]] | None = None) -> Any:
    """The updater with a stubbed database manager; `remaining` is what the selection finds"""
    updater = Update20261115.__new__(Update20261115)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter(remaining or [])
    updater.dbm.find_all.return_value = []
    updater.dbm.aggregate_all.return_value = []
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def test_the_version_and_description_name_the_stamp() -> None:
    """The registry orders by the creation date"""
    updater = _build_stubbed_updater()

    assert updater.creation_date() == CREATION_DATE
    assert 'CmdbObjectRelationLog' in updater.description()


def test_the_frozen_collection_names_are_the_models() -> None:
    """The literals were taken from the models when the migration shipped"""
    assert updater_20261115.RELATION_LOGS_COLLECTION == CmdbObjectRelationLog.COLLECTION
    assert updater_20261115.OBJECTS_COLLECTION == CmdbObject.COLLECTION
    assert updater_20261115.OBJECT_LOGS_COLLECTION == CmdbMetaLog.COLLECTION
    assert updater_20261115.OBJECT_LOG_TYPE == OBJECT_LOG_TYPE

# --------------------------------------------------- the selection -------------------------------------------------- #

def test_a_log_missing_either_key_is_selected() -> None:
    """A log stamped on both sides (value or null) is never visited again"""
    assert UNSTAMPED_LOG_CRITERIA == {'$or': [
        {'relation_parent_type_id': {'$exists': False}},
        {'relation_child_type_id': {'$exists': False}},
    ]}


def test_only_whole_number_endpoint_ids_are_collected() -> None:
    """A null, text or boolean endpoint names no object"""
    logs: list[dict[str, Any]] = [
        _log('a', LIVE_PARENT_ID, LIVE_CHILD_ID), _log('b', None, '12'), _log('c', True, GONE_OBJECT_ID),
    ]

    assert collect_object_ids(logs) == {LIVE_PARENT_ID, LIVE_CHILD_ID, GONE_OBJECT_ID}

# ------------------------------------------------- the object-log source -------------------------------------------- #

def test_the_object_log_source_reads_only_numeric_types_of_object_logs() -> None:
    """Match the gone objects' logs carrying a type, one result per object"""
    assert build_logged_type_pipeline([GONE_OBJECT_ID]) == [
        {'$match': {
            'log_type': OBJECT_LOG_TYPE, 'object_id': {'$in': [GONE_OBJECT_ID]}, 'type_id': {'$type': 'number'},
        }},
        {'$group': {'_id': '$object_id', 'type_id': {'$first': '$type_id'}}},
    ]

# ---------------------------------------------------- the write ----------------------------------------------------- #

def test_the_write_stamps_each_side_from_its_own_object() -> None:
    """Distinct values, so a swapped side fails; the filter repeats the selection"""
    operation = build_stamp_operation(
        _log('abc', LIVE_PARENT_ID, LIVE_CHILD_ID), {LIVE_PARENT_ID: LIVE_PARENT_TYPE, LIVE_CHILD_ID: LIVE_CHILD_TYPE},
    )

    assert operation._filter == {'_id': 'abc', **UNSTAMPED_LOG_CRITERIA}  # pylint: disable=protected-access
    assert operation._doc == {'$set': {  # pylint: disable=protected-access
        'relation_parent_type_id': LIVE_PARENT_TYPE, 'relation_child_type_id': LIVE_CHILD_TYPE,
    }}


def test_an_unresolved_side_is_stamped_null() -> None:
    """The log leaves with both keys, so a second run does not visit it again"""
    operation = build_stamp_operation(_log('abc', LOST_OBJECT_ID, None), {})

    assert operation._doc == {'$set': {  # pylint: disable=protected-access
        'relation_parent_type_id': None, 'relation_child_type_id': None,
    }}

# --------------------------------------------------- the resolution ------------------------------------------------- #

def test_live_objects_answer_first_and_the_logs_only_the_rest() -> None:
    """The object-log source is asked only about objects that are gone"""
    updater = _build_stubbed_updater([_log('a', LIVE_PARENT_ID, GONE_OBJECT_ID)])
    updater.dbm.find_all.return_value = [{'public_id': LIVE_PARENT_ID, 'type_id': LIVE_PARENT_TYPE}]
    updater.dbm.aggregate_all.return_value = [{'_id': GONE_OBJECT_ID, 'type_id': LOGGED_TYPE}]

    updater.start_update()

    assert updater.dbm.find_all.call_args.kwargs['filter'] == {'public_id': {'$in': [LIVE_PARENT_ID, GONE_OBJECT_ID]}}
    updater.dbm.aggregate_all.assert_called_once_with(
        CmdbMetaLog.COLLECTION, DATABASE_NAME, build_logged_type_pipeline([GONE_OBJECT_ID]),
    )
    written = updater.dbm.bulk_write.call_args.args[2][0]
    assert written._doc == {'$set': {  # pylint: disable=protected-access
        'relation_parent_type_id': LIVE_PARENT_TYPE, 'relation_child_type_id': LOGGED_TYPE,
    }}


def test_with_every_object_live_the_logs_are_not_read() -> None:
    """No aggregation for nothing"""
    updater = _build_stubbed_updater([_log('a', LIVE_PARENT_ID, LIVE_CHILD_ID)])
    updater.dbm.find_all.return_value = [
        {'public_id': LIVE_PARENT_ID, 'type_id': LIVE_PARENT_TYPE},
        {'public_id': LIVE_CHILD_ID, 'type_id': LIVE_CHILD_TYPE},
    ]

    updater.start_update()

    updater.dbm.aggregate_all.assert_not_called()


def test_a_log_naming_no_object_reads_nothing_and_is_stamped_null() -> None:
    """Both sides unresolvable without a single read"""
    updater = _build_stubbed_updater([_log('a', None, None)])

    updater.start_update()

    updater.dbm.find_all.assert_not_called()
    updater.dbm.aggregate_all.assert_not_called()
    assert updater.dbm.bulk_write.call_args.args[2][0]._doc == {'$set': {  # pylint: disable=protected-access
        'relation_parent_type_id': None, 'relation_child_type_id': None,
    }}

# ---------------------------------------------------- start_update -------------------------------------------------- #

def test_the_selection_reads_only_the_ids_it_needs() -> None:
    """The relation logs are read projected; the version is bumped at the end"""
    updater = _build_stubbed_updater()

    updater.start_update()

    assert updater.dbm.find.call_args.kwargs['collection'] == CmdbObjectRelationLog.COLLECTION
    assert updater.dbm.find.call_args.kwargs['filter'] == UNSTAMPED_LOG_CRITERIA
    assert updater.dbm.find.call_args.kwargs['projection'] == {
        '_id': 1, 'object_relation_parent_id': 1, 'object_relation_child_id': 1,
    }
    updater.dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_the_logs_are_stamped_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every batch is resolved and written on its own"""
    monkeypatch.setattr(updater_20261115, 'BATCH_SIZE', 2)
    updater = _build_stubbed_updater([_log(str(index), None, None) for index in range(5)])

    updater.start_update()

    assert [len(call.args[2]) for call in updater.dbm.bulk_write.call_args_list] == [2, 2, 1]


def test_a_failure_is_raised_as_the_updater_exception_carrying_it() -> None:
    """The tail wraps the error itself, and the version is not bumped"""
    updater = _build_stubbed_updater()
    failure = RuntimeError('boom')
    updater.dbm.find.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()
