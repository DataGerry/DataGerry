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
Unit tests for cmdb.database.updater.versions.updater_20260901

Covers the two jobs in isolation with a stubbed database manager: the missing-option diff that is the
whole of the option half's re-run safety (the collection has no unique index to fall back on), the
narrowed read, the backfill's query shape, and start_update's orchestration + error wrapping.

The end-to-end behaviour against a real MongoDB - including the double run - is covered by
tests/integration/database/test_integration_updater_20260901.py, and the metadata contract by the
shared parametrized test in test_version_updaters
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260901 import (
    Update20260901,
    backfill_uses_ports,
    get_missing_port_options,
    insert_missing_port_options,
)
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType, ExtendableOptionKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.updater.versions.updater_20260901'
DB_NAME: str = 'testdb'

TOTAL_OPTIONS: int = 44


def _dbm(stored: list[dict] | None = None) -> MagicMock:
    """Builds a database-manager stub whose find_all returns the given stored options"""
    dbm = MagicMock()
    dbm.find_all.return_value = stored or []
    dbm.update_many.return_value = MagicMock(modified_count=0)

    return dbm


def _stored(option_type: OptionType, value: str) -> dict:
    """Builds a stored extendable-option document the way the collection holds one"""
    return {
        ExtendableOptionKey.VALUE: value,
        ExtendableOptionKey.OPTION_TYPE: option_type.value,
        ExtendableOptionKey.PREDEFINED: True,
        'public_id': 1,
    }


class TestGetMissingPortOptions:
    """The diff that keeps the option half idempotent."""

    def test_an_empty_collection_is_missing_everything(self) -> None:
        """The first run on an existing installation: no port options exist yet."""
        assert len(get_missing_port_options(_dbm([]), DB_NAME)) == TOTAL_OPTIONS

    def test_a_fully_seeded_collection_is_missing_nothing(self) -> None:
        """
        The second run inserts nothing.

        This is the assertion the whole design hangs on: CmdbExtendableOption declares only a
        NON-unique index on option_type, so nothing but this diff stops a re-run duplicating all 44.
        """
        from cmdb.database.predefined_data.port_data import get_default_port_extendable_options

        already_there = [
            {**option, ExtendableOptionKey.OPTION_TYPE: option[ExtendableOptionKey.OPTION_TYPE].value}
            for option in get_default_port_extendable_options()
        ]

        assert get_missing_port_options(_dbm(already_there), DB_NAME) == []

    def test_a_partial_collection_is_topped_up(self) -> None:
        """An interrupted first run resumes: only the values not yet stored come back."""
        missing = get_missing_port_options(
            _dbm([_stored(OptionType.PORT_STATUS, 'Up'), _stored(OptionType.CABLE_TYPE, 'Cat6')]),
            DB_NAME,
        )

        assert len(missing) == TOTAL_OPTIONS - 2
        identities = {(o[ExtendableOptionKey.OPTION_TYPE].value, o[ExtendableOptionKey.VALUE])
                      for o in missing}
        assert ('PORT_STATUS', 'Up') not in identities
        assert ('CABLE_TYPE', 'Cat6') not in identities

    def test_a_customer_added_value_is_not_duplicated(self) -> None:
        """
        A value a customer added by hand before upgrading is left alone.

        The identity is (option_type, value) and deliberately excludes 'predefined', so their
        hand-made 'Cat8' does not gain a second, predefined twin.
        """
        customer_added = _stored(OptionType.CABLE_TYPE, 'Cat8')
        customer_added[ExtendableOptionKey.PREDEFINED] = False

        missing = get_missing_port_options(_dbm([customer_added]), DB_NAME)

        assert not any(o[ExtendableOptionKey.VALUE] == 'Cat8' for o in missing)

    def test_the_read_is_narrowed_and_projected(self) -> None:
        """
        An ISMS installation's own options are not loaded just to be discarded.

        The keyword is 'filter', not 'criteria': find_all forwards **kwargs straight to the cursor,
        so a wrong name is a TypeError at runtime that a MagicMock would happily accept - which is
        why the integration suite is the one that proves the call actually works.
        """
        dbm = _dbm([])
        get_missing_port_options(dbm, DB_NAME)

        kwargs = dbm.find_all.call_args.kwargs

        assert sorted(kwargs['filter'][ExtendableOptionKey.OPTION_TYPE]['$in']) == [
            'CABLE_TYPE', 'PORT_SPEED', 'PORT_STATUS', 'PORT_TYPE',
        ]
        assert kwargs['projection'] == {
            ExtendableOptionKey.OPTION_TYPE: 1, ExtendableOptionKey.VALUE: 1, '_id': 0,
        }
        assert dbm.find_all.call_args.args[0] == CmdbExtendableOption.COLLECTION


