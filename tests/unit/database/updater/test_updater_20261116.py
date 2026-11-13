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
Unit tests for cmdb.database.updater.versions.updater_20261116

The migration drops the SpecialType index that held every marker unique; its successor holds only the singletons.
Its run against a real collection is its own integration test; this module owns the frozen literals, the relation to
the declared successor, the drop call, the log lines and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261116 as module
from cmdb.database.updater.versions.updater_20261116 import REPLACED_INDEX, Update20261116
from cmdb.errors.database import DropIndexError
from cmdb.errors.updater import UpdaterException
from cmdb.models.type_model import CmdbType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261116
DATABASE_NAME: str = 'cmdb-unit'
SUCCESSOR_INDEX: str = 'special_type_singleton'


def _build_stubbed_updater(dropped: bool = True) -> Any:
    """The updater with a stubbed database manager; drop_index answers whether the index was there"""
    updater = Update20261116.__new__(Update20261116)
    updater.dbm = MagicMock()
    updater.dbm.drop_index.return_value = dropped
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def test_the_frozen_literals() -> None:
    """The types collection, and the index name updater_20261030 built"""
    assert (module.TYPES_COLLECTION, REPLACED_INDEX) == (CmdbType.COLLECTION, 'special_type')


def test_the_replaced_name_is_no_longer_declared() -> None:
    """A declared name would be rebuilt by the startup reconciliation right after the drop"""
    assert REPLACED_INDEX not in {entry['name'] for entry in CmdbType.INDEX_KEYS}


def test_the_successor_is_declared_on_the_same_key() -> None:
    """The reconciliation adds it under its own name"""
    successor = next(entry for entry in CmdbType.INDEX_KEYS if entry['name'] == SUCCESSOR_INDEX)

    assert successor['keys'] == [(TypeSchemaKey.SPECIAL_TYPE.value, CmdbType.DAO_ASCENDING)]
    assert successor['unique'] is True


def test_the_version_and_description() -> None:
    """The registry orders by the creation date; the description says what changes"""
    updater = _build_stubbed_updater()

    assert updater.creation_date() == CREATION_DATE
    assert 'PERSON' in updater.description()
    assert 'system type' in updater.description()


@pytest.mark.parametrize('dropped, line', [
    (True, "Dropped the 'special_type' index"),
    (False, "No 'special_type' index"),
], ids=['present', 'absent'])
def test_the_index_is_dropped_by_name_and_logged(dropped: bool, line: str, caplog: pytest.LogCaptureFixture) -> None:
    """An absent index is no failure - it is how a re-run and a new install look"""
    updater = _build_stubbed_updater(dropped)

    with caplog.at_level(logging.INFO, logger=module.LOGGER.name):
        updater.start_update()

    updater.dbm.drop_index.assert_called_once_with(CmdbType.COLLECTION, DATABASE_NAME, REPLACED_INDEX)
    assert line in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_every_type_without_the_marker_is_marked_as_no_system_type() -> None:
    """One write, selecting only Types without the key - a re-run selects nothing"""
    updater = _build_stubbed_updater()

    updater.start_update()

    updater.dbm.update_many.assert_called_once_with(
        CmdbType.COLLECTION, DATABASE_NAME, {'system_type': {'$exists': False}}, {'system_type': False},
    )
    assert module.SYSTEM_TYPE_FIELD == TypeSchemaKey.SYSTEM_TYPE.value


def test_a_failed_drop_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The next start runs the migration again"""
    updater = _build_stubbed_updater()
    failure = DropIndexError('boom')
    updater.dbm.drop_index.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.args[0] is failure
    assert caught.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()
