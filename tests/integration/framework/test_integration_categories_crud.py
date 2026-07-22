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
Integration tests for the CmdbCategory CRUD surface of CategoriesManager

Pins the manager-layer behavior against a real MongoDB instance:

- insert / get / update / delete round-trip through the bound collection
- iterate honours BuilderParameters and returns the model-bound results
- get_categories_by filters via the bound collection (post-S1-cleanup, uses get_many)
- remove_category_as_parent nulls the ``parent`` field on every child of a parent id and
  leaves unrelated rows untouched - this is the cascade that the new delete-route ordering
  depends on
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.categories_manager import CategoriesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.category_model import CmdbCategory
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID_FOR_INSERT: int = 9601
CATEGORY_ID_FOR_GET: int = 9602
CATEGORY_ID_FOR_UPDATE: int = 9603
CATEGORY_ID_FOR_DELETE: int = 9604
CATEGORY_ID_FOR_ITERATE_A: int = 9605
CATEGORY_ID_FOR_ITERATE_B: int = 9606
CATEGORY_ID_FOR_FILTER_PARENT: int = 9607
CATEGORY_ID_FOR_FILTER_CHILD_A: int = 9608
CATEGORY_ID_FOR_FILTER_CHILD_B: int = 9609
CATEGORY_ID_FOR_CASCADE_PARENT: int = 9610
CATEGORY_ID_FOR_CASCADE_CHILD_A: int = 9611
CATEGORY_ID_FOR_CASCADE_CHILD_B: int = 9612
CATEGORY_ID_FOR_CASCADE_UNRELATED: int = 9613
MISSING_CATEGORY_ID: int = 9699

ORIGINAL_LABEL: str = 'Original Label'
UPDATED_LABEL: str = 'Updated Label'

SEED_CATEGORY_IDS: list[int] = [
    CATEGORY_ID_FOR_INSERT,
    CATEGORY_ID_FOR_GET,
    CATEGORY_ID_FOR_UPDATE,
    CATEGORY_ID_FOR_DELETE,
    CATEGORY_ID_FOR_ITERATE_A,
    CATEGORY_ID_FOR_ITERATE_B,
    CATEGORY_ID_FOR_FILTER_PARENT,
    CATEGORY_ID_FOR_FILTER_CHILD_A,
    CATEGORY_ID_FOR_FILTER_CHILD_B,
    CATEGORY_ID_FOR_CASCADE_PARENT,
    CATEGORY_ID_FOR_CASCADE_CHILD_A,
    CATEGORY_ID_FOR_CASCADE_CHILD_B,
    CATEGORY_ID_FOR_CASCADE_UNRELATED,
]


def _category_data(
    public_id: int,
    name: str | None = None,
    label: str = ORIGINAL_LABEL,
    parent: int | None = None,
    types: list[int] | None = None,
) -> dict[str, Any]:
    """Builds a minimal CmdbCategory payload acceptable to ``CategoriesManager.insert_category``."""
    return {
        'public_id': public_id,
        'name': name if name is not None else f'int-test-cat-{public_id}',
        'label': label,
        'meta': {'icon': 'fa-folder', 'order': public_id},
        'parent': parent,
        'types': types or [],
    }


