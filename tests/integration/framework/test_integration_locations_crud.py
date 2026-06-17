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
Integration tests for the CmdbLocation CRUD surface of LocationsManager

Pins the manager-layer behavior against a real MongoDB instance:

- insert / get / get_for_object / update / delete round-trip through the bound collection
- get_locations_by filters by parent and returns model-bound results
- update_locations_by_type bulk-updates only the matching type and leaves others untouched
- delete_locations removes a batch via a single ``$in`` raw delete
- get_all_descendant_locations resolves the full subtree with a real ``$graphLookup`` (the
  query that the unit suite can only mock) - including the multi-level chain, exclusion of
  unrelated branches, and cycle-safety for a malformed parent loop
- get_child_locations_object_ids maps an object's subtree to the descendants' object_ids
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.locations_manager import LocationsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.location_model.cmdb_location import CmdbLocation
# -------------------------------------------------------------------------------------------------------------------- #

ORDER_ASCENDING: int = 1

TYPE_ID: int = 9750
OTHER_TYPE_ID: int = 9751
TYPE_LABEL: str = 'Integration Location Type'

LOCATION_ID_FOR_INSERT: int = 9760
OBJECT_ID_FOR_INSERT: int = 9860

LOCATION_ID_FOR_GET: int = 9761
OBJECT_ID_FOR_GET: int = 9861

LOCATION_ID_FOR_UPDATE: int = 9762
OBJECT_ID_FOR_UPDATE: int = 9862

LOCATION_ID_FOR_DELETE: int = 9763
OBJECT_ID_FOR_DELETE: int = 9863

PARENT_LOCATION_ID: int = 9764
CHILD_A_LOCATION_ID: int = 9765
CHILD_B_LOCATION_ID: int = 9766

BULK_TYPE_LOCATION_A: int = 9767
BULK_TYPE_LOCATION_B: int = 9768
BULK_TYPE_LOCATION_OTHER: int = 9769

CHAIN_ROOT_ID: int = 9770
CHAIN_MID_ID: int = 9771
CHAIN_LEAF_ID: int = 9772
CHAIN_UNRELATED_ID: int = 9773
CHAIN_ROOT_OBJECT_ID: int = 9970
CHAIN_MID_OBJECT_ID: int = 9971
CHAIN_LEAF_OBJECT_ID: int = 9972

CYCLE_A_ID: int = 9774
CYCLE_B_ID: int = 9775

DELETE_BATCH_A_ID: int = 9776
DELETE_BATCH_B_ID: int = 9777

ITERATE_A_ID: int = 9778
ITERATE_B_ID: int = 9779
ITERATE_A_OBJECT_ID: int = 9978
ITERATE_B_OBJECT_ID: int = 9979

ROOT_PARENT_ID: int = 1
MISSING_LOCATION_ID: int = 9799

ORIGINAL_NAME: str = 'Original Location'
UPDATED_NAME: str = 'Updated Location'

ALL_SEED_IDS: list[int] = [
    LOCATION_ID_FOR_INSERT, LOCATION_ID_FOR_GET, LOCATION_ID_FOR_UPDATE, LOCATION_ID_FOR_DELETE,
    PARENT_LOCATION_ID, CHILD_A_LOCATION_ID, CHILD_B_LOCATION_ID,
    BULK_TYPE_LOCATION_A, BULK_TYPE_LOCATION_B, BULK_TYPE_LOCATION_OTHER,
    CHAIN_ROOT_ID, CHAIN_MID_ID, CHAIN_LEAF_ID, CHAIN_UNRELATED_ID,
    CYCLE_A_ID, CYCLE_B_ID, DELETE_BATCH_A_ID, DELETE_BATCH_B_ID,
    ITERATE_A_ID, ITERATE_B_ID,
]


