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
Unit tests for cmdb.database.updater.versions.updater_20260804

Covers the keeper-selection rule, the duplicate-group pipeline, the mirrored-parent read, the
fold-and-delete write order (references moved before the duplicates are deleted, which is what makes
an interrupted run safe), the index rebuild's three branches (already unique / non-unique / absent)
and the orchestration in start_update. The metadata contract (creation_date / description) is covered
by the shared parametrized test in test_version_updaters
"""
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model import FieldType
from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260804 import (
    GROUP_NODES_KEY,
    GROUP_OBJECT_ID_KEY,
    OBJECT_ID_INDEX_NAME,
    Update20260804,
    deduplicate_object_locations,
    find_duplicate_location_groups,
    get_mirrored_parents,
    merge_duplicate_locations,
    rebuild_object_id_index,
    select_keeper,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'

KEEPER_ID: int = 41
DROPPED_ID: int = 77
OTHER_DROPPED_ID: int = 78

OBJECT_ID: int = 300
MIRRORED_PARENT_ID: int = 9


def _new() -> Update20260804:
    """Builds the updater without its real __init__ (the caller attaches the mocks it needs)"""
    return Update20260804.__new__(Update20260804)


def _node(public_id: int, parent: int) -> dict[str, Any]:
    """Builds one entry of a duplicate group as the aggregation emits it"""
    return {'public_id': public_id, 'parent': parent}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    select_keeper                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_select_keeper_prefers_the_node_matching_the_objects_own_location_field() -> None:
    """The node whose parent equals the mirrored value wins even when it is not the lowest id"""
    nodes = [_node(4, 3), _node(7, MIRRORED_PARENT_ID)]

    assert select_keeper(nodes, MIRRORED_PARENT_ID) == 7


def test_select_keeper_falls_back_to_the_lowest_public_id_without_a_mirrored_parent() -> None:
    """An object with no location field (mirrored parent None) keeps its oldest node"""
    assert select_keeper([_node(7, 3), _node(4, 9)], None) == 4


def test_select_keeper_falls_back_when_no_node_matches_the_mirrored_parent() -> None:
    """A mirrored value that matches nothing must not prevent a keeper being chosen"""
    assert select_keeper([_node(7, 3), _node(4, 9)], 99) == 4


def test_select_keeper_picks_the_lowest_of_several_matching_nodes() -> None:
    """Two nodes sharing the mirrored parent resolve deterministically to the lowest id"""
    nodes = [_node(9, 5), _node(8, 5), _node(2, 1)]

    assert select_keeper(nodes, 5) == 8

# -------------------------------------------------------------------------------------------------------------------- #
#                                          find_duplicate_location_groups                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def test_find_duplicate_location_groups_matches_only_groups_with_a_second_node() -> None:
    """The pipeline groups by object_id and keeps groups whose 'nodes' array has an index 1"""
    dbm = MagicMock()
    dbm.aggregate.return_value = iter([{GROUP_OBJECT_ID_KEY: OBJECT_ID, GROUP_NODES_KEY: []}])

    result = find_duplicate_location_groups(dbm, DB_NAME)

    assert result == [{GROUP_OBJECT_ID_KEY: OBJECT_ID, GROUP_NODES_KEY: []}]

    collection, db_name, pipeline = dbm.aggregate.call_args.args
    assert collection == CmdbLocation.COLLECTION
    assert db_name == DB_NAME
    assert pipeline[0]['$group'][GROUP_OBJECT_ID_KEY] == '$object_id'
    assert pipeline[1]['$match'] == {f'{GROUP_NODES_KEY}.1': {'$exists': True}}

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_mirrored_parents                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_mirrored_parents_reads_the_location_field_value_per_object() -> None:
    """Only the location-typed field is read, and objects without one are absent from the result"""
    dbm = MagicMock()
    dbm.find_all.return_value = [
        {
            CmdbObjectKey.PUBLIC_ID.value: OBJECT_ID,
            CmdbObjectKey.FIELDS.value: [
                {
                    CmdbObjectFieldKey.NAME.value: 'text-field',
                    CmdbObjectFieldKey.VALUE.value: 'ignored',
                    CmdbObjectFieldKey.TYPE.value: FieldType.TEXT.value,
                },
                {
                    CmdbObjectFieldKey.NAME.value: 'dg_location',
                    CmdbObjectFieldKey.VALUE.value: MIRRORED_PARENT_ID,
                    CmdbObjectFieldKey.TYPE.value: FieldType.LOCATION.value,
                },
            ],
        },
        {CmdbObjectKey.PUBLIC_ID.value: 301, CmdbObjectKey.FIELDS.value: []},
    ]

    assert get_mirrored_parents(dbm, DB_NAME, [OBJECT_ID, 301]) == {OBJECT_ID: MIRRORED_PARENT_ID}

    # The projection must be a keyword argument - MongoDatabaseManager.find injects its own default
    # projection into kwargs, so passing one positionally raises 'multiple values for projection'
    assert 'projection' in dbm.find_all.call_args.kwargs
    assert len(dbm.find_all.call_args.args) == 3


def test_get_mirrored_parents_skips_the_read_for_an_empty_id_list() -> None:
    """No object ids means no query at all"""
    dbm = MagicMock()

    assert get_mirrored_parents(dbm, DB_NAME, []) == {}
    dbm.find_all.assert_not_called()


def test_get_mirrored_parents_tolerates_a_document_without_a_fields_key() -> None:
    """A document whose 'fields' is missing or None must not raise"""
    dbm = MagicMock()
    dbm.find_all.return_value = [
        {CmdbObjectKey.PUBLIC_ID.value: OBJECT_ID},
        {CmdbObjectKey.PUBLIC_ID.value: 301, CmdbObjectKey.FIELDS.value: None},
    ]

    assert get_mirrored_parents(dbm, DB_NAME, [OBJECT_ID, 301]) == {}

# -------------------------------------------------------------------------------------------------------------------- #
#                                            merge_duplicate_locations                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_merge_duplicate_locations_moves_references_before_deleting() -> None:
    """
    Both re-pointing writes must happen before the delete

    That order is the whole re-run guarantee: an interrupted run may leave a childless duplicate
    (removed by the next run) but never a child pointing at a node that is already gone
    """
    manager = MagicMock()
    dropped = [DROPPED_ID, OTHER_DROPPED_ID]

    merge_duplicate_locations(manager, DB_NAME, KEEPER_ID, dropped)

    assert manager.mock_calls.index(
        call.update_many_raw(
            collection=CmdbLocation.COLLECTION,
            db_name=DB_NAME,
            filter_query={'parent': {'$in': dropped}},
            update={'$set': {'parent': KEEPER_ID}},
        )
    ) < manager.mock_calls.index(
        call.delete_many_raw(
            collection=CmdbLocation.COLLECTION,
            db_name=DB_NAME,
            filter_query={'public_id': {'$in': dropped}},
        )
    )
    assert manager.update_many_raw.call_count == 2
    assert manager.delete_many_raw.call_count == 1


def test_merge_duplicate_locations_repoints_the_mirrored_object_field() -> None:
    """The objects' location field is rewritten in place via an array filter, not per document"""
    manager = MagicMock()

    merge_duplicate_locations(manager, DB_NAME, KEEPER_ID, [DROPPED_ID])

    object_update = manager.update_many_raw.call_args_list[1].kwargs
    assert object_update['update'] == {'$set': {'fields.$[f].value': KEEPER_ID}}
    assert object_update['array_filters'] == [
        {'f.type': FieldType.LOCATION.value, 'f.value': {'$in': [DROPPED_ID]}},
    ]


