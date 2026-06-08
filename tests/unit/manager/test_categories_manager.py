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
Unit tests for cmdb.manager.categories_manager.CategoriesManager

Pure tests: no Mongo. Only the methods that carry their own behavior beyond the GenericManager
forwarders are exercised here - ``tree``, ``iterate``, ``get_categories_by`` and
``remove_category_as_parent``. The one-line delegations (``insert_category``, ``get_category``,
``update_category``, ``delete_category``) are intentionally out of scope; they are covered
transitively by the GenericManager unit suite and the integration tests.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.categories_manager import CategoriesManager
from cmdb.models.category_model import CmdbCategory

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.categories_manager import (
    CategoriesManagerGetError,
    CategoriesManagerUpdateError,
    CategoriesManagerIterationError,
    CategoriesManagerTreeInitError,
)
from cmdb.errors.models.cmdb_category import CmdbCategoryInitFromDataError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.categories_manager'

CATEGORY_PUBLIC_ID: int = 7
PARENT_CATEGORY_PUBLIC_ID: int = 3
GRANDPARENT_PUBLIC_ID: int = 2
MISSING_CATEGORY_PUBLIC_ID: int = 99
DELETED_TYPE_PUBLIC_ID: int = 42
TOTAL_CATEGORIES: int = 2

