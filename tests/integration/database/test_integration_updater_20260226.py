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
Integration tests for cmdb.database.updater.versions.updater_20260226 against a real MongoDB

The unit tests pin every query and write with mocked managers; these run the whole migration against
real collections seeded with a pre-migration baseline: two CmdbTypes, three CmdbObjects and a legacy
'framework.links' collection holding one healthy link per direction plus one link pointing at a
deleted object.

Covered end to end: the catch-all 'DgObjectLinks' CmdbRelation is created with every existing type on
both ends, one CmdbObjectRelation per healthy link carries the objects' real type ids, the broken link
is skipped, public_ids are assigned from the collection counter, the persisted updater version is
bumped, and - the claim the dedup code exists for and that nothing verified so far - a **second run
duplicates nothing**, neither the relation nor its instances.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.type_model import CmdbType
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
    Update20260226,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_A_ID: int = 9581
TYPE_B_ID: int = 9582
TYPE_IDS: list[int] = [TYPE_A_ID, TYPE_B_ID]

OBJECT_A_ID: int = 9591
OBJECT_B_ID: int = 9592
OBJECT_C_ID: int = 9593
OBJECT_IDS: list[int] = [OBJECT_A_ID, OBJECT_B_ID, OBJECT_C_ID]

DELETED_OBJECT_ID: int = 9599  # a link target that no longer exists -> the link must be skipped

UPDATER_VERSION: int = 20260226
UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'

NAME_FIELD: str = 'dg-name'


def _type_doc(public_id: int, name: str) -> dict[str, Any]:
    """Builds a minimal active CmdbType document."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        'name': name,
        'label': name,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'information', 'label': 'Information',
                          'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a minimal active CmdbObject document of the given type."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}'}],
    }


def _link_doc(parent_id: int, child_id: int) -> dict[str, Any]:
    """Builds one legacy 'framework.links' document."""
    return {LINK_PARENT_FIELD: parent_id, LINK_CHILD_FIELD: child_id}


@pytest.fixture(scope='module', autouse=True, name='seeded_baseline')
def fixture_seeded_baseline(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the pre-migration baseline (types, objects, legacy links), cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    links = database_manager.get_collection(OBJECT_LINK_COLLECTION, database_name)
    relations = database_manager.get_collection(RELATION_COLLECTION, database_name)
    object_relations = database_manager.get_collection(OBJECT_RELATION_COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    previous_updater_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    types.insert_many([_type_doc(TYPE_A_ID, 'it-link-type-a'), _type_doc(TYPE_B_ID, 'it-link-type-b')])
    objects.insert_many([
        _object_doc(OBJECT_A_ID, TYPE_A_ID),
        _object_doc(OBJECT_B_ID, TYPE_B_ID),
        _object_doc(OBJECT_C_ID, TYPE_A_ID),
    ])
    links.insert_many([
        _link_doc(OBJECT_A_ID, OBJECT_B_ID),        # healthy
        _link_doc(OBJECT_B_ID, OBJECT_C_ID),        # healthy, other direction / other types
        _link_doc(OBJECT_A_ID, DELETED_OBJECT_ID),  # broken -> skipped
    ])

    yield

    migrated = list(relations.find({RELATION_NAME_FIELD: MAPPER_RELATION_NAME}, {PUBLIC_ID_FIELD: 1}))

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': OBJECT_IDS}})
    links.delete_many({})
    object_relations.delete_many({
        RELATION_ID_FIELD: {'$in': [relation[PUBLIC_ID_FIELD] for relation in migrated]},
    })
    relations.delete_many({RELATION_NAME_FIELD: MAPPER_RELATION_NAME})

    if previous_updater_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_updater_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


@pytest.fixture(scope='module', autouse=True, name='run_updater')
def fixture_run_updater(  # pylint: disable=unused-argument
    seeded_baseline, database_manager: MongoDatabaseManager, database_name: str,
):
    """Runs the migration once against the seeded baseline; depends on it purely for ordering."""
    Update20260226(database_manager, database_name).start_update()
    yield


@pytest.fixture(name='relations_collection')
def fixture_relations_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbRelation collection."""
    return database_manager.get_collection(RELATION_COLLECTION, database_name)


