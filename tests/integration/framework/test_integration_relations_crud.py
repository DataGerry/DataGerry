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
Integration tests for the CmdbRelation CRUD surface of RelationsManager

Pins the manager-layer behavior against a real MongoDB instance (the unit suite only asserts the
delegation to GenericManager with a mocked manager):

- insert / get / update / delete round-trip through the bound collection
- iterate honours BuilderParameters and returns model-bound results plus the matching total
- update_relation pins the identity (a forged payload public_id cannot rewrite the stored doc) and
  is a no-op for a missing id (the underlying update does not upsert)
- remove_type_from_relations pulls a type id from both the parent and child id lists in a single
  server-side update, scoped to the relations that reference it
- count_documents' limit really caps the count server-side, which is what the delete route's in-use
  probe relies on
- the route-level update cascade (cascade_relation_update) reconciles the dependent
  CmdbObjectRelations: instances of a no-longer-allowed type are deleted, the surviving ones gain and
  lose the field values the relation's sections gained and lost
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.relation_model import CmdbRelation, RelationDiffKey
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import cascade_relation_update
# -------------------------------------------------------------------------------------------------------------------- #

PARENT_TYPE_ID: int = 1
CHILD_TYPE_ID: int = 2
SHARED_TYPE_ID: int = 9
REMOVED_CHILD_TYPE_ID: int = 10

OBJ_REL_ID_KEPT: int = 76101
OBJ_REL_ID_INVALIDATED: int = 76102
ALL_OBJ_REL_IDS: list[int] = [OBJ_REL_ID_KEPT, OBJ_REL_ID_INVALIDATED]

REL_ID_FOR_INSERT: int = 77101
REL_ID_FOR_GET: int = 77102
REL_ID_FOR_UPDATE: int = 77103
REL_ID_FOR_PIN: int = 77104
REL_ID_FOR_DELETE: int = 77105
REL_ID_FOR_ITERATE_A: int = 77106
REL_ID_FOR_ITERATE_B: int = 77107
REL_ID_FOR_CASCADE: int = 77108
REL_ID_FOR_CASCADE_UNRELATED: int = 77109

FORGED_PUBLIC_ID: int = 77999
MISSING_REL_ID: int = 77900

ALL_REL_IDS: list[int] = [
    REL_ID_FOR_INSERT, REL_ID_FOR_GET, REL_ID_FOR_UPDATE, REL_ID_FOR_PIN, REL_ID_FOR_DELETE,
    REL_ID_FOR_ITERATE_A, REL_ID_FOR_ITERATE_B, REL_ID_FOR_CASCADE, REL_ID_FOR_CASCADE_UNRELATED,
    FORGED_PUBLIC_ID,
]


