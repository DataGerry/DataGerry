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
Integration tests for the CmdbObjectRelation CRUD surface of ObjectRelationsManager

Pins the manager-layer behavior against a real MongoDB instance:

- insert / get / update / delete round-trip through the bound collection
- iterate honours BuilderParameters and returns model-bound results
- update_object_relation pins the identity (a forged payload public_id cannot rewrite the doc)
- get_related_relations matches the object on either the parent or child id
- delete_invalidated_object_relations removes the matching rows in a single server-side delete
- update_changed_fields removes / appends field_values in one pipeline update, scoped to the
  relation and a no-op when nothing changed
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 88001
OTHER_RELATION_ID: int = 88002

PARENT_TYPE_ID: int = 1
CHILD_TYPE_ID: int = 2
REMOVED_TYPE_ID: int = 9

OR_ID_FOR_INSERT: int = 88101
OR_ID_FOR_GET: int = 88102
OR_ID_FOR_UPDATE: int = 88103
OR_ID_FOR_PIN: int = 88104
OR_ID_FOR_DELETE: int = 88105
OR_ID_FOR_ITERATE_A: int = 88106
OR_ID_FOR_ITERATE_B: int = 88107
OR_ID_FOR_RELATED: int = 88108
OR_ID_FOR_INVALIDATE: int = 88109
OR_ID_FOR_KEEP: int = 88110
OR_ID_FOR_FIELDS_A: int = 88111
OR_ID_FOR_FIELDS_B: int = 88112
OR_ID_FOR_FIELDS_OTHER: int = 88113

FORGED_PUBLIC_ID: int = 88999
MISSING_OR_ID: int = 88900

PARENT_OBJECT_ID: int = 700
CHILD_OBJECT_ID: int = 800

ALL_OR_IDS: list[int] = [
    OR_ID_FOR_INSERT, OR_ID_FOR_GET, OR_ID_FOR_UPDATE, OR_ID_FOR_PIN, OR_ID_FOR_DELETE,
    OR_ID_FOR_ITERATE_A, OR_ID_FOR_ITERATE_B, OR_ID_FOR_RELATED, OR_ID_FOR_INVALIDATE,
    OR_ID_FOR_KEEP, OR_ID_FOR_FIELDS_A, OR_ID_FOR_FIELDS_B, OR_ID_FOR_FIELDS_OTHER,
    FORGED_PUBLIC_ID,
]


def _object_relation_data(
    public_id: int,
    relation_id: int = RELATION_ID,
    parent_id: int = PARENT_OBJECT_ID,
    child_id: int = CHILD_OBJECT_ID,
    parent_type_id: int = PARENT_TYPE_ID,
    child_type_id: int = CHILD_TYPE_ID,
    field_values: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a CmdbObjectRelation payload acceptable to ``insert_object_relation``."""
    return {
        'public_id': public_id,
        'relation_id': relation_id,
        'relation_parent_id': parent_id,
        'relation_parent_type_id': parent_type_id,
        'relation_child_id': child_id,
        'relation_child_type_id': child_type_id,
        'author_id': 1,
        'field_values': field_values if field_values is not None else [],
    }


def _delete_by_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes a set of CmdbObjectRelation docs directly via the collection."""
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _delete_by_ids(database_manager, database_name, ALL_OR_IDS)


@pytest.fixture(name='object_relations_manager')
def fixture_object_relations_manager(database_manager: MongoDatabaseManager) -> ObjectRelationsManager:
    """Provides an ObjectRelationsManager wired to the test database."""
    return ObjectRelationsManager(database_manager)


# ------------------------------------------------------- INSERT ----------------------------------------------------- #

class TestInsertObjectRelation:
    """``insert_object_relation`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        object_relations_manager: ObjectRelationsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_INSERT))

            assert returned_id == OR_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .find_one({'public_id': OR_ID_FOR_INSERT})
            assert stored is not None
            assert stored['relation_id'] == RELATION_ID
        finally:
            _delete_by_ids(database_manager, database_name, [OR_ID_FOR_INSERT])


# --------------------------------------------------------- GET ------------------------------------------------------ #

class TestGetObjectRelation:
    """``get_object_relation`` returns the doc as a dict or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed_one(self, object_relations_manager, database_manager, database_name):
        object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_GET))
        yield
        _delete_by_ids(database_manager, database_name, [OR_ID_FOR_GET])

    def test_returns_dict_for_existing_id(self, object_relations_manager: ObjectRelationsManager) -> None:
        """An existing id returns the raw document as a dict."""
        result = object_relations_manager.get_object_relation(OR_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == OR_ID_FOR_GET

    def test_returns_none_for_missing_id(self, object_relations_manager: ObjectRelationsManager) -> None:
        """A missing id returns None rather than raising (GenericManager.get_item contract)."""
        assert object_relations_manager.get_object_relation(MISSING_OR_ID) is None


# ------------------------------------------------------- UPDATE ----------------------------------------------------- #

class TestUpdateObjectRelation:
    """``update_object_relation`` writes the new payload and pins the identity."""

    def test_persists_changes_with_dict_payload(
        self, object_relations_manager, database_manager, database_name,
    ) -> None:
        """A dict payload is written through and the new field value is observable on read."""
        try:
            object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_UPDATE))

            updated = _object_relation_data(OR_ID_FOR_UPDATE, field_values=[{'name': 'a', 'value': 'changed'}])
            object_relations_manager.update_object_relation(OR_ID_FOR_UPDATE, updated)

            stored = object_relations_manager.get_object_relation(OR_ID_FOR_UPDATE)
            assert stored is not None
            assert stored['field_values'] == [{'name': 'a', 'value': 'changed'}]
        finally:
            _delete_by_ids(database_manager, database_name, [OR_ID_FOR_UPDATE])

    def test_forged_public_id_does_not_rewrite_identity(
        self, object_relations_manager, database_manager, database_name,
    ) -> None:
        """A payload public_id different from the URL id must not rewrite the stored id."""
        try:
            object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_PIN))

            forged = _object_relation_data(FORGED_PUBLIC_ID)  # body carries a different public_id
            object_relations_manager.update_object_relation(OR_ID_FOR_PIN, forged)

            assert object_relations_manager.get_object_relation(OR_ID_FOR_PIN) is not None
            assert object_relations_manager.get_object_relation(FORGED_PUBLIC_ID) is None
        finally:
            _delete_by_ids(database_manager, database_name, [OR_ID_FOR_PIN, FORGED_PUBLIC_ID])