SAMPLE_CATEGORY_DICT: dict[str, Any] = {'public_id': CATEGORY_PUBLIC_ID, 'name': 'c', 'label': 'C'}
SAMPLE_CATEGORY_DICTS: list[dict[str, Any]] = [
    SAMPLE_CATEGORY_DICT,
    {'public_id': CATEGORY_PUBLIC_ID + 1, 'name': 'c2', 'label': 'C2'},
]


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a CategoriesManager instance."""
    return MagicMock(spec=CategoriesManager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                          tree                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTree:
    """``tree`` composes a CategoryTree from the bound categories and the type collection."""

    def test_builds_category_tree_from_categories_and_types(self) -> None:
        """The happy path passes hydrated types and the iterated categories to ``CategoryTree``."""
        mgr = _mock_manager()
        raw_types = [{'public_id': 1}, {'public_id': 2}]
        mgr.get_many_from_other_collection.return_value = raw_types
        hydrated_categories = [MagicMock(name='cat1'), MagicMock(name='cat2')]
        mgr.iterate.return_value = MagicMock(results=hydrated_categories)
        sentinel_tree = MagicMock(name='category_tree')

        with patch(f'{MODULE_PATH}.CmdbType.from_data', side_effect=lambda data: ('T', data['public_id'])), \
             patch(f'{MODULE_PATH}.CategoryTree', return_value=sentinel_tree) as tree_ctor:
            result = CategoriesManager.tree.fget(mgr)  # pylint: disable=assignment-from-no-return

        assert result is sentinel_tree
        tree_ctor.assert_called_once_with(hydrated_categories, [('T', 1), ('T', 2)])

    def test_unexpected_error_wraps_as_tree_init_error(self) -> None:
        """A failure anywhere in the composition is surfaced as ``CategoriesManagerTreeInitError``."""
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.side_effect = RuntimeError('db down')

        with pytest.raises(CategoriesManagerTreeInitError):
            CategoriesManager.tree.fget(mgr)  # pylint: disable=assignment-from-no-return


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        iterate                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterate:
    """``iterate`` runs the ACL-aware aggregation and wraps the result in an IterationResult."""

    def test_passes_user_and_permission_to_iterate_query(self) -> None:
        """User and permission are forwarded to ``iterate_query`` and the model is bound to the result."""
        mgr = _mock_manager()
        aggregation_result = SAMPLE_CATEGORY_DICTS
        mgr.iterate_query.return_value = (aggregation_result, TOTAL_CATEGORIES)
        builder_params = MagicMock(name='builder_params')
        user = MagicMock(name='user')
        permission = MagicMock(name='permission')
        sentinel_result = MagicMock(name='iteration_result')

        with patch(f'{MODULE_PATH}.IterationResult', return_value=sentinel_result) as result_ctor:
            result = CategoriesManager.iterate(mgr, builder_params, user, permission)

        mgr.iterate_query.assert_called_once_with(builder_params, user, permission)
        result_ctor.assert_called_once_with(aggregation_result, TOTAL_CATEGORIES, CmdbCategory)
        assert result is sentinel_result

    def test_iteration_error_wraps_as_categories_iteration_error(self) -> None:
        """A ``BaseManagerIterationError`` from ``iterate_query`` is re-raised as the categories variant."""
        mgr = _mock_manager()
        mgr.iterate_query.side_effect = BaseManagerIterationError('bad pipeline')

        with pytest.raises(CategoriesManagerIterationError):
            CategoriesManager.iterate(mgr, MagicMock())

    def test_unexpected_error_wraps_as_categories_iteration_error(self) -> None:
        """A generic exception is also wrapped as ``CategoriesManagerIterationError``."""
        mgr = _mock_manager()
        mgr.iterate_query.side_effect = RuntimeError('boom')

        with pytest.raises(CategoriesManagerIterationError):
            CategoriesManager.iterate(mgr, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_categories_by                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCategoriesBy:
    """``get_categories_by`` queries the bound collection and hydrates each row to ``CmdbCategory``."""

    def test_hydrates_each_raw_row_via_from_data(self) -> None:
        """The happy path forwards ``sort`` + filters to ``get_many`` and rehydrates the rows."""
        mgr = _mock_manager()
        mgr.get_many.return_value = SAMPLE_CATEGORY_DICTS
        hydrated = [MagicMock(name='cat1'), MagicMock(name='cat2')]

        with patch.object(CmdbCategory, 'from_data', side_effect=hydrated) as from_data_mock:
            result = CategoriesManager.get_categories_by(mgr, sort='label', parent=PARENT_CATEGORY_PUBLIC_ID)

        mgr.get_many.assert_called_once_with(sort='label', parent=PARENT_CATEGORY_PUBLIC_ID)
        assert [c.args[0] for c in from_data_mock.call_args_list] == SAMPLE_CATEGORY_DICTS
        assert result == hydrated

    def test_get_error_wraps_as_categories_get_error(self) -> None:
        """A ``BaseManagerGetError`` from ``get_many`` is wrapped as ``CategoriesManagerGetError``."""
        mgr = _mock_manager()
        mgr.get_many.side_effect = BaseManagerGetError('db down')

        with pytest.raises(CategoriesManagerGetError):
            CategoriesManager.get_categories_by(mgr)

    def test_from_data_error_wraps_as_categories_get_error(self) -> None:
        """An ``CmdbCategoryInitFromDataError`` during rehydration is wrapped as ``CategoriesManagerGetError``."""
        mgr = _mock_manager()
        mgr.get_many.return_value = SAMPLE_CATEGORY_DICTS

        with patch.object(CmdbCategory, 'from_data', side_effect=CmdbCategoryInitFromDataError('malformed')):
            with pytest.raises(CategoriesManagerGetError):
                CategoriesManager.get_categories_by(mgr)

    def test_unexpected_error_wraps_as_categories_get_error(self) -> None:
        """A generic exception is wrapped as ``CategoriesManagerGetError``."""
        mgr = _mock_manager()
        mgr.get_many.side_effect = RuntimeError('boom')

        with pytest.raises(CategoriesManagerGetError):
            CategoriesManager.get_categories_by(mgr)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              remove_category_as_parent                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemoveCategoryAsParent:
    """``remove_category_as_parent`` nulls the parent on all children of the given category."""

    def test_calls_update_many_with_parent_criteria_and_null_parent(self) -> None:
        """The happy path issues a single ``update_many({'parent': pid}, {'parent': None})``."""
        mgr = _mock_manager()

        CategoriesManager.remove_category_as_parent(mgr, PARENT_CATEGORY_PUBLIC_ID)

        mgr.update_many.assert_called_once_with(
            criteria={'parent': PARENT_CATEGORY_PUBLIC_ID},
            update={'parent': None},
        )

    def test_update_error_wraps_as_categories_update_error(self) -> None:
        """A ``BaseManagerUpdateError`` from ``update_many`` is wrapped as ``CategoriesManagerUpdateError``."""
        mgr = _mock_manager()
        mgr.update_many.side_effect = BaseManagerUpdateError('write failed')

        with pytest.raises(CategoriesManagerUpdateError):
            CategoriesManager.remove_category_as_parent(mgr, PARENT_CATEGORY_PUBLIC_ID)

    def test_unexpected_error_wraps_as_categories_update_error(self) -> None:
        """A generic exception (including get errors - update_many cannot raise them) is wrapped
        as ``CategoriesManagerUpdateError``."""
        mgr = _mock_manager()
        mgr.update_many.side_effect = RuntimeError('boom')

        with pytest.raises(CategoriesManagerUpdateError):
            CategoriesManager.remove_category_as_parent(mgr, PARENT_CATEGORY_PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             remove_type_from_categories                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemoveTypeFromCategories:
    """``remove_type_from_categories`` pulls a deleted CmdbType id from every 'types' array."""

    def test_issues_a_single_pull_update(self) -> None:
        """The happy path issues one ``update_many_pull`` with the type id in criteria and $pull."""
        mgr = _mock_manager()

        CategoriesManager.remove_type_from_categories(mgr, DELETED_TYPE_PUBLIC_ID)

        mgr.update_many_pull.assert_called_once_with(
            criteria={'types': DELETED_TYPE_PUBLIC_ID},
            update={'$pull': {'types': DELETED_TYPE_PUBLIC_ID}},
        )

    def test_update_error_wraps_as_categories_update_error(self) -> None:
        """A ``BaseManagerUpdateError`` from ``update_many_pull`` is wrapped as ``CategoriesManagerUpdateError``."""
        mgr = _mock_manager()
        mgr.update_many_pull.side_effect = BaseManagerUpdateError('write failed')

        with pytest.raises(CategoriesManagerUpdateError):
            CategoriesManager.remove_type_from_categories(mgr, DELETED_TYPE_PUBLIC_ID)

    def test_unexpected_error_wraps_as_categories_update_error(self) -> None:
        """A generic exception is wrapped as ``CategoriesManagerUpdateError``."""
        mgr = _mock_manager()
        mgr.update_many_pull.side_effect = RuntimeError('boom')

        with pytest.raises(CategoriesManagerUpdateError):
            CategoriesManager.remove_type_from_categories(mgr, DELETED_TYPE_PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             validate_parent_assignment                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateParentAssignment:
    """``validate_parent_assignment`` guards the parent reference on insert and update."""

    @staticmethod
    def _category_doc(public_id: int, parent: int | None) -> dict:
        """Builds a minimal stored category document with the given identity and parent."""
        return {'public_id': public_id, 'parent': parent}

    def test_none_parent_is_always_valid(self) -> None:
        """Detaching / root assignment (parent None) passes without any lookup."""
        mgr = _mock_manager()

        assert CategoriesManager.validate_parent_assignment(mgr, CATEGORY_PUBLIC_ID, None) is None
        mgr.get_category.assert_not_called()

    def test_self_parent_is_rejected_before_any_lookup(self) -> None:
        """parent == public_id returns a rejection reason without touching the database."""
        mgr = _mock_manager()

        reason = CategoriesManager.validate_parent_assignment(mgr, CATEGORY_PUBLIC_ID, CATEGORY_PUBLIC_ID)

        assert reason is not None
        mgr.get_category.assert_not_called()

    def test_missing_parent_is_rejected(self) -> None:
        """A parent id that resolves to no document returns a rejection reason."""
        mgr = _mock_manager()
        mgr.get_category.return_value = None

        reason = CategoriesManager.validate_parent_assignment(
            mgr, CATEGORY_PUBLIC_ID, MISSING_CATEGORY_PUBLIC_ID,
        )

        assert reason is not None

    def test_insert_mode_only_checks_parent_existence(self) -> None:
        """public_id None (insert) accepts any existing parent without walking the chain."""
        mgr = _mock_manager()
        mgr.get_category.return_value = self._category_doc(PARENT_CATEGORY_PUBLIC_ID, GRANDPARENT_PUBLIC_ID)

        assert CategoriesManager.validate_parent_assignment(mgr, None, PARENT_CATEGORY_PUBLIC_ID) is None
        mgr.get_category.assert_called_once_with(PARENT_CATEGORY_PUBLIC_ID)

    def test_valid_chain_passes(self) -> None:
        """A parent whose ancestor chain ends at a root (parent None) is accepted."""
        mgr = _mock_manager()
        mgr.get_category.side_effect = [
            self._category_doc(PARENT_CATEGORY_PUBLIC_ID, GRANDPARENT_PUBLIC_ID),
            self._category_doc(GRANDPARENT_PUBLIC_ID, None),
        ]

        reason = CategoriesManager.validate_parent_assignment(
            mgr, CATEGORY_PUBLIC_ID, PARENT_CATEGORY_PUBLIC_ID,
        )

        assert reason is None

    def test_ancestor_cycle_is_rejected(self) -> None:
        """Assigning a parent whose chain leads back to the candidate (A -> B -> A) is rejected."""
        mgr = _mock_manager()
        # Candidate CATEGORY wants PARENT as parent; PARENT's ancestor is the candidate itself
        mgr.get_category.return_value = self._category_doc(PARENT_CATEGORY_PUBLIC_ID, CATEGORY_PUBLIC_ID)

        reason = CategoriesManager.validate_parent_assignment(
            mgr, CATEGORY_PUBLIC_ID, PARENT_CATEGORY_PUBLIC_ID,
        )

        assert reason is not None

    def test_preexisting_cycle_in_stored_data_terminates(self) -> None:
        """A cycle already stored among the ancestors (not involving the candidate) ends the walk
        via the visited set instead of looping forever; the assignment itself is accepted."""
        mgr = _mock_manager()
        mgr.get_category.side_effect = [
            self._category_doc(PARENT_CATEGORY_PUBLIC_ID, GRANDPARENT_PUBLIC_ID),
            self._category_doc(GRANDPARENT_PUBLIC_ID, PARENT_CATEGORY_PUBLIC_ID),
            self._category_doc(PARENT_CATEGORY_PUBLIC_ID, GRANDPARENT_PUBLIC_ID),
        ]

        reason = CategoriesManager.validate_parent_assignment(
            mgr, CATEGORY_PUBLIC_ID, PARENT_CATEGORY_PUBLIC_ID,
        )

        assert reason is None
