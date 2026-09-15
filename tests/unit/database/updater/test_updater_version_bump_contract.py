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
The version-bump ordering contract, asserted once for every updater that shares it

Every migration that writes to more than one collection owes the same promise: the updater version is
persisted **only after all of its work is done**. Bumping it on the way out would record a
half-applied migration as complete, and the runner never revisits a version below the stored one - so
the unfinished half would never run.

Each updater's own module tests what is specific to it (its filters, its values, its metadata). This
module owns the part that is identical across them, so the contract is written once and every updater
listed here inherits it. Adding an updater to ``TWO_COLLECTION_UPDATERS`` is the whole cost of joining.

``build_stubbed_updater`` is shared for the same reason and is imported by the per-updater modules
rather than copied into them.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.updater.versions.updater_20260417 import Update20260417
from cmdb.database.updater.versions.updater_20260908 import Update20260908
# -------------------------------------------------------------------------------------------------------------------- #

# (updater class, its registered version) for every migration writing to types AND objects
TWO_COLLECTION_UPDATERS: list[tuple[type[BaseDatabaseUpdate], int]] = [
    (Update20260417, 20260417),
    (Update20260908, 20260908),
]

UPDATER_IDS: list[str] = [updater_cls.__name__ for updater_cls, _version in TWO_COLLECTION_UPDATERS]


def build_stubbed_updater(updater_cls: type[BaseDatabaseUpdate],
                          type_modified: int = 0,
                          object_modified: int = 0) -> Any:
    """
    Builds an updater with stubbed managers, bypassing the base class's database wiring

    ``BaseDatabaseUpdate.__init__`` reads the config and opens a MongoDatabaseManager, so the instance
    is created through ``__new__`` and given exactly the three attributes a two-collection migration
    touches.

    Args:
        updater_cls (type[BaseDatabaseUpdate]): The updater class to instantiate
        type_modified (int): modified_count the types update reports
        object_modified (int): modified_count the objects update reports

    Returns:
        Any: The updater, with stubbed managers and a stubbed version bump
    """
    updater = updater_cls.__new__(updater_cls)
    updater.types_manager = MagicMock()
    updater.types_manager.update_many.return_value = MagicMock(modified_count=type_modified)
    updater.objects_manager = MagicMock()
    updater.objects_manager.update_many.return_value = MagicMock(modified_count=object_modified)
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('updater_cls, version', TWO_COLLECTION_UPDATERS, ids=UPDATER_IDS)
class TestVersionBumpOrdering:
    """
    The version is written after all the work, or not at all

    Every test takes both parameters so the whole class shares one parametrisation; the failure cases
    assert that NO version was written, so they never read which one it would have been.
    """
    # pylint: disable=unused-argument

    def test_the_version_is_bumped_after_both_collections(
            self, updater_cls: type[BaseDatabaseUpdate], version: int) -> None:
        """On success, with the updater's own registered version."""
        updater = build_stubbed_updater(updater_cls, type_modified=3, object_modified=7)

        updater.start_update()

        updater.increase_updater_version.assert_called_once_with(version)

    def test_a_types_failure_leaves_the_version_alone(
            self, updater_cls: type[BaseDatabaseUpdate], version: int) -> None:
        """The objects are never reached, and the migration repeats on the next start."""
        updater = build_stubbed_updater(updater_cls)
        updater.types_manager.update_many.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()
        updater.objects_manager.update_many.assert_not_called()

    def test_an_objects_failure_leaves_the_version_alone(
            self, updater_cls: type[BaseDatabaseUpdate], version: int) -> None:
        """Half the collections migrated is exactly the state a repeat fixes."""
        updater = build_stubbed_updater(updater_cls)
        updater.objects_manager.update_many.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()

    def test_the_original_error_is_kept_as_the_cause(
            self, updater_cls: type[BaseDatabaseUpdate], version: int) -> None:
        """The UpdaterException wrapper must not swallow what actually failed."""
        updater = build_stubbed_updater(updater_cls)
        failure = RuntimeError('boom')
        updater.types_manager.update_many.side_effect = failure

        with pytest.raises(UpdaterException) as raised:
            updater.start_update()

        assert raised.value.__cause__ is failure

    def test_both_collections_are_updated_exactly_once(
            self, updater_cls: type[BaseDatabaseUpdate], version: int) -> None:
        """Objects carry a copy of their type's marker, so both collections need the write."""
        updater = build_stubbed_updater(updater_cls)

        updater.start_update()

        updater.types_manager.update_many.assert_called_once()
        updater.objects_manager.update_many.assert_called_once()