# ------------------------------------------------------- DELETE ----------------------------------------------------- #

class TestDeleteObjectRelation:
    """``delete_object_relation`` removes the doc; a follow-up get returns None."""

    def test_removes_doc(self, object_relations_manager, database_manager, database_name) -> None:
        """Deleting an existing object relation makes it unretrievable."""
        object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_DELETE))

        object_relations_manager.delete_object_relation(OR_ID_FOR_DELETE)

        assert object_relations_manager.get_object_relation(OR_ID_FOR_DELETE) is None
        _delete_by_ids(database_manager, database_name, [OR_ID_FOR_DELETE])


# ------------------------------------------------------- ITERATE ---------------------------------------------------- #

class TestIterateObjectRelations:
    """``iterate`` returns model-bound results and the matching total."""

    def test_returns_inserted_rows_as_instances(
        self, object_relations_manager, database_manager, database_name,
    ) -> None:
        """Two inserted rows show up as ``CmdbObjectRelation`` instances in the IterationResult."""
        seeded = [OR_ID_FOR_ITERATE_A, OR_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                object_relations_manager.insert_object_relation(_object_relation_data(public_id))

            params = BuilderParameters(criteria={'public_id': {'$in': seeded}}, sort='public_id', order=1)
            iteration_result = object_relations_manager.iterate(params)

            assert iteration_result.total == len(seeded)
            assert [o.public_id for o in iteration_result.results] == seeded
            assert all(isinstance(o, CmdbObjectRelation) for o in iteration_result.results)
        finally:
            _delete_by_ids(database_manager, database_name, seeded)


# ------------------------------------------------- GET_RELATED_RELATIONS -------------------------------------------- #

class TestGetRelatedRelations:
    """``get_related_relations`` matches the object as parent or child."""

    def test_matches_object_as_parent_or_child(
        self, object_relations_manager, database_manager, database_name,
    ) -> None:
        """An object relation is returned whether the object is its parent or its child."""
        try:
            # OR_ID_FOR_RELATED has PARENT_OBJECT_ID as parent
            object_relations_manager.insert_object_relation(_object_relation_data(OR_ID_FOR_RELATED))
            # OR_ID_FOR_KEEP has PARENT_OBJECT_ID as child
            object_relations_manager.insert_object_relation(
                _object_relation_data(OR_ID_FOR_KEEP, parent_id=CHILD_OBJECT_ID, child_id=PARENT_OBJECT_ID)
            )

            related = object_relations_manager.get_related_relations(PARENT_OBJECT_ID)

            related_ids = {r['public_id'] for r in related}
            assert {OR_ID_FOR_RELATED, OR_ID_FOR_KEEP} <= related_ids
        finally:
            _delete_by_ids(database_manager, database_name, [OR_ID_FOR_RELATED, OR_ID_FOR_KEEP])


# --------------------------------------------- DELETE_INVALIDATED_OBJECT_RELATIONS ---------------------------------- #

class TestDeleteInvalidatedObjectRelations:
    """``delete_invalidated_object_relations`` removes matching rows in one server-side delete."""

    def test_removes_only_matching_parent_type(
        self, object_relations_manager, database_manager, database_name,
    ) -> None:
        """Rows of the relation whose parent type is invalidated are removed; others are kept."""
        try:
            # Invalid row: relation RELATION_ID with the removed parent type
            object_relations_manager.insert_object_relation(
                _object_relation_data(OR_ID_FOR_INVALIDATE, parent_type_id=REMOVED_TYPE_ID)
            )
            # Kept row: same relation but a still-valid parent type
            object_relations_manager.insert_object_relation(
                _object_relation_data(OR_ID_FOR_KEEP, parent_type_id=PARENT_TYPE_ID)
            )

            object_relations_manager.delete_invalidated_object_relations(RELATION_ID, [REMOVED_TYPE_ID], True)

            assert object_relations_manager.get_object_relation(OR_ID_FOR_INVALIDATE) is None
            assert object_relations_manager.get_object_relation(OR_ID_FOR_KEEP) is not None
        finally:
            _delete_by_ids(database_manager, database_name, [OR_ID_FOR_INVALIDATE, OR_ID_FOR_KEEP])


# ------------------------------------------------- UPDATE_CHANGED_FIELDS -------------------------------------------- #

class TestUpdateChangedFields:
    """``update_changed_fields`` rewrites field_values in one pipeline update, scoped to the relation."""

    @pytest.fixture(autouse=True)
    def _seed_fields(self, object_relations_manager, database_manager, database_name):
        """Two rows on RELATION_ID and one on OTHER_RELATION_ID, each carrying an 'old' field value."""
        object_relations_manager.insert_object_relation(
            _object_relation_data(OR_ID_FOR_FIELDS_A, field_values=[{'name': 'old', 'value': 'v1'}])
        )
        object_relations_manager.insert_object_relation(
            _object_relation_data(OR_ID_FOR_FIELDS_B, field_values=[{'name': 'old', 'value': 'v2'}])
        )
        object_relations_manager.insert_object_relation(
            _object_relation_data(
                OR_ID_FOR_FIELDS_OTHER, relation_id=OTHER_RELATION_ID,
                field_values=[{'name': 'old', 'value': 'v3'}],
            )
        )
        yield
        _delete_by_ids(database_manager, database_name,
                       [OR_ID_FOR_FIELDS_A, OR_ID_FOR_FIELDS_B, OR_ID_FOR_FIELDS_OTHER])

    def test_removes_and_appends_fields_for_relation_only(
        self, object_relations_manager: ObjectRelationsManager,
    ) -> None:
        """'old' is dropped and 'new' appended (value None) for both rows on the target relation."""
        object_relations_manager.update_changed_fields(RELATION_ID, {'added': ['new'], 'removed': ['old']})

        for public_id in (OR_ID_FOR_FIELDS_A, OR_ID_FOR_FIELDS_B):
            stored = object_relations_manager.get_object_relation(public_id)
            assert stored is not None
            names = {fv['name'] for fv in stored['field_values']}
            assert names == {'new'}
            assert stored['field_values'] == [{'name': 'new', 'value': None}]

    def test_leaves_other_relations_untouched(
        self, object_relations_manager: ObjectRelationsManager,
    ) -> None:
        """A row belonging to a different relation keeps its original field_values."""
        object_relations_manager.update_changed_fields(RELATION_ID, {'added': ['new'], 'removed': ['old']})

        other = object_relations_manager.get_object_relation(OR_ID_FOR_FIELDS_OTHER)
        assert other is not None
        assert other['field_values'] == [{'name': 'old', 'value': 'v3'}]

    def test_no_change_is_a_noop(self, object_relations_manager: ObjectRelationsManager) -> None:
        """An empty diff leaves the existing field_values intact."""
        object_relations_manager.update_changed_fields(RELATION_ID, {'added': [], 'removed': []})

        stored = object_relations_manager.get_object_relation(OR_ID_FOR_FIELDS_A)
        assert stored is not None
        assert stored['field_values'] == [{'name': 'old', 'value': 'v1'}]
