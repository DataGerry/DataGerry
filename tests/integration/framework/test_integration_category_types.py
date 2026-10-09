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
Integration tests for the CategoriesManager lookups behind the ``types`` rules, against a real MongoDB

``find_unknown_type_ids`` and ``find_type_claims`` answer the write guards; ``get_assigned_type_ids`` and
the category tree are the two reads a stored document entry used to break. All four run on real documents
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CategoriesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.category_model import CategoryTree, CmdbCategory
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_A: int = 9711
TYPE_B: int = 9712
MISSING_TYPE: int = 9719
HOLDER_ID: int = 9721
OTHER_HOLDER_ID: int = 9722
JUNK_ID: int = 9723

ADMIN: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=1)


def _category(public_id: int, types: list[Any]) -> dict[str, Any]:
    """A stored category document."""
    return {'public_id': public_id, 'name': f'integration-category-{public_id}', 'label': 'Integration',
            'parent': None, 'types': types, 'meta': {'icon': '', 'order': None}}


@pytest.fixture(name='manager')
def fixture_manager(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Two types and three categories - one of them carrying a document entry; a real CategoriesManager."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
    ids: list[int] = [HOLDER_ID, OTHER_HOLDER_ID, JUNK_ID]

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [TYPE_A, TYPE_B]}})
        categories.delete_many({'public_id': {'$in': ids}})

    _purge()
    types.insert_many([make_type_doc(TYPE_A, 'integration-category-a'),
                       make_type_doc(TYPE_B, 'integration-category-b')])
    categories.insert_many([_category(HOLDER_ID, [TYPE_A]), _category(OTHER_HOLDER_ID, []),
                            _category(JUNK_ID, [{'a': 1}, TYPE_B])])
    with rest_api.application.app_context():
        manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, ADMIN)
        yield manager
    _purge()


def test_unknown_type_ids_are_found(manager: CategoriesManager) -> None:
    """Against the real types collection"""
    assert manager.find_unknown_type_ids([TYPE_A, MISSING_TYPE]) == [MISSING_TYPE]


def test_claims_exclude_the_written_category(manager: CategoriesManager) -> None:
    """HOLDER holds TYPE_A: a clash for anyone else, none for itself"""
    assert manager.find_type_claims([TYPE_A], OTHER_HOLDER_ID) == {TYPE_A: [HOLDER_ID]}
    assert manager.find_type_claims([TYPE_A], HOLDER_ID) == {}


def test_the_assigned_set_reads_past_a_document_entry(manager: CategoriesManager) -> None:
    """The stored junk is skipped; TYPE_B beside it still counts as assigned"""
    assigned: set[int] = manager.get_assigned_type_ids()

    assert {TYPE_A, TYPE_B} <= assigned


def test_the_tree_builds_over_a_document_entry(manager: CategoriesManager) -> None:
    """The category holding the junk resolves its one real type"""
    tree: CategoryTree = manager.get_tree(ADMIN)

    junk_node = next(node for node in tree.tree if node.category.get_public_id() == JUNK_ID)
    assert [a_type.public_id for a_type in junk_node.types] == [TYPE_B]
