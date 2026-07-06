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
Integration tests for ObjectRelationsManager.get_relation_tabs against a real MongoDB

Verifies the relation-tab aggregation end-to-end: one descriptor per (relation_id, role) with the
role-oriented label/icon/color and the raw instance count, parent-before-child ordering, self-relation
counted on both sides, groups with a missing relation definition dropped, and an empty result for an
object with no relations.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 96401
OTHER_RELATION_ID: int = 96402  # instances exist but its definition is intentionally NOT seeded

MAIN_OBJ: int = 96411
CHILD_OBJ: int = 96412
PARENT_OBJ: int = 96413
SELF_OBJ: int = 96414
LONELY_OBJ: int = 96415  # has no relations

# object-relation instance public_ids
OR_IDS: list[int] = [96421, 96422, 96423, 96424, 96425]

NAME_PARENT: str = 'Hosts'
NAME_CHILD: str = 'Hosted On'
ICON_PARENT: str = 'fas fa-server'
ICON_CHILD: str = 'fas fa-network-wired'
COLOR_PARENT: str = '#111111'
COLOR_CHILD: str = '#222222'


@pytest.fixture(name='object_relations_manager')
def fixture_object_relations_manager(database_manager: MongoDatabaseManager) -> ObjectRelationsManager:
    """Provides an ObjectRelationsManager wired to the test database."""
    return ObjectRelationsManager(database_manager)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one relation definition + object-relation instances, cleaning up around each test."""
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({'public_id': {'$in': [RELATION_ID, OTHER_RELATION_ID]}})
        object_relations.delete_many({'public_id': {'$in': OR_IDS}})

    def _or(public_id: int, relation_id: int, parent: int, child: int) -> dict[str, Any]:
        return {'public_id': public_id, 'relation_id': relation_id,
                'relation_parent_id': parent, 'relation_child_id': child}

    _purge()
    relations.insert_one({
        'public_id': RELATION_ID,
        'relation_name_parent': NAME_PARENT, 'relation_name_child': NAME_CHILD,
        'relation_icon_parent': ICON_PARENT, 'relation_icon_child': ICON_CHILD,
        'relation_color_parent': COLOR_PARENT, 'relation_color_child': COLOR_CHILD,
    })
    object_relations.insert_many([
        # MAIN_OBJ is parent twice (role=parent, count 2) and child once (role=child, count 1)
        _or(OR_IDS[0], RELATION_ID, MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[1], RELATION_ID, MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[2], RELATION_ID, PARENT_OBJ, MAIN_OBJ),
        # instance of a relation whose definition is NOT seeded -> must be dropped
        _or(OR_IDS[3], OTHER_RELATION_ID, MAIN_OBJ, CHILD_OBJ),
        # self-relation: SELF_OBJ is both parent and child of the same instance
        _or(OR_IDS[4], RELATION_ID, SELF_OBJ, SELF_OBJ),
    ])
    yield
    _purge()


def _by_role(tabs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Indexes the returned tabs by their role."""
    return {tab['role']: tab for tab in tabs}


class TestGetRelationTabs:
    """get_relation_tabs returns one descriptor per (relation_id, role) with counts + role display."""

    def test_parent_and_child_tabs_with_counts(self, object_relations_manager: ObjectRelationsManager) -> None:
        """MAIN_OBJ yields a parent tab (count 2) and a child tab (count 1), parent first."""
        tabs = object_relations_manager.get_relation_tabs(MAIN_OBJ)

        # only the seeded-definition relation survives (the OTHER_RELATION_ID group is dropped)
        assert [t['role'] for t in tabs] == ['parent', 'child']
        by_role = _by_role(tabs)
        assert by_role['parent']['count'] == 2
        assert by_role['child']['count'] == 1

    def test_role_oriented_label_icon_color(self, object_relations_manager: ObjectRelationsManager) -> None:
        """Each tab carries the label/icon/color of its role side."""
        by_role = _by_role(object_relations_manager.get_relation_tabs(MAIN_OBJ))

        assert (by_role['parent']['label'], by_role['parent']['icon'], by_role['parent']['color']) == \
            (NAME_PARENT, ICON_PARENT, COLOR_PARENT)
        assert (by_role['child']['label'], by_role['child']['icon'], by_role['child']['color']) == \
            (NAME_CHILD, ICON_CHILD, COLOR_CHILD)
        assert by_role['parent']['relation_id'] == RELATION_ID

    def test_missing_definition_group_is_dropped(self, object_relations_manager: ObjectRelationsManager) -> None:
        """An instance whose relation definition is missing contributes no tab."""
        tabs = object_relations_manager.get_relation_tabs(MAIN_OBJ)

        assert all(tab['relation_id'] == RELATION_ID for tab in tabs)

    def test_self_relation_counts_on_both_sides(self, object_relations_manager: ObjectRelationsManager) -> None:
        """A self-relation instance yields both a parent and a child tab, each count 1."""
        by_role = _by_role(object_relations_manager.get_relation_tabs(SELF_OBJ))

        assert by_role['parent']['count'] == 1
        assert by_role['child']['count'] == 1

    def test_object_without_relations_returns_empty(self,
                                                    object_relations_manager: ObjectRelationsManager) -> None:
        """An object with no relations yields no tabs."""
        assert object_relations_manager.get_relation_tabs(LONELY_OBJ) == []


class TestGetRelationTabInstances:
    """get_relation_tab_instances returns the paged instances of one (relation_id, role) group + total."""

    def test_parent_group_total_and_page(self, object_relations_manager: ObjectRelationsManager) -> None:
        """The parent group has total 2 and a single-item page returns one instance."""
        instances, total = object_relations_manager.get_relation_tab_instances(
            MAIN_OBJ, RELATION_ID, 'parent', limit=1, skip=0)

        assert total == 2
        assert len(instances) == 1
        # parent role -> the object is the parent, the counterpart is the child
        assert instances[0]['relation_parent_id'] == MAIN_OBJ
        assert instances[0]['relation_child_id'] == CHILD_OBJ

    def test_pagination_skips(self, object_relations_manager: ObjectRelationsManager) -> None:
        """Skipping returns the next page and never repeats the first item."""
        first, _ = object_relations_manager.get_relation_tab_instances(MAIN_OBJ, RELATION_ID, 'parent', limit=1, skip=0)
        second, total = object_relations_manager.get_relation_tab_instances(
            MAIN_OBJ, RELATION_ID, 'parent', limit=1, skip=1)

        assert total == 2
        assert first[0]['public_id'] != second[0]['public_id']

    def test_child_group(self, object_relations_manager: ObjectRelationsManager) -> None:
        """The child group selects the instance where the object is the child (total 1)."""
        instances, total = object_relations_manager.get_relation_tab_instances(MAIN_OBJ, RELATION_ID, 'child')

        assert total == 1
        assert instances[0]['relation_child_id'] == MAIN_OBJ
        assert instances[0]['relation_parent_id'] == PARENT_OBJ

    def test_empty_group(self, object_relations_manager: ObjectRelationsManager) -> None:
        """A group with no instances returns an empty page and total 0."""
        instances, total = object_relations_manager.get_relation_tab_instances(LONELY_OBJ, RELATION_ID, 'parent')

        assert (instances, total) == ([], 0)