def _location_doc(
    public_id: int,
    object_id: int,
    parent: int,
    type_id: int = TYPE_ID,
    name: str = ORIGINAL_NAME,
) -> dict[str, Any]:
    """Builds a complete CmdbLocation doc for direct DB insertion / manager insert."""
    return {
        'public_id': public_id,
        'name': name,
        'parent': parent,
        'object_id': object_id,
        'type_id': type_id,
        'type_label': TYPE_LABEL,
        'type_icon': 'fas fa-cube',
        'type_selectable': True,
    }


@pytest.fixture(name='locations_manager')
def fixture_locations_manager(database_manager: MongoDatabaseManager) -> LocationsManager:
    """Provides a LocationsManager wired to the test database."""
    return LocationsManager(database_manager)


def _insert_docs(database_manager: MongoDatabaseManager, database_name: str, docs: list[dict[str, Any]]) -> None:
    """Inserts CmdbLocation docs directly via the collection."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_many(docs)


def _drop_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes CmdbLocation docs directly via the collection."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed CmdbLocation docs after the module's tests have run."""
    yield
    _drop_ids(database_manager, database_name, ALL_SEED_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   INSERT / GET                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertAndGet:
    """``insert_location`` persists a row; ``get_location`` / ``get_location_for_object`` read it back."""

    def test_insert_persists_and_is_retrievable(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A dict insert persists a row retrievable by both public_id and object_id."""
        try:
            returned_id = locations_manager.insert_location(
                _location_doc(LOCATION_ID_FOR_INSERT, OBJECT_ID_FOR_INSERT, ROOT_PARENT_ID)
            )

            assert returned_id == LOCATION_ID_FOR_INSERT
            assert locations_manager.get_location(LOCATION_ID_FOR_INSERT) is not None
            by_object = locations_manager.get_location_for_object(OBJECT_ID_FOR_INSERT)
            assert by_object is not None and by_object['public_id'] == LOCATION_ID_FOR_INSERT
        finally:
            _drop_ids(database_manager, database_name, [LOCATION_ID_FOR_INSERT])

    def test_get_location_returns_none_for_missing_id(self, locations_manager: LocationsManager) -> None:
        """A missing public_id returns None rather than raising."""
        assert locations_manager.get_location(MISSING_LOCATION_ID) is None

    def test_get_location_for_object_returns_none_for_missing_object(
        self, locations_manager: LocationsManager,
    ) -> None:
        """An object with no location returns None."""
        assert locations_manager.get_location_for_object(MISSING_LOCATION_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ITERATE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterate:
    """``iterate`` returns model-bound CmdbLocation results and the matching total."""

    def test_returns_filtered_rows_as_cmdb_location_instances(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A ``$in`` filtered, ascending-sorted iteration yields the seeded rows as CmdbLocation instances."""
        seeded = [ITERATE_A_ID, ITERATE_B_ID]
        _insert_docs(database_manager, database_name, [
            _location_doc(ITERATE_A_ID, ITERATE_A_OBJECT_ID, ROOT_PARENT_ID),
            _location_doc(ITERATE_B_ID, ITERATE_B_OBJECT_ID, ROOT_PARENT_ID),
        ])
        try:
            params = BuilderParameters(
                criteria={'public_id': {'$in': seeded}}, sort='public_id', order=ORDER_ASCENDING,
            )
            iteration_result = locations_manager.iterate(params)

            assert iteration_result.total == len(seeded)
            assert [loc.public_id for loc in iteration_result.results] == seeded
            assert all(isinstance(loc, CmdbLocation) for loc in iteration_result.results)
        finally:
            _drop_ids(database_manager, database_name, seeded)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  GET_LOCATIONS_BY                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetLocationsBy:
    """``get_locations_by`` filters by parent and hydrates each row to ``CmdbLocation``."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a parent and two children pointing at it."""
        _insert_docs(database_manager, database_name, [
            _location_doc(PARENT_LOCATION_ID, OBJECT_ID_FOR_GET, ROOT_PARENT_ID),
            _location_doc(CHILD_A_LOCATION_ID, OBJECT_ID_FOR_GET + 1, PARENT_LOCATION_ID),
            _location_doc(CHILD_B_LOCATION_ID, OBJECT_ID_FOR_GET + 2, PARENT_LOCATION_ID),
        ])
        yield
        _drop_ids(database_manager, database_name, [PARENT_LOCATION_ID, CHILD_A_LOCATION_ID, CHILD_B_LOCATION_ID])

    def test_returns_only_children_of_parent_as_instances(self, locations_manager: LocationsManager) -> None:
        """``parent=<id>`` returns exactly that parent's children as CmdbLocation instances."""
        children = locations_manager.get_locations_by(parent=PARENT_LOCATION_ID)

        assert {child.public_id for child in children} == {CHILD_A_LOCATION_ID, CHILD_B_LOCATION_ID}
        assert all(isinstance(child, CmdbLocation) for child in children)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateLocation:
    """``update_location`` writes by object_id; ``update_locations_by_type`` bulk-updates by type."""

    def test_update_location_by_object_id_persists(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An update keyed by object_id changes the persisted name."""
        _insert_docs(database_manager, database_name, [
            _location_doc(LOCATION_ID_FOR_UPDATE, OBJECT_ID_FOR_UPDATE, ROOT_PARENT_ID),
        ])
        try:
            locations_manager.update_location(OBJECT_ID_FOR_UPDATE, {'name': UPDATED_NAME})

            stored = locations_manager.get_location(LOCATION_ID_FOR_UPDATE)
            assert stored is not None and stored['name'] == UPDATED_NAME
        finally:
            _drop_ids(database_manager, database_name, [LOCATION_ID_FOR_UPDATE])

    def test_update_locations_by_type_touches_only_matching_type(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The bulk update changes every location of the type and leaves other types untouched."""
        _insert_docs(database_manager, database_name, [
            _location_doc(BULK_TYPE_LOCATION_A, OBJECT_ID_FOR_UPDATE + 10, ROOT_PARENT_ID, type_id=TYPE_ID),
            _location_doc(BULK_TYPE_LOCATION_B, OBJECT_ID_FOR_UPDATE + 11, ROOT_PARENT_ID, type_id=TYPE_ID),
            _location_doc(BULK_TYPE_LOCATION_OTHER, OBJECT_ID_FOR_UPDATE + 12, ROOT_PARENT_ID, type_id=OTHER_TYPE_ID),
        ])
        try:
            locations_manager.update_locations_by_type(TYPE_ID, {'type_label': UPDATED_NAME})

            assert locations_manager.get_location(BULK_TYPE_LOCATION_A)['type_label'] == UPDATED_NAME
            assert locations_manager.get_location(BULK_TYPE_LOCATION_B)['type_label'] == UPDATED_NAME
            assert locations_manager.get_location(BULK_TYPE_LOCATION_OTHER)['type_label'] == TYPE_LABEL
        finally:
            _drop_ids(
                database_manager, database_name,
                [BULK_TYPE_LOCATION_A, BULK_TYPE_LOCATION_B, BULK_TYPE_LOCATION_OTHER],
            )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteLocation:
    """``delete_location`` removes one row; ``delete_locations`` removes a batch."""

    def test_delete_location_removes_row(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting an existing location makes it unretrievable."""
        _insert_docs(database_manager, database_name, [
            _location_doc(LOCATION_ID_FOR_DELETE, OBJECT_ID_FOR_DELETE, ROOT_PARENT_ID),
        ])
        try:
            assert locations_manager.delete_location(LOCATION_ID_FOR_DELETE) is True
            assert locations_manager.get_location(LOCATION_ID_FOR_DELETE) is None
        finally:
            _drop_ids(database_manager, database_name, [LOCATION_ID_FOR_DELETE])

    def test_delete_locations_removes_the_whole_batch(
        self, locations_manager: LocationsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A batch delete removes every supplied location in a single operation."""
        _insert_docs(database_manager, database_name, [
            _location_doc(DELETE_BATCH_A_ID, OBJECT_ID_FOR_DELETE + 1, ROOT_PARENT_ID),
            _location_doc(DELETE_BATCH_B_ID, OBJECT_ID_FOR_DELETE + 2, ROOT_PARENT_ID),
        ])
        try:
            locations_manager.delete_locations([
                {'public_id': DELETE_BATCH_A_ID},
                {'public_id': DELETE_BATCH_B_ID},
            ])

            assert locations_manager.get_location(DELETE_BATCH_A_ID) is None
            assert locations_manager.get_location(DELETE_BATCH_B_ID) is None
        finally:
            _drop_ids(database_manager, database_name, [DELETE_BATCH_A_ID, DELETE_BATCH_B_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                  get_all_descendant_locations ($graphLookup)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetAllDescendantLocations:
    """``get_all_descendant_locations`` resolves the subtree via a real ``$graphLookup`` query."""

    @pytest.fixture(autouse=True)
    def _seed_chain(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a 3-deep chain (root <- mid <- leaf) plus an unrelated sibling root."""
        _insert_docs(database_manager, database_name, [
            _location_doc(CHAIN_ROOT_ID, CHAIN_ROOT_OBJECT_ID, ROOT_PARENT_ID),
            _location_doc(CHAIN_MID_ID, CHAIN_MID_OBJECT_ID, CHAIN_ROOT_ID),
            _location_doc(CHAIN_LEAF_ID, CHAIN_LEAF_OBJECT_ID, CHAIN_MID_ID),
            _location_doc(CHAIN_UNRELATED_ID, CHAIN_LEAF_OBJECT_ID + 1, ROOT_PARENT_ID),
        ])
        yield
        _drop_ids(database_manager, database_name, [CHAIN_ROOT_ID, CHAIN_MID_ID, CHAIN_LEAF_ID, CHAIN_UNRELATED_ID])

    def test_returns_all_descendants_excluding_self_and_unrelated(
        self, locations_manager: LocationsManager,
    ) -> None:
        """The multi-level subtree of the root resolves to mid + leaf, excluding self and siblings."""
        descendants = locations_manager.get_all_descendant_locations(CHAIN_ROOT_ID)

        descendant_ids = {loc['public_id'] for loc in descendants}
        assert descendant_ids == {CHAIN_MID_ID, CHAIN_LEAF_ID}

    def test_leaf_has_no_descendants(self, locations_manager: LocationsManager) -> None:
        """A leaf location resolves to an empty descendant set."""
        assert locations_manager.get_all_descendant_locations(CHAIN_LEAF_ID) == []

    def test_get_child_locations_object_ids_maps_subtree_to_object_ids(
        self, locations_manager: LocationsManager,
    ) -> None:
        """The object's subtree resolves to the descendants' object_ids (not the root's own)."""
        child_object_ids = locations_manager.get_child_locations_object_ids(CHAIN_ROOT_OBJECT_ID)

        assert set(child_object_ids) == {CHAIN_MID_OBJECT_ID, CHAIN_LEAF_OBJECT_ID}


class TestGetAllDescendantLocationsCycleSafety:
    """A malformed parent cycle must not hang $graphLookup; it terminates with a finite set."""

    @pytest.fixture(autouse=True)
    def _seed_cycle(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two locations that reference each other as parent (A <-> B)."""
        _insert_docs(database_manager, database_name, [
            _location_doc(CYCLE_A_ID, CYCLE_A_ID + 100, CYCLE_B_ID),
            _location_doc(CYCLE_B_ID, CYCLE_B_ID + 100, CYCLE_A_ID),
        ])
        yield
        _drop_ids(database_manager, database_name, [CYCLE_A_ID, CYCLE_B_ID])

    def test_cycle_terminates_with_finite_descendants(self, locations_manager: LocationsManager) -> None:
        """Resolving descendants of a cyclic node terminates and yields a deduplicated finite set."""
        descendants = locations_manager.get_all_descendant_locations(CYCLE_A_ID)

        descendant_ids = {loc['public_id'] for loc in descendants}
        assert descendant_ids == {CYCLE_A_ID, CYCLE_B_ID}