@pytest.fixture(name='object_relations_collection')
def fixture_object_relations_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbObjectRelation collection."""
    return database_manager.get_collection(OBJECT_RELATION_COLLECTION, database_name)


def _mapper_relation(relations_collection) -> dict[str, Any]:
    """Reads the migrated catch-all relation."""
    return relations_collection.find_one({RELATION_NAME_FIELD: MAPPER_RELATION_NAME}, {'_id': 0})


def _migrated_instances(relations_collection, object_relations_collection) -> list[dict[str, Any]]:
    """Reads every CmdbObjectRelation belonging to the migrated relation."""
    relation = _mapper_relation(relations_collection)

    return list(object_relations_collection.find(
        {RELATION_ID_FIELD: relation[PUBLIC_ID_FIELD]}, {'_id': 0},
    ))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                THE CATCH-ALL RELATION                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_mapper_relation_is_created(relations_collection) -> None:
    """Exactly one 'DgObjectLinks' relation exists after the migration"""
    assert relations_collection.count_documents({RELATION_NAME_FIELD: MAPPER_RELATION_NAME}) == 1


def test_both_relation_ends_permit_every_seeded_type(relations_collection) -> None:
    """The type lists are the snapshot of all existing types (frozen at migration time)"""
    relation = _mapper_relation(relations_collection)

    assert set(TYPE_IDS) <= set(relation[PARENT_TYPE_IDS_FIELD])
    assert set(TYPE_IDS) <= set(relation[CHILD_TYPE_IDS_FIELD])
    assert relation[PARENT_TYPE_IDS_FIELD] == relation[CHILD_TYPE_IDS_FIELD]


def test_the_relation_got_a_public_id(relations_collection) -> None:
    """The relation is inserted through the counter, so it carries a real public_id"""
    assert isinstance(_mapper_relation(relations_collection)[PUBLIC_ID_FIELD], int)


# -------------------------------------------------------------------------------------------------------------------- #
#                                               THE MIGRATED INSTANCES                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_one_instance_per_healthy_link(relations_collection, object_relations_collection) -> None:
    """Both healthy links are migrated; the broken one contributes nothing"""
    instances = _migrated_instances(relations_collection, object_relations_collection)

    pairs = {(item[RELATION_PARENT_ID_FIELD], item[RELATION_CHILD_ID_FIELD]) for item in instances}

    assert pairs == {(OBJECT_A_ID, OBJECT_B_ID), (OBJECT_B_ID, OBJECT_C_ID)}


def test_broken_link_is_not_migrated(relations_collection, object_relations_collection) -> None:
    """No instance references the deleted object"""
    instances = _migrated_instances(relations_collection, object_relations_collection)

    assert all(item[RELATION_CHILD_ID_FIELD] != DELETED_OBJECT_ID for item in instances)


def test_instances_carry_the_objects_real_type_ids(
    relations_collection, object_relations_collection,
) -> None:
    """Each instance's parent/child type ids come from the linked objects, not from a default"""
    instances = _migrated_instances(relations_collection, object_relations_collection)
    by_pair = {
        (item[RELATION_PARENT_ID_FIELD], item[RELATION_CHILD_ID_FIELD]): item for item in instances
    }

    first = by_pair[(OBJECT_A_ID, OBJECT_B_ID)]
    second = by_pair[(OBJECT_B_ID, OBJECT_C_ID)]

    assert (first[RELATION_PARENT_TYPE_ID_FIELD], first[RELATION_CHILD_TYPE_ID_FIELD]) == (TYPE_A_ID, TYPE_B_ID)
    assert (second[RELATION_PARENT_TYPE_ID_FIELD], second[RELATION_CHILD_TYPE_ID_FIELD]) == (TYPE_B_ID, TYPE_A_ID)


def test_instances_are_attributed_to_the_migration_author(
    relations_collection, object_relations_collection,
) -> None:
    """Every migrated instance records the bootstrap admin and no field values"""
    instances = _migrated_instances(relations_collection, object_relations_collection)

    assert all(item[AUTHOR_ID_FIELD] == MIGRATION_AUTHOR_ID for item in instances)
    assert all(item[FIELD_VALUES_FIELD] == [] for item in instances)
    assert all(isinstance(item[CREATION_TIME_FIELD], datetime) for item in instances)


def test_instances_got_distinct_public_ids(relations_collection, object_relations_collection) -> None:
    """The reserved ids are stamped 1:1 - no duplicates, no missing id"""
    instances = _migrated_instances(relations_collection, object_relations_collection)

    public_ids = [item[PUBLIC_ID_FIELD] for item in instances]

    assert len(set(public_ids)) == len(instances)
    assert all(isinstance(public_id, int) for public_id in public_ids)


