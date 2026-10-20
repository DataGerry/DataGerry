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
Unit tests for cmdb.database.updater.versions.updater_20261002

The migration keeps only the right names the right tree knows in each CmdbUserGroup's ``rights``. Its run against
real collections is its own integration test; this module owns the pure filter (``known_rights_of``), the shape
of what is written, and the failure tail: the wrapper carries the error itself and a failed run leaves the version
alone, so the migration repeats on the next start
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so find / bulk_write carry call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.updater.versions.updater_20261002 import (
    KNOWN_RIGHT_NAMES,
    UNREPAIRED_RIGHTS_CRITERIA,
    Update20261002,
    known_rights_of,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.group_model import CmdbUserGroup, MASTER_RIGHT_NAME
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261002
DATABASE_NAME: str = 'cmdb-unit'

KNOWN_RIGHT: str = 'base.framework.object.view'
OTHER_KNOWN_RIGHT: str = 'base.framework.type.edit'
UNKNOWN_RIGHT: str = 'base.no-such-right'
NOT_A_STRING: int = 7
UNHASHABLE: dict[str, Any] = {}

KNOWN_NAMES: frozenset[str] = frozenset(KNOWN_RIGHT_NAMES)
GROUP_ID: int = 4242


def _build_stubbed_updater(groups: list[dict[str, Any]] | None = None) -> Any:
    """
    Builds the updater with a stubbed database manager, bypassing the base class's wiring

    Args:
        groups (list[dict[str, Any]] | None): What the stubbed find answers

    Returns:
        Any: The updater, with a stubbed manager, database name and version bump
    """
    updater = Update20261002.__new__(Update20261002)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter(groups or [])
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater

# --------------------------------------------------- known_rights_of ------------------------------------------------ #

def test_known_names_are_the_whole_right_tree() -> None:
    """The kept set is every name of the right tree, wildcards included."""
    assert KNOWN_NAMES == {right.name for right in flat_rights_tree(ALL_RIGHTS)}
    assert MASTER_RIGHT_NAME in KNOWN_NAMES


def test_known_names_are_kept_in_their_stored_order() -> None:
    """Known names survive in the order they were stored."""
    assert known_rights_of([OTHER_KNOWN_RIGHT, KNOWN_RIGHT], KNOWN_NAMES) == [OTHER_KNOWN_RIGHT, KNOWN_RIGHT]


@pytest.mark.parametrize('junk', [UNKNOWN_RIGHT, NOT_A_STRING, UNHASHABLE, [KNOWN_RIGHT], None])
def test_every_unknown_entry_is_stripped(junk: Any) -> None:
    """An unknown name, a number, an unhashable dict, a nested list and a null all go; the known name stays."""
    assert known_rights_of([junk, KNOWN_RIGHT], KNOWN_NAMES) == [KNOWN_RIGHT]


@pytest.mark.parametrize('stored', ['base.*', {'name': KNOWN_RIGHT}, NOT_A_STRING])
def test_a_rights_value_that_is_no_list_becomes_empty(stored: Any) -> None:
    """A non-list value is reset - not read character by character or key by key."""
    assert not known_rights_of(stored, KNOWN_NAMES)

# ----------------------------------------------------- start_update ------------------------------------------------- #

def test_selects_groups_through_the_unrepaired_criteria() -> None:
    """Only the groups holding an unknown entry (or a non-list value) are read."""
    updater = _build_stubbed_updater()

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.find.call_args.kwargs
    assert kwargs['collection'] == CmdbUserGroup.COLLECTION
    assert kwargs['db_name'] == DATABASE_NAME
    assert kwargs['filter'] == UNREPAIRED_RIGHTS_CRITERIA


def test_writes_each_groups_known_names_back() -> None:
    """One $set per selected group, guarded by the same criteria so a repaired group is not rewritten."""
    updater = _build_stubbed_updater([{'public_id': GROUP_ID, 'rights': [UNHASHABLE, KNOWN_RIGHT, UNKNOWN_RIGHT]}])

    updater.start_update()

    collection, db_name, operations = updater.dbm.bulk_write.call_args.args
    assert (collection, db_name) == (CmdbUserGroup.COLLECTION, DATABASE_NAME)
    assert len(operations) == 1
    assert operations[0]._filter == {'public_id': GROUP_ID, **UNREPAIRED_RIGHTS_CRITERIA}
    assert operations[0]._doc == {'$set': {'rights': [KNOWN_RIGHT]}}


def test_nothing_selected_writes_nothing_and_still_bumps_the_version() -> None:
    """A clean database is a no-op apart from the version."""
    updater = _build_stubbed_updater()

    updater.start_update()

    updater.dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_write_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The wrapper carries the exception (args[0] and __cause__); the version is not bumped."""
    updater = _build_stubbed_updater([{'public_id': GROUP_ID, 'rights': [UNKNOWN_RIGHT]}])
    failure = RuntimeError('down')
    updater.dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.args[0] is failure
    assert exc_info.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()


def test_creation_date_is_registered() -> None:
    """The version is the module's date and is listed in the updater registry."""
    assert Update20261002.__new__(Update20261002).creation_date() == CREATION_DATE
    assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__


def test_description_names_the_repair() -> None:
    """The description shown in the update log says what the migration does."""
    assert Update20261002.__new__(Update20261002).description() == (
        "Keeps only known right names in every user group's 'rights'"
    )