def test_merge_duplicate_locations_writes_nothing_without_duplicates() -> None:
    """An empty dropped list is a no-op rather than an unfiltered update"""
    manager = MagicMock()

    merge_duplicate_locations(manager, DB_NAME, KEEPER_ID, [])

    manager.update_many_raw.assert_not_called()
    manager.delete_many_raw.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                          deduplicate_object_locations                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_deduplicate_object_locations_returns_zero_when_nothing_is_duplicated() -> None:
    """A clean collection performs no reads beyond the grouping and no writes"""
    dbm = MagicMock()
    dbm.aggregate.return_value = iter([])

    assert deduplicate_object_locations(dbm, DB_NAME) == 0
    dbm.find_all.assert_not_called()
    dbm.delete_many_raw.assert_not_called()


def test_deduplicate_object_locations_keeps_the_mirrored_node_and_drops_the_rest() -> None:
    """The keeper is the mirrored node; every other node of the group is folded in and deleted"""
    dbm = MagicMock()
    dbm.aggregate.return_value = iter([
        {
            GROUP_OBJECT_ID_KEY: OBJECT_ID,
            GROUP_NODES_KEY: [_node(KEEPER_ID, MIRRORED_PARENT_ID), _node(DROPPED_ID, 5)],
        },
    ])
    dbm.find_all.return_value = [
        {
            CmdbObjectKey.PUBLIC_ID.value: OBJECT_ID,
            CmdbObjectKey.FIELDS.value: [
                {
                    CmdbObjectFieldKey.NAME.value: 'dg_location',
                    CmdbObjectFieldKey.VALUE.value: MIRRORED_PARENT_ID,
                    CmdbObjectFieldKey.TYPE.value: FieldType.LOCATION.value,
                },
            ],
        },
    ]

    assert deduplicate_object_locations(dbm, DB_NAME) == 1

    delete_filter = dbm.delete_many_raw.call_args.kwargs['filter_query']
    assert delete_filter == {'public_id': {'$in': [DROPPED_ID]}}


