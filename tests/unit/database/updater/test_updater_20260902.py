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
Unit tests for cmdb.database.updater.versions.updater_20260902

Pure tests with a mocked MongoDatabaseManager. What matters here is the ordering and the choices,
not the I/O:

* the duplicate-group pipeline groups on BOTH identity fields and keeps only real groups
* which duplicate survives - predefined first, then the lowest public_id
* references are re-pointed BEFORE the duplicate is deleted, so nothing is ever left pointing at a
  document that no longer exists
* the dedupe runs BEFORE the index rebuild, because MongoDB refuses to build a unique index over a
  collection that still holds duplicates
* the index spec is read from the model rather than copied into the migration, and an already-unique
  index is left alone so a second run is a no-op
"""
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
    LEGACY_OPTION_TYPE_INDEX_NAME,
)
from cmdb.models.extendable_option_model import OptionType
from cmdb.models.port_connection_model import CmdbPortConnection
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.database.updater.versions.updater_20260902 import (
    GROUP_IDENTITY_KEY,
    GROUP_OPTIONS_KEY,
    Update20260902,
    deduplicate_options,
    find_duplicate_option_groups,
    rebuild_value_index,
    select_keeper,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'

NON_UNIQUE_INDEX_INFO: dict[str, Any] = {
    LEGACY_OPTION_TYPE_INDEX_NAME: {'key': [('option_type', 1)]},
}


def _new() -> Update20260902:
    """Builds the updater without its real __init__ (the caller attaches the mocks it needs)"""
    return Update20260902.__new__(Update20260902)


def _member(public_id: int, predefined: bool = False) -> dict[str, Any]:
    """One member of a duplicate group, shaped like the aggregation output"""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.PREDEFINED.value: predefined,
    }


def _group(option_type: str, value: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """One duplicate group, shaped like the aggregation output"""
    return {
        GROUP_IDENTITY_KEY: {
            ExtendableOptionKey.OPTION_TYPE.value: option_type,
            ExtendableOptionKey.VALUE.value: value,
        },
        GROUP_OPTIONS_KEY: members,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              find_duplicate_option_groups                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindDuplicateOptionGroups:
    """The aggregation that locates the duplicates."""

    def test_groups_on_both_identity_fields(self) -> None:
        """A value is only a duplicate within its own OptionType, so both fields form the group key"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([])

        find_duplicate_option_groups(dbm, DB_NAME)

        collection, db_name, pipeline = dbm.aggregate.call_args.args
        group_id = pipeline[0]['$group'][GROUP_IDENTITY_KEY]

        assert (collection, db_name) == (CmdbExtendableOption.COLLECTION, DB_NAME)
        assert group_id == {
            ExtendableOptionKey.OPTION_TYPE.value: f'${ExtendableOptionKey.OPTION_TYPE.value}',
            ExtendableOptionKey.VALUE.value: f'${ExtendableOptionKey.VALUE.value}',
        }

    def test_keeps_only_groups_with_a_second_member(self) -> None:
        """The $match on 'options.1' is what makes a single option not a duplicate"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([])

        find_duplicate_option_groups(dbm, DB_NAME)

        pipeline = dbm.aggregate.call_args.args[2]

        assert pipeline[1] == {'$match': {f'{GROUP_OPTIONS_KEY}.1': {'$exists': True}}}

    def test_returns_the_groups_as_a_list(self) -> None:
        """The cursor is materialised, because the collection is written to while iterating it"""
        groups = [_group(OptionType.RISK.value, 'Financial', [_member(3), _member(4)])]
        dbm = MagicMock()
        dbm.aggregate.return_value = iter(groups)

        assert find_duplicate_option_groups(dbm, DB_NAME) == groups


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    select_keeper                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSelectKeeper:
    """Which of several identical options survives."""

    def test_prefers_a_predefined_option_over_a_lower_public_id(self) -> None:
        """Discarding the predefined copy would only bring the duplicate back on the next seeding"""
        assert select_keeper([_member(3), _member(9, predefined=True)]) == 9

    def test_falls_back_to_the_lowest_public_id(self) -> None:
        """Among customer-created equals the oldest entry wins"""
        assert select_keeper([_member(7), _member(2), _member(5)]) == 2

    def test_picks_the_lowest_of_several_predefined_options(self) -> None:
        """Two predefined copies of the same value should not make the choice ambiguous"""
        assert select_keeper([_member(9, predefined=True), _member(4, predefined=True), _member(1)]) == 4

    def test_a_missing_predefined_key_is_not_predefined(self) -> None:
        """A document written before the flag existed must not be mistaken for a predefined one"""
        assert select_keeper([{ExtendableOptionKey.PUBLIC_ID.value: 8},
                              {ExtendableOptionKey.PUBLIC_ID.value: 3}]) == 3

    def test_a_truthy_non_true_predefined_value_is_not_predefined(self) -> None:
        """The flag is compared with 'is True', so a stray string does not win the tie-break"""
        assert select_keeper([{ExtendableOptionKey.PUBLIC_ID.value: 8,
                               ExtendableOptionKey.PREDEFINED.value: 'yes'},
                              {ExtendableOptionKey.PUBLIC_ID.value: 3}]) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                                deduplicate_options                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeduplicateOptions:
    """The de-duplication pass."""

    def test_writes_nothing_when_there_are_no_duplicates(self) -> None:
        """The common case on a healthy database: one read, no writes"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([])

        assert deduplicate_options(dbm, DB_NAME) == 0
        dbm.delete_many_raw.assert_not_called()
        dbm.update_many.assert_not_called()

    def test_deletes_every_member_except_the_keeper(self) -> None:
        """Both discarded ids go in one delete statement, not one statement per document"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group(OptionType.RISK.value, 'Financial', [_member(3), _member(4), _member(5)]),
        ])

        assert deduplicate_options(dbm, DB_NAME) == 2

        dbm.delete_many_raw.assert_called_once_with(
            CmdbExtendableOption.COLLECTION,
            DB_NAME,
            {ExtendableOptionKey.PUBLIC_ID.value: {'$in': [4, 5]}},
        )

    def test_repoints_references_before_deleting(self) -> None:
        """Deleting first would leave the referencing documents pointing at nothing"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group(OptionType.RISK.value, 'Financial', [_member(3), _member(4)]),
        ])

        deduplicate_options(dbm, DB_NAME)

        repoint_index = dbm.mock_calls.index(call.update_many(
            IsmsRisk.COLLECTION, DB_NAME, {'category_id': 4}, {'category_id': 3},
        ))
        delete_index = dbm.mock_calls.index(call.delete_many_raw(
            *dbm.delete_many_raw.call_args.args,
        ))

        assert repoint_index < delete_index

    def test_repoints_every_discarded_member(self) -> None:
        """A group of three leaves two ids to move, each onto the keeper"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group(OptionType.RISK.value, 'Financial', [_member(3), _member(4), _member(5)]),
        ])

        deduplicate_options(dbm, DB_NAME)

        assert dbm.update_many.call_args_list == [
            call(IsmsRisk.COLLECTION, DB_NAME, {'category_id': 4}, {'category_id': 3}),
            call(IsmsRisk.COLLECTION, DB_NAME, {'category_id': 5}, {'category_id': 3}),
        ]

    def test_counts_removals_across_groups(self) -> None:
        """Every group contributes its own discarded members to the total"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group(OptionType.RISK.value, 'Financial', [_member(3), _member(4)]),
            _group(OptionType.PORT_TYPE.value, 'RJ45', [_member(10), _member(11), _member(12)]),
        ])

        assert deduplicate_options(dbm, DB_NAME) == 3

    def test_an_option_type_nothing_references_is_only_deleted(self) -> None:
        """A group whose option_type nothing can reference has nothing to move, only to delete

        Every real OptionType is referenced from somewhere now, so this is reached by a stored value
        that is no OptionType at all - a duplicate of one still has to be removed.
        """
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group('SOMETHING_ELSE', 'Cat6', [_member(10), _member(11)]),
        ])

        assert deduplicate_options(dbm, DB_NAME) == 1
        dbm.update_many.assert_not_called()
        dbm.delete_many_raw.assert_called_once()

    def test_a_cable_type_duplicate_repoints_the_connections_holding_it(self) -> None:
        """A CABLE_TYPE duplicate moves the connections that hold it before it is deleted"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            _group(OptionType.CABLE_TYPE.value, 'Cat6', [_member(10), _member(11)]),
        ])

        assert deduplicate_options(dbm, DB_NAME) == 1
        assert dbm.update_many.call_args.args[0] == CmdbPortConnection.COLLECTION
        dbm.delete_many_raw.assert_called_once()

    def test_documents_missing_their_identity_fields_are_deduplicated_too(self) -> None:
        """A unique index treats every missing value as the same null, so these collide as well"""
        dbm = MagicMock()
        dbm.aggregate.return_value = iter([
            {
                GROUP_IDENTITY_KEY: {},
                GROUP_OPTIONS_KEY: [_member(20), _member(21)],
            },
        ])

        assert deduplicate_options(dbm, DB_NAME) == 1
        dbm.delete_many_raw.assert_called_once_with(
            CmdbExtendableOption.COLLECTION,
            DB_NAME,
            {ExtendableOptionKey.PUBLIC_ID.value: {'$in': [21]}},
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                rebuild_value_index                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRebuildValueIndex:
    """Building the unique index and retiring the one it supersedes."""

    def test_creates_the_unique_index_and_drops_the_legacy_one(self) -> None:
        """The compound index has option_type as its prefix, so the old index is redundant"""
        dbm = MagicMock()
        dbm.get_index_info.return_value = dict(NON_UNIQUE_INDEX_INFO)

        assert rebuild_value_index(dbm, DB_NAME) is True

        collection, db_name, indexes = dbm.create_indexes.call_args.args
        assert (collection, db_name) == (CmdbExtendableOption.COLLECTION, DB_NAME)
        assert indexes[0].document['name'] == OPTION_TYPE_VALUE_INDEX_NAME
        assert indexes[0].document['unique'] is True
        assert list(indexes[0].document['key'].items()) == [
            (ExtendableOptionKey.OPTION_TYPE.value, 1),
            (ExtendableOptionKey.VALUE.value, 1),
        ]
        dbm.drop_index.assert_called_once_with(
            CmdbExtendableOption.COLLECTION, DB_NAME, LEGACY_OPTION_TYPE_INDEX_NAME,
        )

    def test_creates_the_index_before_dropping_the_legacy_one(self) -> None:
        """An interruption must never leave the collection with no index on option_type at all"""
        dbm = MagicMock()
        dbm.get_index_info.return_value = dict(NON_UNIQUE_INDEX_INFO)

        rebuild_value_index(dbm, DB_NAME)

        create_index = dbm.mock_calls.index(call.create_indexes(*dbm.create_indexes.call_args.args))
        drop_index = dbm.mock_calls.index(call.drop_index(*dbm.drop_index.call_args.args))

        assert create_index < drop_index

    def test_leaves_an_already_unique_index_alone(self) -> None:
        """A database that already carries the unique index is untouched, so a re-run is a no-op"""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {
            OPTION_TYPE_VALUE_INDEX_NAME: {'key': [('option_type', 1), ('value', 1)], 'unique': True},
        }

        assert rebuild_value_index(dbm, DB_NAME) is False
        dbm.create_indexes.assert_not_called()
        dbm.drop_index.assert_not_called()

    def test_finishes_dropping_the_legacy_index_after_an_interrupted_run(self) -> None:
        """The unique index exists but the drop did not happen - the second run completes it"""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {
            OPTION_TYPE_VALUE_INDEX_NAME: {'key': [('option_type', 1), ('value', 1)], 'unique': True},
            LEGACY_OPTION_TYPE_INDEX_NAME: {'key': [('option_type', 1)]},
        }

        assert rebuild_value_index(dbm, DB_NAME) is False
        dbm.create_indexes.assert_not_called()
        dbm.drop_index.assert_called_once_with(
            CmdbExtendableOption.COLLECTION, DB_NAME, LEGACY_OPTION_TYPE_INDEX_NAME,
        )

    def test_drops_a_same_name_index_that_is_not_unique_before_recreating_it(self) -> None:
        """MongoDB rejects redefining an index under the same name with different options"""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {
            OPTION_TYPE_VALUE_INDEX_NAME: {'key': [('option_type', 1), ('value', 1)]},
        }

        assert rebuild_value_index(dbm, DB_NAME) is True
        assert dbm.drop_index.call_args_list == [
            call(CmdbExtendableOption.COLLECTION, DB_NAME, OPTION_TYPE_VALUE_INDEX_NAME),
        ]
        dbm.create_indexes.assert_called_once()

    def test_creates_nothing_if_the_model_stops_declaring_the_index(self) -> None:
        """
        The spec is read from the model, so a model that no longer declares it creates nothing

        Guards against a future change to CmdbExtendableOption.INDEX_KEYS silently resurrecting the
        index from a copy of the spec hardcoded in this migration.
        """
        dbm = MagicMock()
        dbm.get_index_info.return_value = {}

        with patch.object(CmdbExtendableOption, 'INDEX_KEYS', []):
            assert rebuild_value_index(dbm, DB_NAME) is False

        dbm.create_indexes.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    start_update                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStartUpdate:
    """The migration as a whole."""

    def test_deduplicates_before_rebuilding_and_bumps_the_version(self) -> None:
        """The dedupe must precede the rebuild - a unique index cannot be built over duplicates"""
        updater = _new()
        updater.dbm = dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.settings_manager = settings_manager = MagicMock()

        dbm.aggregate.return_value = iter([])
        dbm.get_index_info.return_value = dict(NON_UNIQUE_INDEX_INFO)

        updater.start_update()

        aggregate_index = dbm.mock_calls.index(call.aggregate(*dbm.aggregate.call_args.args))
        create_index = dbm.mock_calls.index(call.create_indexes(*dbm.create_indexes.call_args.args))

        assert aggregate_index < create_index
        settings_manager.write.assert_called_once_with(
            _id='updater', data={'_id': 'updater', 'version': 20260902},
        )

    def test_does_not_bump_the_version_when_the_rebuild_fails(self) -> None:
        """A failed migration must stay unrecorded so the next start re-runs it in full"""
        updater = _new()
        updater.dbm = dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.settings_manager = settings_manager = MagicMock()

        dbm.aggregate.return_value = iter([])
        dbm.get_index_info.side_effect = RuntimeError('index info unavailable')

        with pytest.raises(UpdaterException):
            updater.start_update()

        settings_manager.write.assert_not_called()

    def test_does_not_rebuild_the_index_when_the_dedupe_fails(self) -> None:
        """Building the unique index over a collection still holding duplicates would fail anyway"""
        updater = _new()
        updater.dbm = dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.settings_manager = settings_manager = MagicMock()

        dbm.aggregate.side_effect = RuntimeError('aggregation failed')

        with pytest.raises(UpdaterException):
            updater.start_update()

        dbm.create_indexes.assert_not_called()
        settings_manager.write.assert_not_called()
