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
Unit tests for cmdb.database.updater.versions.updater_20250619

DB-free: the updater is built via __new__ with a MagicMock dbm, following the established
version-updater pattern. Asserts that each of the three backfills is one server-side bulk operation
filtered on the missing property (no document is loaded for the two constant backfills), that the
per-type color read is filtered AND projected, that a type document without a public_id is skipped
with a warning instead of silently, and that the version bump comes last. The metadata contract
(creation_date / description) is covered by the shared parametrized test in test_version_updaters
"""
import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.database.updater.versions.updater_20250619 import (
    MONGO_ID_FIELD,
    OBJECT_TOOLTIP_FIELD,
    PUBLIC_ID_FIELD,
    TYPE_COLOR_FIELD,
    TYPE_LABEL_FIELD,
    Update20250619,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'cmdb-unit'

TYPE_A_ID: int = 10
TYPE_B_ID: int = 11

UPDATER_VERSION: int = 20250619

MODIFIED_COUNT: int = 3

HEX_COLOR_PATTERN: re.Pattern = re.compile(r'^#[0-9A-F]{6}$')


def _new_updater(types_without_color: list[dict[str, Any]] | None = None) -> Update20250619:
    """
    Builds the updater without its real __init__, with a mocked dbm

    Args:
        types_without_color (list[dict[str, Any]] | None): Documents the color read serves; defaults to
            the two test types

    Returns:
        Update20250619: The updater with ``dbm`` and the version bump mocked
    """
    updater: Update20250619 = Update20250619.__new__(Update20250619)
    updater.db_name = DB_NAME
    updater.dbm = MagicMock()
    updater.increase_updater_version = MagicMock()

    updater.dbm.update_many_raw.return_value = MagicMock(modified_count=MODIFIED_COUNT)
    updater.dbm.find_all.return_value = types_without_color if types_without_color is not None else [
        {PUBLIC_ID_FIELD: TYPE_A_ID},
        {PUBLIC_ID_FIELD: TYPE_B_ID},
    ]

    return updater


def _bulk_update_call(updater: Update20250619, collection: str) -> dict[str, Any]:
    """Returns the kwargs of the update_many_raw call targeting the given collection."""
    return next(
        call.kwargs for call in updater.dbm.update_many_raw.call_args_list
        if call.kwargs['collection'] == collection
    )


def _bulk_write_operations(updater: Update20250619) -> list[Any]:
    """Returns the pymongo operations handed to the single bulk_write (empty when it never ran)."""
    if not updater.dbm.bulk_write.call_args_list:
        return []

    return updater.dbm.bulk_write.call_args.args[2]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            backfill_object_tooltips                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBackfillObjectTooltips:
    """The object tooltip backfill: one bulk update, nothing loaded."""

    def test_is_one_filtered_bulk_update(self) -> None:
        """Only objects lacking the property are matched, and the value is set server-side."""
        updater = _new_updater()

        updater.backfill_object_tooltips()

        updater.dbm.update_many_raw.assert_called_once_with(
            collection=CmdbObject.COLLECTION,
            db_name=DB_NAME,
            filter_query={OBJECT_TOOLTIP_FIELD: {'$exists': False}},
            update={'$set': {OBJECT_TOOLTIP_FIELD: None}},
        )

    def test_loads_no_document(self) -> None:
        """The objects collection is never read (it used to be loaded in full)."""
        updater = _new_updater()

        updater.backfill_object_tooltips()

        updater.dbm.find_all.assert_not_called()
        updater.dbm.update.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              backfill_type_labels                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBackfillTypeLabels:
    """The type label backfill: the same single bulk update."""

    def test_is_one_filtered_bulk_update(self) -> None:
        """Only types lacking the label are matched."""
        updater = _new_updater()

        updater.backfill_type_labels()

        updater.dbm.update_many_raw.assert_called_once_with(
            collection=CmdbType.COLLECTION,
            db_name=DB_NAME,
            filter_query={TYPE_LABEL_FIELD: {'$exists': False}},
            update={'$set': {TYPE_LABEL_FIELD: None}},
        )

    def test_loads_no_document(self) -> None:
        """No type document is loaded for the label backfill."""
        updater = _new_updater()

        updater.backfill_type_labels()

        updater.dbm.find_all.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              backfill_type_colors                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBackfillTypeColors:
    """The per-type color backfill: filtered + projected read, one batched bulk_write."""

    def test_reads_only_the_public_ids_of_types_missing_the_color(self) -> None:
        """The read is filtered and projected server-side instead of loading whole types."""
        updater = _new_updater()

        updater.backfill_type_colors()

        updater.dbm.find_all.assert_called_once_with(
            CmdbType.COLLECTION,
            DB_NAME,
            filter={TYPE_COLOR_FIELD: {'$exists': False}},
            projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0},
        )

    def test_writes_one_operation_per_type_in_a_single_bulk_write(self) -> None:
        """Every type missing the color gets its own operation, all sent in one call."""
        updater = _new_updater()

        updater.backfill_type_colors()

        updater.dbm.bulk_write.assert_called_once()
        collection, db_name, _ = updater.dbm.bulk_write.call_args.args
        assert (collection, db_name) == (CmdbType.COLLECTION, DB_NAME)
        assert len(_bulk_write_operations(updater)) == 2

    def test_each_operation_targets_one_type_with_a_hex_color(self) -> None:
        """Each operation sets a well-formed color on exactly its own type."""
        updater = _new_updater()

        updater.backfill_type_colors()

        targeted_ids = []
        for operation in _bulk_write_operations(updater):
            document = operation._doc  # pylint: disable=protected-access
            targeted_ids.append(operation._filter[PUBLIC_ID_FIELD])  # pylint: disable=protected-access
            assert HEX_COLOR_PATTERN.match(document['$set'][TYPE_COLOR_FIELD])

        assert targeted_ids == [TYPE_A_ID, TYPE_B_ID]

    def test_nothing_is_written_when_every_type_has_a_color(self) -> None:
        """An installation that needs no color assignment pays no write."""
        updater = _new_updater(types_without_color=[])

        updater.backfill_type_colors()

        updater.dbm.bulk_write.assert_not_called()

    def test_a_type_without_a_public_id_is_skipped_with_a_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A corrupt type document cannot be addressed - it is skipped loudly, not silently."""
        updater = _new_updater(types_without_color=[{}, {PUBLIC_ID_FIELD: TYPE_A_ID}])

        with caplog.at_level('WARNING'):
            updater.backfill_type_colors()

        assert len(_bulk_write_operations(updater)) == 1
        assert PUBLIC_ID_FIELD in caplog.text

    def test_only_corrupt_documents_means_no_write(self) -> None:
        """When nothing addressable is left, no bulk_write is issued."""
        updater = _new_updater(types_without_color=[{}])

        updater.backfill_type_colors()

        updater.dbm.bulk_write.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              start_update - orchestration                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStartUpdate:
    """The orchestrator runs the three backfills and bumps the version last."""

    def test_runs_every_backfill_and_bumps_the_version(self) -> None:
        """All three properties are backfilled in one run and the version is persisted."""
        updater = _new_updater()

        updater.start_update()

        updated_fields = {
            next(iter(call.kwargs['update']['$set'])) for call in updater.dbm.update_many_raw.call_args_list
        }
        assert updated_fields == {OBJECT_TOOLTIP_FIELD, TYPE_LABEL_FIELD}
        updater.dbm.bulk_write.assert_called_once()
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_each_collection_gets_its_own_filtered_update(self) -> None:
        """The object and type bulk updates target their own collection and property."""
        updater = _new_updater()

        updater.start_update()

        object_call = _bulk_update_call(updater, CmdbObject.COLLECTION)
        type_call = _bulk_update_call(updater, CmdbType.COLLECTION)

        assert object_call['filter_query'] == {OBJECT_TOOLTIP_FIELD: {'$exists': False}}
        assert type_call['filter_query'] == {TYPE_LABEL_FIELD: {'$exists': False}}

    def test_an_installation_needing_nothing_still_bumps_the_version(self) -> None:
        """No matching document anywhere: no color write, migration still recorded as done."""
        updater = _new_updater(types_without_color=[])
        updater.dbm.update_many_raw.return_value = MagicMock(modified_count=0)

        updater.start_update()

        updater.dbm.bulk_write.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_a_failure_is_wrapped_and_the_version_kept(self) -> None:
        """Any error surfaces as UpdaterException; the version stays put so the run repeats."""
        updater = _new_updater()
        updater.dbm.update_many_raw.side_effect = RuntimeError('db down')

        with pytest.raises(UpdaterException) as err:
            updater.start_update()

        assert 'db down' in str(err.value)
        updater.increase_updater_version.assert_not_called()

    def test_a_failing_color_write_keeps_the_version(self) -> None:
        """A failure in the last backfill also leaves the version untouched (the whole run repeats)."""
        updater = _new_updater()
        updater.dbm.bulk_write.side_effect = RuntimeError('bulk failed')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()
