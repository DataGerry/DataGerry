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
Unit tests for cmdb.database.updater.versions.updater_20261114

The migration drops the two log indexes their longer successors replace. Its run against a real collection is its own
integration test; this module owns the frozen literals, the relation to the declared successors, the drop calls, the
log lines and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261114 as module
from cmdb.database.updater.versions.updater_20261114 import REPLACED_INDEXES, Update20261114
from cmdb.errors.database import DropIndexError
from cmdb.errors.updater import UpdaterException
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261114
DATABASE_NAME: str = 'cmdb-unit'
OBJECT_ID_INDEX: str = 'object_id_log_time'
LOG_TYPE_INDEX: str = 'log_type_action'


def _build_stubbed_updater(drop_results: list[bool] | None = None) -> Any:
    """The updater with a stubbed database manager; drop_index answers the given results in turn"""
    updater = Update20261114.__new__(Update20261114)
    updater.dbm = MagicMock()
    updater.dbm.drop_index.side_effect = drop_results or [True, True]
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def _declared_keys() -> dict[str, list[tuple[str, int]]]:
    """The key lists CmdbMetaLog declares, by index name"""
    return {entry['name']: list(entry['keys']) for entry in CmdbMetaLog.INDEX_KEYS}


def test_the_collection_is_the_logs_collection() -> None:
    """Frozen on purpose - and right when it shipped"""
    assert module.LOGS_COLLECTION == CmdbMetaLog.COLLECTION


def test_the_replaced_names_are_the_two_predecessors() -> None:
    """Exactly the two names the successors replaced"""
    assert REPLACED_INDEXES == (OBJECT_ID_INDEX, LOG_TYPE_INDEX)


def test_no_replaced_name_is_still_declared() -> None:
    """A declared name would be rebuilt by the startup reconciliation right after the drop"""
    assert not set(REPLACED_INDEXES) & set(_declared_keys())


@pytest.mark.parametrize('replaced, prefix', [
    (OBJECT_ID_INDEX, [('object_id', 1), ('log_time', -1)]),
    (LOG_TYPE_INDEX, [('log_type', 1), ('action', 1)]),
], ids=['object_id', 'log_type'])
def test_a_successor_starts_with_the_predecessors_keys(replaced: str, prefix: list[tuple[str, int]]) -> None:
    """Every query the dropped index served, a declared index still serves by its leading keys"""
    del replaced
    successors = [keys for keys in _declared_keys().values() if keys[:len(prefix)] == prefix]

    assert len(successors) == 1
    assert len(successors[0]) > len(prefix)


def test_both_indexes_are_dropped_by_name() -> None:
    """One drop per predecessor, then the version"""
    updater = _build_stubbed_updater()

    updater.start_update()

    assert updater.dbm.drop_index.call_args_list == [
        call(CmdbMetaLog.COLLECTION, DATABASE_NAME, OBJECT_ID_INDEX),
        call(CmdbMetaLog.COLLECTION, DATABASE_NAME, LOG_TYPE_INDEX),
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


@pytest.mark.parametrize('drop_results, dropped, absent', [
    ([True, True], [OBJECT_ID_INDEX, LOG_TYPE_INDEX], []),
    ([False, True], [LOG_TYPE_INDEX], [OBJECT_ID_INDEX]),
    ([False, False], [], [OBJECT_ID_INDEX, LOG_TYPE_INDEX]),
], ids=['both-present', 'one-present', 'none-present'])
def test_each_index_is_logged_as_dropped_or_absent(drop_results: list[bool], dropped: list[str], absent: list[str],
                                                   caplog: pytest.LogCaptureFixture) -> None:
    """An absent index is no failure - it is how a re-run and a new install look"""
    updater = _build_stubbed_updater(drop_results)

    with caplog.at_level(logging.INFO, logger=module.LOGGER.name):
        updater.start_update()

    for name in dropped:
        assert f"Dropped the '{name}' index" in caplog.text
    for name in absent:
        assert f"No '{name}' index" in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_drop_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The next start runs the migration again"""
    error = DropIndexError('down')
    updater = _build_stubbed_updater()
    updater.dbm.drop_index.side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_names_the_log_indexes() -> None:
    """The line the updater log prints"""
    assert 'log indexes' in Update20261114.__new__(Update20261114).description()
