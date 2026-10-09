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
Unit tests for the object-relation read rule in cmdb.manager.object_relations_manager

A CmdbObjectRelation is as readable as the less readable of its two objects, judged by the type ids stamped on it.
``build_readable_endpoints_condition`` is the rule; the tab pipeline, the tab instances and the list each apply it
to the criteria their rows AND their totals are read from - and add nothing when nothing is denied
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager import ObjectRelationsManager
from cmdb.manager.object_relations_manager import build_readable_endpoints_condition, build_relation_tabs_pipeline
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_relation_model import ObjectRelationKey, ObjectRelationRole
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 100
RELATION_ID: int = 5
DENIED_TYPE_IDS: list[int] = [31, 32]
CLIENT_FILTER: dict[str, Any] = {ObjectRelationKey.RELATION_ID.value: RELATION_ID}

PARENT_TYPE: str = ObjectRelationKey.RELATION_PARENT_TYPE_ID.value
CHILD_TYPE: str = ObjectRelationKey.RELATION_CHILD_TYPE_ID.value

READABLE_CONDITION: dict[str, Any] = {
    PARENT_TYPE: {'$nin': DENIED_TYPE_IDS},
    CHILD_TYPE: {'$nin': DENIED_TYPE_IDS},
}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for an ObjectRelationsManager instance"""
    return MagicMock(spec=ObjectRelationsManager)


class TestTheCondition:
    """build_readable_endpoints_condition"""

    def test_both_ends_must_be_readable(self) -> None:
        """A denied type at either end excludes the relation"""
        assert build_readable_endpoints_condition(DENIED_TYPE_IDS) == READABLE_CONDITION

    @pytest.mark.parametrize('denied', [None, []], ids=['none', 'empty'])
    def test_nothing_denied_adds_nothing(self, denied: list[int] | None) -> None:
        """The common case costs no condition"""
        assert build_readable_endpoints_condition(denied) == {}


class TestTheTabPipeline:
    """build_relation_tabs_pipeline narrows its first match"""

    def test_the_first_match_keeps_only_readable_relations(self) -> None:
        """Ahead of the group, so the counts follow"""
        match: dict[str, Any] = build_relation_tabs_pipeline(OBJECT_ID, DENIED_TYPE_IDS)[0]['$match']

        assert match == {
            '$or': [
                {ObjectRelationKey.RELATION_PARENT_ID.value: OBJECT_ID},
                {ObjectRelationKey.RELATION_CHILD_ID.value: OBJECT_ID},
            ],
            **READABLE_CONDITION,
        }

    def test_without_denied_types_the_match_is_unchanged(self) -> None:
        """The object on either side, nothing else"""
        assert build_relation_tabs_pipeline(OBJECT_ID)[0]['$match'] == build_relation_tabs_pipeline(
            OBJECT_ID, [])[0]['$match']

    def test_get_relation_tabs_passes_the_denied_types_on(self) -> None:
        """The manager aggregates the narrowed pipeline"""
        mgr = _mock_manager()
        mgr.aggregate.return_value = iter([])

        ObjectRelationsManager.get_relation_tabs(mgr, OBJECT_ID, DENIED_TYPE_IDS)

        assert mgr.aggregate.call_args.args[0] == build_relation_tabs_pipeline(OBJECT_ID, DENIED_TYPE_IDS)


class TestTheTabInstances:
    """get_relation_tab_instances narrows the page and the total alike"""

    def test_page_and_total_read_the_same_narrowed_criteria(self) -> None:
        """A row the caller cannot see is neither shown nor counted"""
        mgr = _mock_manager()
        mgr.count_documents.return_value = 0
        mgr.find.return_value = []

        ObjectRelationsManager.get_relation_tab_instances(
            mgr, OBJECT_ID, RELATION_ID, ObjectRelationRole.PARENT.value, denied_type_ids=DENIED_TYPE_IDS,
        )

        expected: dict[str, Any] = {
            ObjectRelationKey.RELATION_ID.value: RELATION_ID,
            ObjectRelationKey.RELATION_PARENT_ID.value: OBJECT_ID,
            **READABLE_CONDITION,
        }
        assert mgr.count_documents.call_args.args[0] == expected
        assert mgr.find.call_args.kwargs['criteria'] == expected


class TestTheList:
    """iterate narrows the caller's criteria ahead of its own filter"""

    def test_the_condition_goes_first(self) -> None:
        """Prepended into the criteria both the rows and the count are built from"""
        mgr = _mock_manager()
        params = BuilderParameters(criteria=dict(CLIENT_FILTER))

        ObjectRelationsManager.iterate(mgr, params, DENIED_TYPE_IDS)

        mgr.iterate_items.assert_called_once_with(params)
        assert params.get_criteria() == {**CLIENT_FILTER, **READABLE_CONDITION}

    def test_a_client_filter_on_a_stamped_type_cannot_replace_the_rule(self) -> None:
        """Both are kept under $and - a filter naming a denied type matches nothing"""
        mgr = _mock_manager()
        client_filter: dict[str, Any] = {PARENT_TYPE: DENIED_TYPE_IDS[0]}
        params = BuilderParameters(criteria=dict(client_filter))

        ObjectRelationsManager.iterate(mgr, params, DENIED_TYPE_IDS)

        assert params.get_criteria() == {'$and': [client_filter, READABLE_CONDITION]}

    def test_a_pipeline_filter_is_narrowed_before_its_first_stage(self) -> None:
        """A client pipeline cannot project the stamped types away before the rule reads them"""
        mgr = _mock_manager()
        client_pipeline: list[dict[str, Any]] = [{'$project': {ObjectRelationKey.RELATION_ID.value: 1}}]
        params = BuilderParameters(criteria=list(client_pipeline))

        ObjectRelationsManager.iterate(mgr, params, DENIED_TYPE_IDS)

        assert params.get_criteria() == [{'$match': READABLE_CONDITION}, *client_pipeline]

    @pytest.mark.parametrize('denied', [None, []], ids=['none', 'empty'])
    def test_nothing_denied_leaves_the_criteria_alone(self, denied: list[int] | None) -> None:
        """Internal callers and unrestricted groups read as before"""
        mgr = _mock_manager()
        params = BuilderParameters(criteria=dict(CLIENT_FILTER))

        ObjectRelationsManager.iterate(mgr, params, denied)

        assert params.get_criteria() == CLIENT_FILTER
