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
Unit tests for cmdb.database.updater.versions.updater_20261003

The migration rewrites every CmdbType's incomplete ``acl`` to the complete block it already reads as. Its run
against real collections - every stored shape, the readers' answers before and after, the double run - is its own
integration test, which also evaluates the selection against every shape in a real MongoDB; this module owns the
shape of the writes and the failure tail
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so find / bulk_write carry call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.updater.versions.updater_20261003 import (
    INCOMPLETE_ACL_CRITERIA,
    Update20261003,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.access_control_list import AccessControlList
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261003
DATABASE_NAME: str = 'cmdb-unit'
TYPE_ID: int = 4343


def _build_stubbed_updater(documents: list[dict[str, Any]] | None = None) -> Any:
    """The updater with a stubbed database manager, bypassing the base class's wiring."""
    updater = Update20261003.__new__(Update20261003)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter(documents or [])
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater

# ---------------------------------------------------- start_update -------------------------------------------------- #

def test_reads_the_types_through_the_selection() -> None:
    """Only the incomplete types are read, with their id and acl"""
    updater = _build_stubbed_updater()

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.find.call_args.kwargs
    assert kwargs['collection'] == CmdbType.COLLECTION
    assert kwargs['db_name'] == DATABASE_NAME
    assert kwargs['filter'] == INCOMPLETE_ACL_CRITERIA


def test_writes_each_types_normalized_block_guarded_by_the_selection() -> None:
    """One $set per type, of normalize_stored's block, filtered by the selection so a repaired type is skipped"""
    stored_acl: dict[str, Any] = {'activated': False}
    updater = _build_stubbed_updater([{'public_id': TYPE_ID, 'acl': stored_acl}])

    updater.start_update()

    collection, db_name, operations = updater.dbm.bulk_write.call_args.args
    assert (collection, db_name) == (CmdbType.COLLECTION, DATABASE_NAME)
    assert len(operations) == 1
    assert operations[0]._filter == {'public_id': TYPE_ID, **INCOMPLETE_ACL_CRITERIA}
    assert operations[0]._doc == {'$set': {'acl': AccessControlList.normalize_stored(stored_acl)}}


def test_a_type_without_an_acl_key_gets_the_default() -> None:
    """The document carries no acl at all"""
    updater = _build_stubbed_updater([{'public_id': TYPE_ID}])

    updater.start_update()

    operations = updater.dbm.bulk_write.call_args.args[2]
    assert operations[0]._doc == {'$set': {'acl': AccessControlList.default_json()}}


def test_nothing_selected_writes_nothing_and_still_bumps_the_version() -> None:
    """A clean database is a no-op apart from the version"""
    updater = _build_stubbed_updater()

    updater.start_update()

    updater.dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_write_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The wrapper carries the exception (args[0] and __cause__); the version is not bumped"""
    updater = _build_stubbed_updater([{'public_id': TYPE_ID, 'acl': None}])
    failure = RuntimeError('down')
    updater.dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.args[0] is failure
    assert exc_info.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()


def test_creation_date_and_description() -> None:
    """The version is the module's date, it is registered, and the description says what it does"""
    updater = Update20261003.__new__(Update20261003)

    assert updater.creation_date() == CREATION_DATE
    assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__
    assert updater.description() == "Stores every Type's 'acl' as the complete block"