def _delete_category_by_id(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one CmdbCategory doc directly via the collection, used for per-test cleanup."""
    database_manager.get_collection(CmdbCategory.COLLECTION, database_name)\
        .delete_one({'public_id': public_id})


def _delete_categories_by_ids(
    database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int],
) -> None:
    """Removes a set of CmdbCategory docs directly via the collection."""
    database_manager.get_collection(CmdbCategory.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded_categories(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed CmdbCategory docs after the module's tests have run."""
    yield
    _delete_categories_by_ids(database_manager, database_name, SEED_CATEGORY_IDS)


@pytest.fixture(name='categories_manager')
def fixture_categories_manager(database_manager: MongoDatabaseManager) -> CategoriesManager:
    """Provides a CategoriesManager wired to the test database."""
    return CategoriesManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertCategory:
    """``insert_category`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_INSERT))

            assert returned_id == CATEGORY_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)\
                .find_one({'public_id': CATEGORY_ID_FOR_INSERT})
            assert stored is not None
            assert stored['label'] == ORIGINAL_LABEL
        finally:
            _delete_category_by_id(database_manager, database_name, CATEGORY_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                         GET                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCategory:
    """``get_category`` returns the doc as a dict or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single category before each test in this class and removes it after."""
        categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_GET))
        yield
        _delete_category_by_id(database_manager, database_name, CATEGORY_ID_FOR_GET)

    def test_returns_dict_for_existing_id(self, categories_manager: CategoriesManager) -> None:
        """An existing id returns the raw document as a dict."""
        result = categories_manager.get_category(CATEGORY_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == CATEGORY_ID_FOR_GET
        assert result['label'] == ORIGINAL_LABEL

    def test_returns_none_for_missing_id(self, categories_manager: CategoriesManager) -> None:
        """A missing id returns None rather than raising (GenericManager.get_item contract)."""
        assert categories_manager.get_category(MISSING_CATEGORY_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateCategory:
    """``update_category`` writes the new payload over the existing doc."""

    def test_persists_new_label_with_dict_payload(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A dict payload is written through ``update_item`` and the new label is observable on read."""
        try:
            categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_UPDATE))

            updated_payload = _category_data(CATEGORY_ID_FOR_UPDATE, label=UPDATED_LABEL)
            categories_manager.update_category(CATEGORY_ID_FOR_UPDATE, updated_payload)

            stored = categories_manager.get_category(CATEGORY_ID_FOR_UPDATE)
            assert stored is not None
            assert stored['label'] == UPDATED_LABEL
        finally:
            _delete_category_by_id(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCategory:
    """``delete_category`` removes the doc; a follow-up get returns None."""

    def test_removes_doc(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing category makes it unretrievable."""
        categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_DELETE))

        categories_manager.delete_category(CATEGORY_ID_FOR_DELETE)

        assert categories_manager.get_category(CATEGORY_ID_FOR_DELETE) is None
        # belt-and-braces cleanup in case delete_category semantics ever change
        _delete_category_by_id(database_manager, database_name, CATEGORY_ID_FOR_DELETE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ITERATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterateCategories:
    """``iterate`` returns model-bound results and the matching total."""

    def test_returns_inserted_rows_as_cmdb_category_instances(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Two inserted rows show up as ``CmdbCategory`` instances in the IterationResult."""
        seeded = [CATEGORY_ID_FOR_ITERATE_A, CATEGORY_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                categories_manager.insert_category(_category_data(public_id))

            params = BuilderParameters(criteria={'public_id': {'$in': seeded}}, sort='public_id', order=1)
            iteration_result = categories_manager.iterate(params)

            assert iteration_result.total == len(seeded)
            assert [c.public_id for c in iteration_result.results] == seeded
            assert all(isinstance(c, CmdbCategory) for c in iteration_result.results)
        finally:
            _delete_categories_by_ids(database_manager, database_name, seeded)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   GET_CATEGORIES_BY                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCategoriesBy:
    """``get_categories_by`` filters the bound collection and hydrates each row."""

    @pytest.fixture(autouse=True)
    def _seed_parent_and_children(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts one parent + two children; cleanup runs after each test."""
        categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_FILTER_PARENT))
        categories_manager.insert_category(
            _category_data(CATEGORY_ID_FOR_FILTER_CHILD_A, parent=CATEGORY_ID_FOR_FILTER_PARENT)
        )
        categories_manager.insert_category(
            _category_data(CATEGORY_ID_FOR_FILTER_CHILD_B, parent=CATEGORY_ID_FOR_FILTER_PARENT)
        )
        yield
        _delete_categories_by_ids(
            database_manager,
            database_name,
            [CATEGORY_ID_FOR_FILTER_PARENT, CATEGORY_ID_FOR_FILTER_CHILD_A, CATEGORY_ID_FOR_FILTER_CHILD_B],
        )

    def test_filters_by_parent_and_returns_only_children(
        self, categories_manager: CategoriesManager,
    ) -> None:
        """``parent=<id>`` returns exactly the children of that parent, as CmdbCategory instances."""
        children = categories_manager.get_categories_by(parent=CATEGORY_ID_FOR_FILTER_PARENT)

        child_ids = {c.public_id for c in children}
        assert child_ids == {CATEGORY_ID_FOR_FILTER_CHILD_A, CATEGORY_ID_FOR_FILTER_CHILD_B}
        assert all(isinstance(c, CmdbCategory) for c in children)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              REMOVE_CATEGORY_AS_PARENT                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemoveCategoryAsParent:
    """``remove_category_as_parent`` nulls the parent field on every child and leaves siblings alone."""

    @pytest.fixture(autouse=True)
    def _seed_cascade_fixture(
        self,
        categories_manager: CategoriesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a parent, two children pointing to it, and one unrelated category."""
        categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_CASCADE_PARENT))
        categories_manager.insert_category(
            _category_data(CATEGORY_ID_FOR_CASCADE_CHILD_A, parent=CATEGORY_ID_FOR_CASCADE_PARENT)
        )
        categories_manager.insert_category(
            _category_data(CATEGORY_ID_FOR_CASCADE_CHILD_B, parent=CATEGORY_ID_FOR_CASCADE_PARENT)
        )
        categories_manager.insert_category(_category_data(CATEGORY_ID_FOR_CASCADE_UNRELATED))
        yield
        _delete_categories_by_ids(
            database_manager,
            database_name,
            [
                CATEGORY_ID_FOR_CASCADE_PARENT,
                CATEGORY_ID_FOR_CASCADE_CHILD_A,
                CATEGORY_ID_FOR_CASCADE_CHILD_B,
                CATEGORY_ID_FOR_CASCADE_UNRELATED,
            ],
        )

    def test_nulls_parent_on_every_child(self, categories_manager: CategoriesManager) -> None:
        """After the cascade both children have ``parent=None``."""
        categories_manager.remove_category_as_parent(CATEGORY_ID_FOR_CASCADE_PARENT)

        child_a = categories_manager.get_category(CATEGORY_ID_FOR_CASCADE_CHILD_A)
        child_b = categories_manager.get_category(CATEGORY_ID_FOR_CASCADE_CHILD_B)
        assert child_a is not None and child_a['parent'] is None
        assert child_b is not None and child_b['parent'] is None

    def test_leaves_unrelated_categories_untouched(self, categories_manager: CategoriesManager) -> None:
        """A category that was never a child of the target is not modified by the cascade."""
        categories_manager.remove_category_as_parent(CATEGORY_ID_FOR_CASCADE_PARENT)

        unrelated = categories_manager.get_category(CATEGORY_ID_FOR_CASCADE_UNRELATED)
        assert unrelated is not None
        assert unrelated['parent'] is None  # was inserted with parent=None
        assert unrelated['public_id'] == CATEGORY_ID_FOR_CASCADE_UNRELATED

    def test_leaves_parent_itself_untouched(self, categories_manager: CategoriesManager) -> None:
        """The cascade only touches CHILDREN; the parent doc itself is not modified."""
        categories_manager.remove_category_as_parent(CATEGORY_ID_FOR_CASCADE_PARENT)

        parent = categories_manager.get_category(CATEGORY_ID_FOR_CASCADE_PARENT)
        assert parent is not None
        assert parent['public_id'] == CATEGORY_ID_FOR_CASCADE_PARENT

    def test_no_matching_children_is_a_noop(self, categories_manager: CategoriesManager) -> None:
        """Calling the cascade with an id that no row references is safe and changes nothing."""
        categories_manager.remove_category_as_parent(MISSING_CATEGORY_ID)

        child_a = categories_manager.get_category(CATEGORY_ID_FOR_CASCADE_CHILD_A)
        assert child_a is not None and child_a['parent'] == CATEGORY_ID_FOR_CASCADE_PARENT


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_parent_assignment ($graphLookup)                                   #
# -------------------------------------------------------------------------------------------------------------------- #
CHAIN_ROOT_ID: int = 9620
CHAIN_MID_ID: int = 9621
CHAIN_LEAF_ID: int = 9622
CHAIN_STANDALONE_ID: int = 9623

CHAIN_IDS: list[int] = [CHAIN_ROOT_ID, CHAIN_MID_ID, CHAIN_LEAF_ID, CHAIN_STANDALONE_ID]


class TestValidateParentAssignment:
    """``validate_parent_assignment`` resolves the ancestor chain via a single $graphLookup query."""

    @pytest.fixture(autouse=True)
    def _seed_chain(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a 3-deep parent chain (root <- mid <- leaf) plus a standalone root, per test."""
        collection = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
        collection.delete_many({'public_id': {'$in': CHAIN_IDS}})
        collection.insert_many([
            _category_data(CHAIN_ROOT_ID, parent=None),
            _category_data(CHAIN_MID_ID, parent=CHAIN_ROOT_ID),
            _category_data(CHAIN_LEAF_ID, parent=CHAIN_MID_ID),
            _category_data(CHAIN_STANDALONE_ID, parent=None),
        ])
        yield
        collection.delete_many({'public_id': {'$in': CHAIN_IDS}})

    def test_missing_parent_is_rejected(self, categories_manager: CategoriesManager) -> None:
        """A parent id that does not exist is rejected (the $match stage returns nothing)."""
        rejection = categories_manager.validate_parent_assignment(CHAIN_STANDALONE_ID, MISSING_CATEGORY_ID)

        assert rejection is not None
        assert 'does not exist' in rejection

    def test_valid_assignment_returns_none(self, categories_manager: CategoriesManager) -> None:
        """Assigning an existing, non-ancestor parent is accepted."""
        assert categories_manager.validate_parent_assignment(CHAIN_STANDALONE_ID, CHAIN_ROOT_ID) is None

    def test_cycle_through_multi_level_ancestors_is_rejected(self, categories_manager: CategoriesManager) -> None:
        """Assigning the leaf as parent of the root closes a cycle (root is a 2-level ancestor of leaf)."""
        rejection = categories_manager.validate_parent_assignment(CHAIN_ROOT_ID, CHAIN_LEAF_ID)

        assert rejection is not None
        assert 'cycle' in rejection

    def test_deep_chain_without_cycle_returns_none(self, categories_manager: CategoriesManager) -> None:
        """A category outside the chain may be parented under the deep leaf without a false cycle."""
        assert categories_manager.validate_parent_assignment(CHAIN_STANDALONE_ID, CHAIN_LEAF_ID) is None