def test_deduplicate_object_locations_counts_every_removed_node_across_groups() -> None:
    """Two groups with three surplus nodes between them report three removals"""
    dbm = MagicMock()
    dbm.aggregate.return_value = iter([
        {GROUP_OBJECT_ID_KEY: OBJECT_ID, GROUP_NODES_KEY: [_node(4, 1), _node(5, 1), _node(6, 1)]},
        {GROUP_OBJECT_ID_KEY: 301, GROUP_NODES_KEY: [_node(8, 1), _node(9, 1)]},
    ])
    dbm.find_all.return_value = []

    assert deduplicate_object_locations(dbm, DB_NAME) == 3


def test_deduplicate_object_locations_ignores_a_non_integer_group_id_for_the_object_read() -> None:
    """A null object_id group must not be sent into the '$in' of the object lookup"""
    dbm = MagicMock()
    dbm.aggregate.return_value = iter([
        {GROUP_OBJECT_ID_KEY: None, GROUP_NODES_KEY: [_node(4, 1), _node(5, 1)]},
    ])
    dbm.find_all.return_value = []

    assert deduplicate_object_locations(dbm, DB_NAME) == 1
    dbm.find_all.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                            rebuild_object_id_index                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_rebuild_object_id_index_leaves_an_already_unique_index_alone() -> None:
    """A database already carrying the unique index is untouched, so a re-run is a no-op"""
    dbm = MagicMock()
    dbm.get_index_info.return_value = {OBJECT_ID_INDEX_NAME: {'key': [('object_id', 1)], 'unique': True}}

    assert rebuild_object_id_index(dbm, DB_NAME) is False
    dbm.drop_index.assert_not_called()
    dbm.create_indexes.assert_not_called()


def test_rebuild_object_id_index_drops_and_recreates_a_non_unique_index() -> None:
    """The legacy non-unique index is dropped first, because MongoDB rejects a same-name redefine"""
    dbm = MagicMock()
    dbm.get_index_info.return_value = {OBJECT_ID_INDEX_NAME: {'key': [('object_id', 1)]}}

    assert rebuild_object_id_index(dbm, DB_NAME) is True

    dbm.drop_index.assert_called_once_with(CmdbLocation.COLLECTION, DB_NAME, OBJECT_ID_INDEX_NAME)

    collection, db_name, indexes = dbm.create_indexes.call_args.args
    assert (collection, db_name) == (CmdbLocation.COLLECTION, DB_NAME)
    assert indexes[0].document['name'] == OBJECT_ID_INDEX_NAME
    assert indexes[0].document['unique'] is True


def test_rebuild_object_id_index_creates_the_index_when_it_is_absent() -> None:
    """A collection missing the index entirely gets it created without a drop"""
    dbm = MagicMock()
    dbm.get_index_info.return_value = {'public_id': {'key': [('public_id', 1)], 'unique': True}}

    assert rebuild_object_id_index(dbm, DB_NAME) is True
    dbm.drop_index.assert_not_called()
    dbm.create_indexes.assert_called_once()


def test_rebuild_object_id_index_creates_nothing_if_the_model_stops_declaring_it() -> None:
    """
    The index spec is read from the model, so a model that no longer declares it creates nothing

    Guards against a future change to CmdbLocation.INDEX_KEYS silently resurrecting the index from a
    copy of the spec hardcoded in this migration.
    """
    dbm = MagicMock()
    dbm.get_index_info.return_value = {}

    with patch.object(CmdbLocation, 'INDEX_KEYS', []):
        assert rebuild_object_id_index(dbm, DB_NAME) is False

    dbm.create_indexes.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   start_update                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_start_update_deduplicates_before_rebuilding_and_bumps_the_version() -> None:
    """The dedupe must precede the rebuild - a unique index cannot be built over duplicates"""
    updater = _new()
    updater.dbm = dbm = MagicMock()
    updater.db_name = DB_NAME
    updater.settings_manager = settings_manager = MagicMock()

    dbm.aggregate.return_value = iter([])
    dbm.get_index_info.return_value = {OBJECT_ID_INDEX_NAME: {'key': [('object_id', 1)]}}

    updater.start_update()

    assert dbm.mock_calls.index(call.aggregate(
        CmdbLocation.COLLECTION, DB_NAME, dbm.aggregate.call_args.args[2],
    )) < dbm.mock_calls.index(call.create_indexes(
        *dbm.create_indexes.call_args.args,
    ))
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20260804},
    )


def test_start_update_does_not_bump_the_version_when_the_rebuild_fails() -> None:
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