class TestInsertMissingPortOptions:
    """The insert loop."""

    def test_inserts_each_missing_option_and_reports_the_count(self) -> None:
        """Every missing document is inserted once into the extendable-option collection."""
        dbm = _dbm([])

        assert insert_missing_port_options(dbm, DB_NAME) == TOTAL_OPTIONS
        assert dbm.insert.call_count == TOTAL_OPTIONS
        assert dbm.insert.call_args.args[0] == CmdbExtendableOption.COLLECTION

    def test_inserts_nothing_when_all_are_present(self) -> None:
        """The idempotent path does no writes at all, not merely harmless ones."""
        from cmdb.database.predefined_data.port_data import get_default_port_extendable_options

        already_there = [
            {**option, ExtendableOptionKey.OPTION_TYPE: option[ExtendableOptionKey.OPTION_TYPE].value}
            for option in get_default_port_extendable_options()
        ]
        dbm = _dbm(already_there)

        assert insert_missing_port_options(dbm, DB_NAME) == 0
        dbm.insert.assert_not_called()


class TestBackfillUsesPorts:
    """The CmdbType.uses_ports backfill."""

    def test_targets_only_documents_without_the_key(self) -> None:
        """
        '$exists: False' is what makes this re-runnable and non-destructive.

        Matching on the value instead would overwrite a type that was already set to True.
        """
        dbm = _dbm()
        backfill_uses_ports(dbm, DB_NAME)

        assert dbm.update_many.call_args.args[0] == CmdbType.COLLECTION
        assert dbm.update_many.call_args.kwargs['criteria'] == {
            TypeSchemaKey.USES_PORTS.value: {'$exists': False},
        }
        assert dbm.update_many.call_args.kwargs['update'] == {TypeSchemaKey.USES_PORTS.value: False}

    def test_reports_how_many_types_were_given_the_field(self) -> None:
        """The count is what the migration logs."""
        dbm = _dbm()
        dbm.update_many.return_value = MagicMock(modified_count=7)

        assert backfill_uses_ports(dbm, DB_NAME) == 7


class TestStartUpdate:
    """Orchestration: both jobs, then the version bump."""

    def test_runs_both_jobs_then_bumps_the_version(self) -> None:
        """The version is written only after both jobs return, so a crash leaves it re-runnable."""
        updater = Update20260901.__new__(Update20260901)
        updater.dbm = _dbm([])
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        with patch(f'{MODULE_PATH}.insert_missing_port_options', return_value=3) as options, \
             patch(f'{MODULE_PATH}.backfill_uses_ports', return_value=2) as backfill:
            updater.start_update()

        options.assert_called_once_with(updater.dbm, DB_NAME)
        backfill.assert_called_once_with(updater.dbm, DB_NAME)
        updater.increase_updater_version.assert_called_once_with(20260901)

    def test_a_failure_is_wrapped_and_the_version_is_not_bumped(self) -> None:
        """
        A half-applied migration must stay re-runnable.

        Bumping the version on the way out would mark it done and the second job would never run.
        """
        updater = Update20260901.__new__(Update20260901)
        updater.dbm = _dbm([])
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        with patch(f'{MODULE_PATH}.insert_missing_port_options', side_effect=RuntimeError('boom')):
            with pytest.raises(UpdaterException):
                updater.start_update()

        updater.increase_updater_version.assert_not_called()

    def test_a_backfill_failure_also_leaves_the_version_alone(self) -> None:
        """The second job failing is the same contract as the first."""
        updater = Update20260901.__new__(Update20260901)
        updater.dbm = _dbm([])
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        with patch(f'{MODULE_PATH}.insert_missing_port_options', return_value=0), \
             patch(f'{MODULE_PATH}.backfill_uses_ports', side_effect=RuntimeError('boom')):
            with pytest.raises(UpdaterException):
                updater.start_update()

        updater.increase_updater_version.assert_not_called()