def _relation_data(
    public_id: int,
    relation_name: str = 'rel',
    parent_type_ids: list[int] | None = None,
    child_type_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Builds a CmdbRelation payload acceptable to ``insert_relation``."""
    return {
        'public_id': public_id,
        'relation_name': relation_name,
        'parent_type_ids': parent_type_ids if parent_type_ids is not None else [PARENT_TYPE_ID],
        'child_type_ids': child_type_ids if child_type_ids is not None else [CHILD_TYPE_ID],
        'relation_name_parent': 'is-parent-of',
        'relation_name_child': 'is-child-of',
        'sections': [],
        'fields': [],
    }


def _delete_by_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes a set of CmdbRelation docs directly via the collection."""
    database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _delete_by_ids(database_manager, database_name, ALL_REL_IDS)


@pytest.fixture(name='relations_manager')
def fixture_relations_manager(database_manager: MongoDatabaseManager) -> RelationsManager:
    """Provides a RelationsManager wired to the test database."""
    return RelationsManager(database_manager)


# ------------------------------------------------------- INSERT ----------------------------------------------------- #

class TestInsertRelation:
    """``insert_relation`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        relations_manager: RelationsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = relations_manager.insert_relation(_relation_data(REL_ID_FOR_INSERT))

            assert returned_id == REL_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .find_one({'public_id': REL_ID_FOR_INSERT})
            assert stored is not None
            assert stored['relation_name'] == 'rel'
        finally:
            _delete_by_ids(database_manager, database_name, [REL_ID_FOR_INSERT])


# --------------------------------------------------------- GET ------------------------------------------------------ #

class TestGetRelation:
    """``get_relation`` returns the doc as a dict or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed_one(self, relations_manager, database_manager, database_name):
        relations_manager.insert_relation(_relation_data(REL_ID_FOR_GET))
        yield
        _delete_by_ids(database_manager, database_name, [REL_ID_FOR_GET])

    def test_returns_dict_for_existing_id(self, relations_manager: RelationsManager) -> None:
        """An existing id returns the raw document as a dict."""
        result = relations_manager.get_relation(REL_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == REL_ID_FOR_GET

    def test_returns_none_for_missing_id(self, relations_manager: RelationsManager) -> None:
        """A missing id returns None rather than raising (GenericManager.get_item contract)."""
        assert relations_manager.get_relation(MISSING_REL_ID) is None


# ------------------------------------------------------- UPDATE ----------------------------------------------------- #

class TestUpdateRelation:
    """``update_relation`` writes the new payload and pins the identity to the url id."""

    def test_persists_changes_with_dict_payload(
        self, relations_manager, database_manager, database_name,
    ) -> None:
        """A dict payload is written through and the new value is observable on read."""
        try:
            relations_manager.insert_relation(_relation_data(REL_ID_FOR_UPDATE))

            relations_manager.update_relation(REL_ID_FOR_UPDATE, _relation_data(REL_ID_FOR_UPDATE, 'renamed'))

            stored = relations_manager.get_relation(REL_ID_FOR_UPDATE)
            assert stored is not None
            assert stored['relation_name'] == 'renamed'
        finally:
            _delete_by_ids(database_manager, database_name, [REL_ID_FOR_UPDATE])

    def test_forged_public_id_does_not_rewrite_identity(
        self, relations_manager, database_manager, database_name,
    ) -> None:
        """A payload public_id different from the url id must not rewrite the stored id."""
        try:
            relations_manager.insert_relation(_relation_data(REL_ID_FOR_PIN))

            forged = _relation_data(FORGED_PUBLIC_ID)  # body carries a different public_id
            relations_manager.update_relation(REL_ID_FOR_PIN, forged)

            assert relations_manager.get_relation(REL_ID_FOR_PIN) is not None
            assert relations_manager.get_relation(FORGED_PUBLIC_ID) is None
        finally:
            _delete_by_ids(database_manager, database_name, [REL_ID_FOR_PIN, FORGED_PUBLIC_ID])

    def test_update_missing_id_is_a_noop(
        self, relations_manager, database_manager, database_name,
    ) -> None:
        """Updating an id that does not exist neither raises nor upserts a new doc."""
        relations_manager.update_relation(MISSING_REL_ID, _relation_data(MISSING_REL_ID))

        assert relations_manager.get_relation(MISSING_REL_ID) is None
        _delete_by_ids(database_manager, database_name, [MISSING_REL_ID])


# ------------------------------------------------------- DELETE ----------------------------------------------------- #

class TestDeleteRelation:
    """``delete_relation`` removes the doc; a follow-up get returns None."""

    def test_removes_doc(self, relations_manager, database_manager, database_name) -> None:
        """Deleting an existing relation makes it unretrievable."""
        relations_manager.insert_relation(_relation_data(REL_ID_FOR_DELETE))

        assert relations_manager.delete_relation(REL_ID_FOR_DELETE) is True
        assert relations_manager.get_relation(REL_ID_FOR_DELETE) is None
        _delete_by_ids(database_manager, database_name, [REL_ID_FOR_DELETE])


# ------------------------------------------------------- ITERATE ---------------------------------------------------- #

class TestIterateRelations:
    """``iterate`` returns model-bound results and the matching total."""

    def test_returns_inserted_rows_as_instances(
        self, relations_manager, database_manager, database_name,
    ) -> None:
        """Two inserted rows show up as ``CmdbRelation`` instances in the IterationResult."""
        seeded = [REL_ID_FOR_ITERATE_A, REL_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                relations_manager.insert_relation(_relation_data(public_id))

            params = BuilderParameters(criteria={'public_id': {'$in': seeded}}, sort='public_id', order=1)
            iteration_result = relations_manager.iterate(params)

            assert iteration_result.total == len(seeded)
            assert [relation.public_id for relation in iteration_result.results] == seeded
            assert all(isinstance(relation, CmdbRelation) for relation in iteration_result.results)
        finally:
            _delete_by_ids(database_manager, database_name, seeded)


# ----------------------------------------------- remove_type_from_relations ----------------------------------------- #

class TestRemoveTypeFromRelations:
    """``remove_type_from_relations`` pulls a type id from both id lists, scoped to its referrers."""

    def test_pulls_type_id_from_parent_and_child_lists(
        self, relations_manager, database_manager, database_name,
    ) -> None:
        """The shared type id is pulled from both lists of the referring relation only."""
        seeded = [REL_ID_FOR_CASCADE, REL_ID_FOR_CASCADE_UNRELATED]
        try:
            relations_manager.insert_relation(_relation_data(
                REL_ID_FOR_CASCADE,
                parent_type_ids=[PARENT_TYPE_ID, SHARED_TYPE_ID],
                child_type_ids=[CHILD_TYPE_ID, SHARED_TYPE_ID],
            ))
            relations_manager.insert_relation(_relation_data(REL_ID_FOR_CASCADE_UNRELATED))

            relations_manager.remove_type_from_relations(SHARED_TYPE_ID)

            touched = relations_manager.get_relation(REL_ID_FOR_CASCADE)
            assert touched['parent_type_ids'] == [PARENT_TYPE_ID]
            assert touched['child_type_ids'] == [CHILD_TYPE_ID]

            untouched = relations_manager.get_relation(REL_ID_FOR_CASCADE_UNRELATED)
            assert untouched['parent_type_ids'] == [PARENT_TYPE_ID]
            assert untouched['child_type_ids'] == [CHILD_TYPE_ID]
        finally:
            _delete_by_ids(database_manager, database_name, seeded)


# ------------------------------------------------- in-use probe (count) --------------------------------------------- #

class TestCountDocumentsLimit:
    """``count_documents`` caps the count server-side, which the delete route's in-use probe uses."""

    def test_limit_caps_the_count(
        self, relations_manager: RelationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Two matching docs with limit=1 report 1, so the probe stops at the first hit."""
        seeded = [REL_ID_FOR_ITERATE_A, REL_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                relations_manager.insert_relation(_relation_data(public_id, relation_name='probe'))

            criteria: dict[str, Any] = {'relation_name': 'probe'}

            assert relations_manager.count_documents(criteria) == 2
            assert relations_manager.count_documents(criteria, limit=1) == 1
        finally:
            _delete_by_ids(database_manager, database_name, seeded)

    def test_reports_zero_without_a_match(self, relations_manager: RelationsManager) -> None:
        """A criteria nothing matches counts 0 even with a limit (the 'not in use' case)."""
        assert relations_manager.count_documents({'public_id': MISSING_REL_ID}, limit=1) == 0


# --------------------------------------------- cascade_relation_update ---------------------------------------------- #

class TestCascadeRelationUpdate:
    """The route-level cascade reconciles the CmdbObjectRelations of an updated CmdbRelation."""

    @pytest.fixture(name='object_relations_manager')
    def fixture_object_relations_manager(
        self, database_manager: MongoDatabaseManager,
    ) -> ObjectRelationsManager:
        """Provides an ObjectRelationsManager wired to the test database."""
        return ObjectRelationsManager(database_manager)

    @staticmethod
    def _object_relation(public_id: int, child_type_id: int, field_names: list[str]) -> dict[str, Any]:
        """Builds a stored CmdbObjectRelation of the cascaded relation."""
        return {
            ObjectRelationKey.PUBLIC_ID.value: public_id,
            ObjectRelationKey.RELATION_ID.value: REL_ID_FOR_CASCADE,
            ObjectRelationKey.RELATION_PARENT_ID.value: 1,
            ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: PARENT_TYPE_ID,
            ObjectRelationKey.RELATION_CHILD_ID.value: 2,
            ObjectRelationKey.RELATION_CHILD_TYPE_ID.value: child_type_id,
            ObjectRelationKey.FIELD_VALUES.value: [{'name': name, 'value': name} for name in field_names],
        }

    def test_deletes_invalidated_instances_and_applies_the_field_diff(
        self,
        object_relations_manager: ObjectRelationsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The instance of the dropped child type goes; the surviving one loses 'a' and gains 'b'."""
        object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
        object_relations.insert_many([
            self._object_relation(OBJ_REL_ID_KEPT, CHILD_TYPE_ID, ['a']),
            self._object_relation(OBJ_REL_ID_INVALIDATED, REMOVED_CHILD_TYPE_ID, ['a']),
        ])
        try:
            old_relation = _relation_data(
                REL_ID_FOR_CASCADE, child_type_ids=[CHILD_TYPE_ID, REMOVED_CHILD_TYPE_ID],
            )
            new_relation = _relation_data(REL_ID_FOR_CASCADE, child_type_ids=[CHILD_TYPE_ID])
            changed_fields = {RelationDiffKey.ADDED.value: ['b'], RelationDiffKey.REMOVED.value: ['a']}

            cascade_relation_update(
                REL_ID_FOR_CASCADE, old_relation, new_relation, changed_fields, object_relations_manager,
            )

            assert object_relations.find_one({ObjectRelationKey.PUBLIC_ID.value: OBJ_REL_ID_INVALIDATED}) is None

            survivor = object_relations.find_one({ObjectRelationKey.PUBLIC_ID.value: OBJ_REL_ID_KEPT})
            field_names = [entry['name'] for entry in survivor[ObjectRelationKey.FIELD_VALUES.value]]
            assert field_names == ['b']
        finally:
            object_relations.delete_many({ObjectRelationKey.PUBLIC_ID.value: {'$in': ALL_OBJ_REL_IDS}})
