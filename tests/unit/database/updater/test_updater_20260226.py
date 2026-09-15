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
Unit tests for cmdb.database.updater.versions.updater_20260226

DB-free. The pure helpers (id collection, both document builders, the batch builder with its skip /
dedup rules) are called directly; the database-touching methods and the orchestration get a MagicMock
dbm / managers, with the updater built via __new__ following the established version-updater pattern.

Emphasis on re-run safety, since a crash before the final version bump repeats the whole migration:
the create-or-adopt branch, the already-migrated-pair skip, the repeat-within-one-run skip, and the
strict id zipping. The metadata contract (creation_date / description) is covered by the shared
parametrized test in test_version_updaters
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260226 import (
    AUTHOR_ID_FIELD,
    CHILD_TYPE_IDS_FIELD,
    CREATION_TIME_FIELD,
    FIELD_VALUES_FIELD,
    LINK_CHILD_FIELD,
    LINK_PARENT_FIELD,
    MAPPER_RELATION_NAME,
    MIGRATION_AUTHOR_ID,
    OBJECT_LINK_COLLECTION,
    OBJECT_RELATION_COLLECTION,
    PARENT_TYPE_IDS_FIELD,
    PUBLIC_ID_FIELD,
    RELATION_CHILD_ID_FIELD,
    RELATION_CHILD_TYPE_ID_FIELD,
    RELATION_COLLECTION,
    RELATION_ID_FIELD,
    RELATION_NAME_FIELD,
    RELATION_PARENT_ID_FIELD,
    RELATION_PARENT_TYPE_ID_FIELD,
    TYPE_ID_FIELD,
    Update20260226,
    build_object_relations,
    collect_linked_object_ids,
    get_mapper_relation,
    get_object_relation_dict,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'cmdb-unit'

TYPE_A_ID: int = 10
TYPE_B_ID: int = 11

OBJECT_A_ID: int = 101
OBJECT_B_ID: int = 102
MISSING_OBJECT_ID: int = 999   # referenced by a link but absent from the objects collection

MAPPER_RELATION_ID: int = 5
RESERVED_ID: int = 77

UPDATER_VERSION: int = 20260226

OBJECT_TYPE_MAP: dict[int, int] = {OBJECT_A_ID: TYPE_A_ID, OBJECT_B_ID: TYPE_B_ID}


def _link(parent_id: int, child_id: int) -> dict[str, Any]:
    """Builds one legacy 'framework.links' document."""
    return {LINK_PARENT_FIELD: parent_id, LINK_CHILD_FIELD: child_id}


def _new_updater(
        object_links: list[dict[str, Any]] | None = None,
        relation_exists: bool = False,
        migrated_relations: list[dict[str, Any]] | None = None,
        objects: list[dict[str, Any]] | None = None,
    ) -> Update20260226:
    """
    Builds the updater without its real __init__, wiring the mocks each test needs

    Args:
        object_links (list[dict[str, Any]] | None): The legacy 'framework.links' documents to serve
        relation_exists (bool): Whether a 'DgObjectLinks' relation is already present (adopt path)
        migrated_relations (list[dict[str, Any]] | None): Pairs the existing relation holds
        objects (list[dict[str, Any]] | None): Object documents; defaults to A and B with a type each

    Returns:
        Update20260226: The updater with ``dbm``, both managers and the version bump mocked
    """
    updater: Update20260226 = Update20260226.__new__(Update20260226)
    updater.db_name = DB_NAME
    updater.dbm = MagicMock()
    updater.objects_manager = MagicMock()
    updater.types_manager = MagicMock()
    updater.increase_updater_version = MagicMock()

    updater.objects_manager.find.return_value = objects if objects is not None else [
        {PUBLIC_ID_FIELD: OBJECT_A_ID, TYPE_ID_FIELD: TYPE_A_ID},
        {PUBLIC_ID_FIELD: OBJECT_B_ID, TYPE_ID_FIELD: TYPE_B_ID},
    ]
    updater.types_manager.find.return_value = [
        {PUBLIC_ID_FIELD: TYPE_A_ID},
        {PUBLIC_ID_FIELD: TYPE_B_ID},
    ]

    updater.dbm.insert.return_value = MAPPER_RELATION_ID
    updater.dbm.reserve_public_ids.side_effect = lambda *args, **kwargs: list(
        range(RESERVED_ID, RESERVED_ID + kwargs['amount'])
    )

    def find(*args: Any, **kwargs: Any) -> Any:
        """Serves the legacy links, the relation lookup and the already-migrated pairs."""
        collection = kwargs.get('collection', args[0] if args else None)

        if collection == OBJECT_LINK_COLLECTION:
            return iter(object_links or [])

        if collection == RELATION_COLLECTION:
            return iter([{PUBLIC_ID_FIELD: MAPPER_RELATION_ID}] if relation_exists else [])

        return iter(migrated_relations or [])

    updater.dbm.find.side_effect = find

    return updater


def _migrated_pair(parent_id: int, child_id: int) -> dict[str, Any]:
    """Builds one stored CmdbObjectRelation as the pair read projects it."""
    return {RELATION_PARENT_ID_FIELD: parent_id, RELATION_CHILD_ID_FIELD: child_id}


def _inserted_relations(updater: Update20260226) -> list[dict[str, Any]]:
    """Returns the documents handed to the single bulk insert (empty when it never ran)."""
    if not updater.dbm.insert_many.call_args_list:
        return []

    return updater.dbm.insert_many.call_args.kwargs['data']


# -------------------------------------------------------------------------------------------------------------------- #
#                                             collect_linked_object_ids                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectLinkedObjectIds:
    """Both ends of every link contribute, deduplicated."""

    def test_collects_both_ends(self) -> None:
        """Parent and child ids are collected."""
        assert collect_linked_object_ids([_link(OBJECT_A_ID, OBJECT_B_ID)]) == {OBJECT_A_ID, OBJECT_B_ID}

    def test_deduplicates_across_links(self) -> None:
        """An object referenced by several links is collected once."""
        links = [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_B_ID, OBJECT_A_ID)]

        assert collect_linked_object_ids(links) == {OBJECT_A_ID, OBJECT_B_ID}

    def test_self_link_yields_one_id(self) -> None:
        """A link pointing at the same object on both ends yields that single id."""
        assert collect_linked_object_ids([_link(OBJECT_A_ID, OBJECT_A_ID)]) == {OBJECT_A_ID}

    def test_no_links_yields_nothing(self) -> None:
        """An empty legacy collection contributes no ids."""
        assert collect_linked_object_ids([]) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 get_mapper_relation                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetMapperRelation:
    """The catch-all relation document."""

    def test_document_shape(self) -> None:
        """Every field of the 2026-02-26 CmdbRelation shape is written, with the frozen name."""
        # The keys/values are spelled out on purpose: a migration writes the 2026-02-26 wire shape, so
        # this assertion has to fail if one of the module's frozen constants is ever re-pointed
        assert get_mapper_relation([TYPE_A_ID, TYPE_B_ID]) == {
            RELATION_NAME_FIELD: MAPPER_RELATION_NAME,
            'relation_name_parent': 'to secondary',
            'relation_icon_parent': 'fa fa-cube',
            'relation_color_parent': '#e9ecef',
            'relation_name_child': 'to primary',
            'relation_icon_child': 'fa fa-cube',
            'relation_color_child': '#e9ecef',
            PARENT_TYPE_IDS_FIELD: [TYPE_A_ID, TYPE_B_ID],
            CHILD_TYPE_IDS_FIELD: [TYPE_A_ID, TYPE_B_ID],
            'description': '',
            'sections': [],
            'fields': [],
        }

    def test_both_ends_allow_every_given_type(self) -> None:
        """The same type list is used on both ends (a catch-all relation)."""
        relation = get_mapper_relation([TYPE_A_ID])

        assert relation[PARENT_TYPE_IDS_FIELD] == relation[CHILD_TYPE_IDS_FIELD] == [TYPE_A_ID]

    def test_an_installation_without_types_yields_empty_ends(self) -> None:
        """No types at migration time means no type is permitted (nothing is invented)."""
        relation = get_mapper_relation([])

        assert relation[PARENT_TYPE_IDS_FIELD] == []
        assert relation[CHILD_TYPE_IDS_FIELD] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_object_relation_dict                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetObjectRelationDict:
    """The per-link CmdbObjectRelation document."""

    @staticmethod
    def _document() -> dict[str, Any]:
        """One built document for object A -> object B."""
        return get_object_relation_dict(
            parent_id=OBJECT_A_ID,
            child_id=OBJECT_B_ID,
            parent_type_id=TYPE_A_ID,
            child_type_id=TYPE_B_ID,
            relation_id=MAPPER_RELATION_ID,
        )

    def test_document_shape(self) -> None:
        """The legacy primary becomes the parent, the secondary the child; no public_id yet."""
        relation = self._document()

        assert relation[RELATION_ID_FIELD] == MAPPER_RELATION_ID
        assert relation[RELATION_PARENT_ID_FIELD] == OBJECT_A_ID
        assert relation[RELATION_CHILD_ID_FIELD] == OBJECT_B_ID
        assert relation[RELATION_PARENT_TYPE_ID_FIELD] == TYPE_A_ID
        assert relation[RELATION_CHILD_TYPE_ID_FIELD] == TYPE_B_ID
        assert relation[AUTHOR_ID_FIELD] == MIGRATION_AUTHOR_ID
        assert relation[FIELD_VALUES_FIELD] == []
        assert isinstance(relation[CREATION_TIME_FIELD], datetime)
        assert PUBLIC_ID_FIELD not in relation

    def test_creation_time_is_timezone_aware_utc(self) -> None:
        """The stamped creation_time carries UTC (not a naive local timestamp)."""
        assert self._document()[CREATION_TIME_FIELD].tzinfo is timezone.utc


