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
Integration tests for ``RelationsManager.find_relations_left_without_types`` against a real MongoDB

The query decides which CmdbType deletes are refused: a relation is found when the type is the ONLY id on its parent
or its child side - so pulling it would empty that side. Pinned on stored documents: a parent-only and a child-only
relation are found, a relation holding the type next to another one on the same side is not, nor is one that does
not name the type; a side repeating the type is still "only the type"; the answer is in public_id order and carries
nothing but the identity
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.models.relation_model import CmdbRelation, RelationKey
# -------------------------------------------------------------------------------------------------------------------- #

DELETED_TYPE_ID: int = 86501
OTHER_TYPE_ID: int = 86502
UNRELATED_TYPE_ID: int = 86503

ONLY_PARENT_ID: int = 86511       # parent side = [deleted]          -> found
ONLY_CHILD_ID: int = 86512        # child side  = [deleted]          -> found
SHARED_SIDE_ID: int = 86513       # parent side = [deleted, other]   -> not found
UNRELATED_ID: int = 86514         # the type on neither side         -> not found
REPEATED_ID: int = 86515          # child side  = [deleted, deleted] -> found
ALL_IDS: list[int] = [ONLY_PARENT_ID, ONLY_CHILD_ID, SHARED_SIDE_ID, UNRELATED_ID, REPEATED_ID]


def _relation(public_id: int, parent_type_ids: list[int], child_type_ids: list[int]) -> dict[str, Any]:
    """A stored relation definition with the given sides."""
    return {
        RelationKey.PUBLIC_ID.value: public_id,
        RelationKey.RELATION_NAME.value: f'last-type-{public_id}',
        RelationKey.PARENT_TYPE_IDS.value: parent_type_ids,
        RelationKey.CHILD_TYPE_IDS.value: child_type_ids,
        'sections': [],
        'fields': [],
    }


@pytest.fixture(name='relations_manager')
def fixture_relations_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The five relations seeded directly, removed afterwards"""
    collection = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    collection.delete_many({RelationKey.PUBLIC_ID.value: {'$in': ALL_IDS}})
    collection.insert_many([
        _relation(ONLY_PARENT_ID, [DELETED_TYPE_ID], [OTHER_TYPE_ID]),
        _relation(ONLY_CHILD_ID, [OTHER_TYPE_ID], [DELETED_TYPE_ID]),
        _relation(SHARED_SIDE_ID, [DELETED_TYPE_ID, OTHER_TYPE_ID], [OTHER_TYPE_ID]),
        _relation(UNRELATED_ID, [OTHER_TYPE_ID], [UNRELATED_TYPE_ID]),
        _relation(REPEATED_ID, [OTHER_TYPE_ID], [DELETED_TYPE_ID, DELETED_TYPE_ID]),
    ])
    yield RelationsManager(database_manager)
    collection.delete_many({RelationKey.PUBLIC_ID.value: {'$in': ALL_IDS}})


def test_finds_exactly_the_relations_a_pull_would_empty(relations_manager: RelationsManager) -> None:
    """Parent-only, child-only and a repeated id are found - a shared side and an unrelated relation are not"""
    found = relations_manager.find_relations_left_without_types(DELETED_TYPE_ID)

    assert [relation[RelationKey.PUBLIC_ID.value] for relation in found] == [ONLY_PARENT_ID, ONLY_CHILD_ID, REPEATED_ID]


def test_answers_the_identity_only(relations_manager: RelationsManager) -> None:
    """Name and id - what the refusal shows - and no stored side lists"""
    found = relations_manager.find_relations_left_without_types(DELETED_TYPE_ID)

    assert found[0] == {RelationKey.PUBLIC_ID.value: ONLY_PARENT_ID,
                        RelationKey.RELATION_NAME.value: f'last-type-{ONLY_PARENT_ID}'}


def test_another_type_is_judged_on_its_own_sides(relations_manager: RelationsManager) -> None:
    """UNRELATED_TYPE_ID is the only child type of one relation - that one, and none of the others, is found"""
    found = relations_manager.find_relations_left_without_types(UNRELATED_TYPE_ID)

    assert [relation[RelationKey.PUBLIC_ID.value] for relation in found] == [UNRELATED_ID]
