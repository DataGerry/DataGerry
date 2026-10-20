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
Integration tests for the object-relation read rule in ObjectRelationsManager against a real MongoDB

Seeds one object with relations to a readable, a denied and an unstamped (null) counterpart (and one where its own side
is denied), and asserts that the denied types narrow, end-to-end, what the real queries answer:

  - the tab aggregation counts only the relations whose two stamped types are readable, and drops a group made
    only of denied ones
  - the tab instances answer the same set in the page and the total, with the compound index still serving them
  - the list leaves the denied relations out of the rows and the total, ahead of a filter and of a client pipeline
  - nothing denied answers everything, as before
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager, build_readable_endpoints_condition
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationRole
from cmdb.models.relation_model import CmdbRelation
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 96801
MAIN_OBJ: int = 96811
READABLE_OBJ: int = 96812
DENIED_OBJ: int = 96813
UNSTAMPED_OBJ: int = 96814

READABLE_TYPE: int = 96821
DENIED_TYPE: int = 96822

READABLE_ROW: int = 96831     # MAIN -> READABLE
DENIED_ROW: int = 96832       # MAIN -> DENIED
UNSTAMPED_ROW: int = 96833    # MAIN -> UNSTAMPED (child type stored as null)
DENIED_PARENT_ROW: int = 96834  # DENIED -> MAIN (the main object's only child-side relation)
ALL_ROWS: list[int] = [READABLE_ROW, DENIED_ROW, UNSTAMPED_ROW, DENIED_PARENT_ROW]
READABLE_ROWS: list[int] = [READABLE_ROW, UNSTAMPED_ROW]

PARENT: str = ObjectRelationRole.PARENT.value
CHILD: str = ObjectRelationRole.CHILD.value
PUBLIC_ID: str = 'public_id'
SEEDED_ONLY: dict[str, Any] = {PUBLIC_ID: {'$in': ALL_ROWS}}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ObjectRelationsManager:
    """An ObjectRelationsManager wired to the test database"""
    return ObjectRelationsManager(database_manager)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """The relation definition and the four relations, cleaned up around each test"""
    definitions = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        definitions.delete_many({PUBLIC_ID: RELATION_ID})
        relations.delete_many(SEEDED_ONLY)

    def _row(public_id: int, parent: tuple[int, int | None], child: tuple[int, int | None]) -> dict[str, Any]:
        return {PUBLIC_ID: public_id, 'relation_id': RELATION_ID,
                'relation_parent_id': parent[0], 'relation_parent_type_id': parent[1],
                'relation_child_id': child[0], 'relation_child_type_id': child[1]}

    _purge()
    definitions.insert_one({PUBLIC_ID: RELATION_ID, 'relation_name_parent': 'Hosts',
                            'relation_name_child': 'Hosted On'})
    main = (MAIN_OBJ, READABLE_TYPE)
    relations.insert_many([
        _row(READABLE_ROW, main, (READABLE_OBJ, READABLE_TYPE)),
        _row(DENIED_ROW, main, (DENIED_OBJ, DENIED_TYPE)),
        _row(UNSTAMPED_ROW, main, (UNSTAMPED_OBJ, None)),
        _row(DENIED_PARENT_ROW, (DENIED_OBJ, DENIED_TYPE), main),
    ])
    yield
    _purge()


def _counts(tabs: list[dict[str, Any]]) -> dict[str, int]:
    """role -> count of the seeded relation's tabs"""
    return {tab['role']: tab['count'] for tab in tabs if tab['relation_id'] == RELATION_ID}


class TestTheTabs:
    """get_relation_tabs"""

    def test_denied_counterparts_are_not_counted(self, manager: ObjectRelationsManager) -> None:
        """Parent tab 2 of 3 (an unstamped side is not refused); the child tab is only a denied one, so it goes"""
        assert _counts(manager.get_relation_tabs(MAIN_OBJ, [DENIED_TYPE])) == {PARENT: 2}

    def test_nothing_denied_counts_everything(self, manager: ObjectRelationsManager) -> None:
        """As before"""
        assert _counts(manager.get_relation_tabs(MAIN_OBJ)) == {PARENT: 3, CHILD: 1}


class TestTheTabInstances:
    """get_relation_tab_instances"""

    def test_page_and_total_agree(self, manager: ObjectRelationsManager) -> None:
        """Both leave the denied row out"""
        instances, total = manager.get_relation_tab_instances(MAIN_OBJ, RELATION_ID, PARENT, limit=10,
                                                              denied_type_ids=[DENIED_TYPE])

        assert ([row[PUBLIC_ID] for row in instances], total) == (READABLE_ROWS, len(READABLE_ROWS))

    def test_a_tab_of_denied_rows_only_is_empty(self, manager: ObjectRelationsManager) -> None:
        """Nothing, and a zero total"""
        assert manager.get_relation_tab_instances(MAIN_OBJ, RELATION_ID, CHILD, limit=10,
                                                  denied_type_ids=[DENIED_TYPE]) == ([], 0)

    def test_the_tab_index_still_serves_the_page(self, manager: ObjectRelationsManager, database_manager,
                                                 database_name) -> None:
        """The narrowed criteria keep the compound (relation_id, side, public_id) index as the plan"""
        relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
        relations.create_index([('relation_id', 1), ('relation_parent_id', 1), (PUBLIC_ID, 1)],
                               name='relation_parent_tab')
        criteria: dict[str, Any] = {'relation_id': RELATION_ID, 'relation_parent_id': MAIN_OBJ,
                                    **build_readable_endpoints_condition([DENIED_TYPE])}

        plan: str = str(relations.find(criteria).sort(PUBLIC_ID, 1).explain()['queryPlanner']['winningPlan'])

        assert 'relation_parent_tab' in plan
        assert 'SORT' not in plan.replace('SORT_KEY', '')


class TestTheList:
    """iterate"""

    def test_rows_and_total_leave_denied_relations_out(self, manager: ObjectRelationsManager) -> None:
        """Ahead of the caller's filter"""
        result = manager.iterate(BuilderParameters(criteria=dict(SEEDED_ONLY), limit=0), [DENIED_TYPE])

        assert (sorted(row.public_id for row in result.results), result.total) == (READABLE_ROWS, 2)

    def test_a_client_pipeline_cannot_hide_the_types_from_the_rule(self, manager: ObjectRelationsManager) -> None:
        """A stage rewriting the stamped types runs after the rule, so it cannot launder a denied relation"""
        pipeline: list[dict[str, Any]] = [{'$match': SEEDED_ONLY},
                                          {'$set': {'relation_parent_type_id': READABLE_TYPE,
                                                    'relation_child_type_id': READABLE_TYPE}}]

        result = manager.iterate(BuilderParameters(criteria=pipeline, limit=0), [DENIED_TYPE])

        assert sorted(row.public_id for row in result.results) == READABLE_ROWS

    def test_nothing_denied_lists_everything(self, manager: ObjectRelationsManager) -> None:
        """As before"""
        result = manager.iterate(BuilderParameters(criteria=dict(SEEDED_ONLY), limit=0))

        assert result.total == len(ALL_ROWS)