# -------------------------------------------------------------------------------------------------------------------- #
#                                               build_object_relations                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildObjectRelations:
    """Every skip / dedup rule of the migration lives here - and it is pure."""

    def test_one_document_per_link(self) -> None:
        """Each healthy link becomes one document carrying the objects' types."""
        links = [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_B_ID, OBJECT_A_ID)]

        relations = build_object_relations(links, OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID)

        assert [
            (item[RELATION_PARENT_ID_FIELD], item[RELATION_CHILD_ID_FIELD]) for item in relations
        ] == [(OBJECT_A_ID, OBJECT_B_ID), (OBJECT_B_ID, OBJECT_A_ID)]
        assert relations[0][RELATION_PARENT_TYPE_ID_FIELD] == TYPE_A_ID
        assert relations[0][RELATION_CHILD_TYPE_ID_FIELD] == TYPE_B_ID
        assert all(item[RELATION_ID_FIELD] == MAPPER_RELATION_ID for item in relations)

    def test_already_migrated_pair_is_skipped(self) -> None:
        """A pair the relation already holds produces nothing (the re-run case)."""
        relations = build_object_relations(
            [_link(OBJECT_A_ID, OBJECT_B_ID)],
            OBJECT_TYPE_MAP,
            {(OBJECT_A_ID, OBJECT_B_ID)},
            MAPPER_RELATION_ID,
        )

        assert relations == []

    def test_only_the_missing_pair_of_a_partial_batch_is_built(self) -> None:
        """Completing a half-written batch emits exactly the documents that are still missing."""
        links = [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_B_ID, OBJECT_A_ID)]

        relations = build_object_relations(
            links, OBJECT_TYPE_MAP, {(OBJECT_A_ID, OBJECT_B_ID)}, MAPPER_RELATION_ID,
        )

        assert len(relations) == 1
        assert relations[0][RELATION_PARENT_ID_FIELD] == OBJECT_B_ID

    def test_a_pair_repeated_in_the_source_yields_one_document(self) -> None:
        """A legacy link duplicated in the source collection is migrated once, not twice."""
        links = [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_A_ID, OBJECT_B_ID)]

        relations = build_object_relations(links, OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID)

        assert len(relations) == 1

    def test_the_reverse_pair_is_a_different_pair(self) -> None:
        """The dedup is directional: (A,B) and (B,A) are both migrated (by design)."""
        links = [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_B_ID, OBJECT_A_ID)]

        assert len(build_object_relations(links, OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID)) == 2

    def test_the_callers_pair_set_is_not_mutated(self) -> None:
        """The migrated-pair set is copied, never extended in place."""
        migrated_pairs = {(OBJECT_B_ID, OBJECT_A_ID)}

        build_object_relations(
            [_link(OBJECT_A_ID, OBJECT_B_ID)], OBJECT_TYPE_MAP, migrated_pairs, MAPPER_RELATION_ID,
        )

        assert migrated_pairs == {(OBJECT_B_ID, OBJECT_A_ID)}

    @pytest.mark.parametrize('link', [
        _link(OBJECT_A_ID, MISSING_OBJECT_ID),   # child deleted
        _link(MISSING_OBJECT_ID, OBJECT_A_ID),   # parent deleted
        _link(MISSING_OBJECT_ID, MISSING_OBJECT_ID),
    ])
    def test_broken_link_is_skipped(self, link: dict[str, Any]) -> None:
        """A link whose object no longer exists produces no document."""
        assert build_object_relations([link], OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID) == []

    def test_broken_link_does_not_stop_the_healthy_ones(self) -> None:
        """A batch containing one broken link still migrates the rest."""
        links = [_link(OBJECT_A_ID, MISSING_OBJECT_ID), _link(OBJECT_A_ID, OBJECT_B_ID)]

        relations = build_object_relations(links, OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID)

        assert len(relations) == 1
        assert relations[0][RELATION_CHILD_ID_FIELD] == OBJECT_B_ID

    def test_no_links_yields_no_documents(self) -> None:
        """Nothing in, nothing out."""
        assert build_object_relations([], OBJECT_TYPE_MAP, set(), MAPPER_RELATION_ID) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  read_legacy_links                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadLegacyLinks:
    """The one read of the legacy collection."""

    def test_reads_the_frozen_collection_with_both_id_fields(self) -> None:
        """The read targets 'framework.links' and projects only the two ids."""
        updater = _new_updater([_link(OBJECT_A_ID, OBJECT_B_ID)])

        result = updater.read_legacy_links()

        assert result == [_link(OBJECT_A_ID, OBJECT_B_ID)]
        assert updater.dbm.find.call_args == call(
            collection=OBJECT_LINK_COLLECTION,
            db_name=DB_NAME,
            filter={},
            projection={LINK_PARENT_FIELD: 1, LINK_CHILD_FIELD: 1, '_id': 0},
        )

    def test_an_installation_without_links_returns_an_empty_list(self) -> None:
        """A missing / empty legacy collection is not an error."""
        assert _new_updater([]).read_legacy_links() == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_object_type_map                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildObjectTypeMap:
    """The object -> type lookup, one query for the whole batch."""

    def test_maps_every_object_to_its_type(self) -> None:
        """The result maps object public_id to type_id."""
        updater = _new_updater()

        assert updater.build_object_type_map({OBJECT_A_ID, OBJECT_B_ID}) == OBJECT_TYPE_MAP

    def test_queries_all_ids_at_once(self) -> None:
        """A single $in query is paid for the whole batch."""
        updater = _new_updater()

        updater.build_object_type_map({OBJECT_A_ID, OBJECT_B_ID})

        updater.objects_manager.find.assert_called_once()
        criteria = updater.objects_manager.find.call_args.kwargs['criteria']
        assert sorted(criteria[PUBLIC_ID_FIELD]['$in']) == [OBJECT_A_ID, OBJECT_B_ID]

    def test_a_deleted_object_is_simply_absent(self) -> None:
        """An id with no document is left out (that is how a broken link is detected)."""
        updater = _new_updater(objects=[{PUBLIC_ID_FIELD: OBJECT_A_ID, TYPE_ID_FIELD: TYPE_A_ID}])

        assert updater.build_object_type_map({OBJECT_A_ID, MISSING_OBJECT_ID}) == {OBJECT_A_ID: TYPE_A_ID}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       resolve / create mapper relation + pairs                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveMapperRelation:
    """Create-or-adopt: the heart of the re-run safety."""

    def test_creates_the_relation_when_none_exists(self) -> None:
        """The relation is created and reported with no migrated pairs."""
        updater = _new_updater()

        relation_id, migrated_pairs = updater.resolve_mapper_relation()

        assert (relation_id, migrated_pairs) == (MAPPER_RELATION_ID, set())

    def test_creation_does_not_read_existing_pairs(self) -> None:
        """A fresh relation cannot hold pairs, so no second query is paid."""
        updater = _new_updater()

        updater.resolve_mapper_relation()

        read_collections = [
            kwargs.get('collection', args[0] if args else None)
            for args, kwargs in updater.dbm.find.call_args_list
        ]
        assert OBJECT_RELATION_COLLECTION not in read_collections

    def test_adopts_an_existing_relation_by_name(self) -> None:
        """An existing relation is adopted (no insert) and its pairs are reported."""
        updater = _new_updater(
            relation_exists=True,
            migrated_relations=[_migrated_pair(OBJECT_A_ID, OBJECT_B_ID)],
        )

        relation_id, migrated_pairs = updater.resolve_mapper_relation()

        assert relation_id == MAPPER_RELATION_ID
        assert migrated_pairs == {(OBJECT_A_ID, OBJECT_B_ID)}
        updater.dbm.insert.assert_not_called()

    def test_the_existence_check_is_a_single_read(self) -> None:
        """One read answers 'does it exist' and 'what is its id' (no separate count)."""
        updater = _new_updater(relation_exists=True)

        updater.resolve_mapper_relation()

        relation_reads = [
            args for args, kwargs in updater.dbm.find.call_args_list
            if args and args[0] == RELATION_COLLECTION
        ]
        assert len(relation_reads) == 1
        updater.dbm.count.assert_not_called()

    def test_created_relation_permits_every_existing_type(self) -> None:
        """The type snapshot is read on the create path and written onto the relation."""
        updater = _new_updater()

        updater.create_mapper_relation()

        collection, db_name, document = updater.dbm.insert.call_args.args
        assert (collection, db_name) == (RELATION_COLLECTION, DB_NAME)
        assert document[RELATION_NAME_FIELD] == MAPPER_RELATION_NAME
        assert document[PARENT_TYPE_IDS_FIELD] == [TYPE_A_ID, TYPE_B_ID]

    def test_adopting_does_not_read_the_types(self) -> None:
        """An installation that already carries the relation never pays the full type read."""
        updater = _new_updater(relation_exists=True)

        updater.resolve_mapper_relation()

        updater.types_manager.find.assert_not_called()

    def test_pairs_are_read_for_the_adopted_relation_only(self) -> None:
        """The pair read is filtered by the adopted relation's public_id."""
        updater = _new_updater(relation_exists=True)

        updater.read_migrated_pairs(MAPPER_RELATION_ID)

        assert updater.dbm.find.call_args.kwargs['filter'] == {RELATION_ID_FIELD: MAPPER_RELATION_ID}

    def test_pairs_of_a_relation_without_instances_are_empty(self) -> None:
        """A relation created by a crashed run holds no pair yet."""
        assert _new_updater(relation_exists=True).read_migrated_pairs(MAPPER_RELATION_ID) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               insert_object_relations                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertObjectRelations:
    """Reserve, stamp, one bulk insert."""

    def test_reserves_ids_and_stamps_them_before_one_bulk_insert(self) -> None:
        """public_ids come from one reservation and are written onto the documents."""
        updater = _new_updater()
        relations = [
            get_object_relation_dict(OBJECT_A_ID, OBJECT_B_ID, TYPE_A_ID, TYPE_B_ID, MAPPER_RELATION_ID),
            get_object_relation_dict(OBJECT_B_ID, OBJECT_A_ID, TYPE_B_ID, TYPE_A_ID, MAPPER_RELATION_ID),
        ]

        updater.insert_object_relations(relations)

        updater.dbm.reserve_public_ids.assert_called_once_with(
            OBJECT_RELATION_COLLECTION, DB_NAME, amount=2,
        )
        updater.dbm.insert_many.assert_called_once()
        assert updater.dbm.insert_many.call_args.kwargs['skip_public'] is True
        assert [item[PUBLIC_ID_FIELD] for item in relations] == [RESERVED_ID, RESERVED_ID + 1]

    def test_an_empty_batch_writes_nothing(self) -> None:
        """Everything already migrated means no reservation and no insert."""
        updater = _new_updater()

        updater.insert_object_relations([])

        updater.dbm.reserve_public_ids.assert_not_called()
        updater.dbm.insert_many.assert_not_called()

    def test_an_id_count_mismatch_fails_loudly(self) -> None:
        """A short reservation raises instead of silently inserting an id-less document."""
        updater = _new_updater()
        updater.dbm.reserve_public_ids.side_effect = None
        updater.dbm.reserve_public_ids.return_value = [RESERVED_ID]

        with pytest.raises(ValueError):
            updater.insert_object_relations([
                get_object_relation_dict(OBJECT_A_ID, OBJECT_B_ID, TYPE_A_ID, TYPE_B_ID, MAPPER_RELATION_ID),
                get_object_relation_dict(OBJECT_B_ID, OBJECT_A_ID, TYPE_B_ID, TYPE_A_ID, MAPPER_RELATION_ID),
            ])

        updater.dbm.insert_many.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              start_update - orchestration                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStartUpdate:
    """The orchestrator wires the phases together and bumps the version last."""

    def test_first_run_creates_the_relation_and_migrates_every_link(self) -> None:
        """The happy path: relation created, one instance per healthy link, version bumped."""
        updater = _new_updater([_link(OBJECT_A_ID, OBJECT_B_ID)])

        updater.start_update()

        updater.dbm.insert.assert_called_once()
        inserted = _inserted_relations(updater)
        assert len(inserted) == 1
        assert inserted[0][RELATION_ID_FIELD] == MAPPER_RELATION_ID
        assert inserted[0][PUBLIC_ID_FIELD] == RESERVED_ID
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_a_repeated_run_writes_nothing(self) -> None:
        """Re-entering a completed migration adopts the relation and inserts nothing."""
        updater = _new_updater(
            [_link(OBJECT_A_ID, OBJECT_B_ID)],
            relation_exists=True,
            migrated_relations=[_migrated_pair(OBJECT_A_ID, OBJECT_B_ID)],
        )

        updater.start_update()

        updater.dbm.insert.assert_not_called()
        updater.dbm.insert_many.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_a_crashed_run_is_completed(self) -> None:
        """Relation present but only part of the batch written: the rest is migrated."""
        updater = _new_updater(
            [_link(OBJECT_A_ID, OBJECT_B_ID), _link(OBJECT_B_ID, OBJECT_A_ID)],
            relation_exists=True,
            migrated_relations=[_migrated_pair(OBJECT_A_ID, OBJECT_B_ID)],
        )

        updater.start_update()

        inserted = _inserted_relations(updater)
        assert len(inserted) == 1
        assert inserted[0][RELATION_PARENT_ID_FIELD] == OBJECT_B_ID

    def test_broken_link_only_still_bumps_the_version(self) -> None:
        """Nothing to write, but the migration is done and must not run again."""
        updater = _new_updater([_link(OBJECT_A_ID, MISSING_OBJECT_ID)])

        updater.start_update()

        updater.dbm.insert_many.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_empty_legacy_collection_creates_nothing_but_bumps_the_version(self) -> None:
        """Without legacy links there is nothing to host: no relation, no instances, version bumped."""
        updater = _new_updater([])

        updater.start_update()

        updater.dbm.insert.assert_not_called()
        updater.dbm.insert_many.assert_not_called()
        updater.objects_manager.find.assert_not_called()
        updater.types_manager.find.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(UPDATER_VERSION)

    def test_a_failing_database_call_is_wrapped_and_the_version_kept(self) -> None:
        """Any error surfaces as UpdaterException; the version stays put so the run repeats."""
        updater = _new_updater([_link(OBJECT_A_ID, OBJECT_B_ID)])
        updater.dbm.insert.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException) as err:
            updater.start_update()

        assert 'boom' in str(err.value)
        updater.increase_updater_version.assert_not_called()