def test_the_legacy_collection_is_kept(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The migration is one-way but non-destructive: the legacy links survive"""
    links = database_manager.get_collection(OBJECT_LINK_COLLECTION, database_name)

    assert links.count_documents({}) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                              VERSION + IDEMPOTENCY                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_persisted_updater_version_is_bumped(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The settings document records the migration version"""
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == UPDATER_VERSION


def test_a_second_run_duplicates_nothing(
    database_manager: MongoDatabaseManager,
    database_name: str,
    relations_collection,
    object_relations_collection,
) -> None:
    """Re-running reuses the relation and skips every already-migrated pair (the dedup claim)"""
    relation_before = _mapper_relation(relations_collection)
    instances_before = _migrated_instances(relations_collection, object_relations_collection)

    Update20260226(database_manager, database_name).start_update()

    relation_after = _mapper_relation(relations_collection)
    instances_after = _migrated_instances(relations_collection, object_relations_collection)

    assert relations_collection.count_documents({RELATION_NAME_FIELD: MAPPER_RELATION_NAME}) == 1
    assert relation_after == relation_before
    assert sorted(instances_after, key=lambda item: item[PUBLIC_ID_FIELD]) == \
           sorted(instances_before, key=lambda item: item[PUBLIC_ID_FIELD])


# -------------------------------------------------------------------------------------------------------------------- #
#                                        RE-RUN AFTER A CRASHED RUN                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
# A crash anywhere before the final version bump repeats the whole migration over whatever the crashed
# run committed. These tests reproduce the two states such a crash can leave and assert the re-run
# converges on the same end state. They rebuild the migrated data themselves, so they run last and
# restore it for nobody - the module fixture cleans up either way
class TestReRunAfterCrash:
    """The migration re-entered on top of a partially written run."""

    @staticmethod
    def _reset_to(relations_collection, object_relations_collection, keep_pairs: list[tuple[int, int]]):
        """Drops the migrated instances except the given pairs, leaving the relation in place."""
        relation = _mapper_relation(relations_collection)
        criteria: dict[str, Any] = {RELATION_ID_FIELD: relation[PUBLIC_ID_FIELD]}

        if keep_pairs:
            criteria['$nor'] = [
                {RELATION_PARENT_ID_FIELD: parent, RELATION_CHILD_ID_FIELD: child}
                for parent, child in keep_pairs
            ]

        object_relations_collection.delete_many(criteria)

        return relation

    def test_relation_without_instances_is_completed(
        self,
        database_manager: MongoDatabaseManager,
        database_name: str,
        relations_collection,
        object_relations_collection,
    ) -> None:
        """Crashed right after creating the relation: the re-run adopts it and writes every instance"""
        relation_before = self._reset_to(relations_collection, object_relations_collection, [])

        assert _migrated_instances(relations_collection, object_relations_collection) == []

        Update20260226(database_manager, database_name).start_update()

        instances = _migrated_instances(relations_collection, object_relations_collection)
        pairs = {(item[RELATION_PARENT_ID_FIELD], item[RELATION_CHILD_ID_FIELD]) for item in instances}

        assert pairs == {(OBJECT_A_ID, OBJECT_B_ID), (OBJECT_B_ID, OBJECT_C_ID)}
        assert relations_collection.count_documents({RELATION_NAME_FIELD: MAPPER_RELATION_NAME}) == 1
        assert _mapper_relation(relations_collection) == relation_before

    def test_half_written_batch_is_completed_without_touching_the_existing_instance(
        self,
        database_manager: MongoDatabaseManager,
        database_name: str,
        relations_collection,
        object_relations_collection,
    ) -> None:
        """Crashed mid-insert: only the missing pair is added, the written one stays byte-identical"""
        self._reset_to(relations_collection, object_relations_collection, [(OBJECT_A_ID, OBJECT_B_ID)])

        kept_before = _migrated_instances(relations_collection, object_relations_collection)
        assert len(kept_before) == 1

        Update20260226(database_manager, database_name).start_update()

        instances = _migrated_instances(relations_collection, object_relations_collection)
        by_pair = {
            (item[RELATION_PARENT_ID_FIELD], item[RELATION_CHILD_ID_FIELD]): item for item in instances
        }

        assert set(by_pair) == {(OBJECT_A_ID, OBJECT_B_ID), (OBJECT_B_ID, OBJECT_C_ID)}
        assert by_pair[(OBJECT_A_ID, OBJECT_B_ID)] == kept_before[0]

    def test_a_duplicated_legacy_link_yields_one_instance(
        self,
        database_manager: MongoDatabaseManager,
        database_name: str,
        relations_collection,
        object_relations_collection,
    ) -> None:
        """A pair duplicated in the source collection is migrated once, on a fresh run"""
        links = database_manager.get_collection(OBJECT_LINK_COLLECTION, database_name)
        relation = _mapper_relation(relations_collection)

        # Start from a relation with no instances and a source collection holding the same pair twice
        object_relations_collection.delete_many({RELATION_ID_FIELD: relation[PUBLIC_ID_FIELD]})
        links.delete_many({})
        links.insert_many([_link_doc(OBJECT_A_ID, OBJECT_B_ID), _link_doc(OBJECT_A_ID, OBJECT_B_ID)])

        Update20260226(database_manager, database_name).start_update()

        instances = _migrated_instances(relations_collection, object_relations_collection)

        assert len(instances) == 1
        assert (instances[0][RELATION_PARENT_ID_FIELD], instances[0][RELATION_CHILD_ID_FIELD]) == \
               (OBJECT_A_ID, OBJECT_B_ID)
