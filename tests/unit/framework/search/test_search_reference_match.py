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
Unit tests for cmdb.framework.search.search_reference_match

Pure tests over a stub objects manager: which query collects a term's referenced objects, the condition
a reference row has to meet, and which of the three shapes a term becomes - own values only, own values
or a referenced id, or the database-side join for a term too broad for an id list - with one condition on
both sides, or a separate ``own_condition`` on the candidate (the object list's ``?search=``). What these stages
match against real documents is the integration tier's question, not this module's
"""
from typing import Any

import pytest

from cmdb.framework.search import search_reference_match
from cmdb.framework.search.search_constants import REFERENCE_FIELD_KINDS, REFERENCED_MATCH_FIELD
from cmdb.framework.search.search_reference_match import (
    build_reference_rows_condition,
    build_term_join_stages,
    build_text_term_stages,
    collect_referenced_match_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

VALUE_CONDITION: dict[str, Any] = {'fields.value': {'$regex': 'needle', '$options': 'ims'}}
ACL_STAGES: list[dict[str, Any]] = [{'$match': {'type_id': {'$nin': [21]}}}]
REFERENCED_IDS: list[int] = [31, 32, 33]
SMALL_LIMIT: int = 2


class _StubObjectsManager:
    """Answers the configured ids as public_id documents and records every pipeline it ran."""

    def __init__(self, public_ids: list[int]) -> None:
        self.public_ids = public_ids
        self.pipelines: list[list[dict[str, Any]]] = []

    def aggregate_objects(self, pipeline: list[dict[str, Any]]) -> list[dict[str, int]]:
        """Records the pipeline; honours its $limit so the cap is exercised as in the database."""
        self.pipelines.append(pipeline)
        limit: int = next((stage['$limit'] for stage in pipeline if '$limit' in stage), len(self.public_ids))

        return [{'public_id': public_id} for public_id in self.public_ids[:limit]]


class TestCollectReferencedMatchIds:
    """The query answering the objects a term matches by their own values."""

    def test_the_matching_ids_are_answered(self) -> None:
        """Under the limit, the ids come back as a list"""
        assert collect_referenced_match_ids(_StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, []) \
            == REFERENCED_IDS

    def test_the_query_matches_the_term_then_applies_the_acl(self) -> None:
        """The term first, then the caller's ACL - an unreadable object is never a referenced match"""
        objects_manager = _StubObjectsManager(REFERENCED_IDS)

        collect_referenced_match_ids(objects_manager, VALUE_CONDITION, ACL_STAGES)

        pipeline: list[dict[str, Any]] = objects_manager.pipelines[0]
        assert pipeline[0] == {'$match': VALUE_CONDITION}
        assert pipeline[1:1 + len(ACL_STAGES)] == ACL_STAGES

    def test_only_the_public_id_is_read(self) -> None:
        """The objects are not loaded - one projected key per match"""
        objects_manager = _StubObjectsManager(REFERENCED_IDS)

        collect_referenced_match_ids(objects_manager, VALUE_CONDITION, [])

        assert {'$project': {'_id': 0, 'public_id': 1}} in objects_manager.pipelines[0]

    def test_it_reads_one_past_the_limit_and_no_further(self) -> None:
        """One extra document is enough to know the limit was passed"""
        objects_manager = _StubObjectsManager(REFERENCED_IDS)

        collect_referenced_match_ids(objects_manager, VALUE_CONDITION, [], SMALL_LIMIT)

        assert {'$limit': SMALL_LIMIT + 1} in objects_manager.pipelines[0]

    def test_more_than_the_limit_answers_none(self) -> None:
        """Too many for an id list: the caller switches to the join"""
        assert collect_referenced_match_ids(
            _StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, [], SMALL_LIMIT,
        ) is None

    def test_exactly_the_limit_is_still_a_list(self) -> None:
        """The limit itself is allowed"""
        assert collect_referenced_match_ids(
            _StubObjectsManager(REFERENCED_IDS[:SMALL_LIMIT]), VALUE_CONDITION, [], SMALL_LIMIT,
        ) == REFERENCED_IDS[:SMALL_LIMIT]


class TestReferenceRowsCondition:
    """The condition a stored row has to meet to count as a reference to one of the ids."""

    def test_kind_and_value_are_matched_on_the_same_row(self) -> None:
        """One $elemMatch: a reference row elsewhere next to a number row holding the id does not match"""
        assert build_reference_rows_condition(REFERENCED_IDS) == {
            'fields': {'$elemMatch': {'type': {'$in': list(REFERENCE_FIELD_KINDS)}, 'value': {'$in': REFERENCED_IDS}}}
        }

    @pytest.mark.parametrize('kind', ['ref', 'ref-section-field', 'location'])
    def test_every_reference_kind_counts(self, kind: str) -> None:
        """A plain reference, a reference section's field and a location all point at an object"""
        assert kind in build_reference_rows_condition(REFERENCED_IDS)['fields']['$elemMatch']['type']['$in']

    @pytest.mark.parametrize('kind', ['number', 'text'])
    def test_a_non_reference_kind_does_not(self, kind: str) -> None:
        """A number that equals an object's id is still a number"""
        assert kind not in build_reference_rows_condition(REFERENCED_IDS)['fields']['$elemMatch']['type']['$in']


class TestTermJoinStages:
    """The database-side evaluation for a term too broad for an id list."""

    def test_join_match_and_clean_up(self) -> None:
        """Three stages: the join, the match on own values or a joined hit, and the working field removed"""
        stages = build_term_join_stages(VALUE_CONDITION, ACL_STAGES)

        assert [next(iter(stage)) for stage in stages] == ['$lookup', '$match', '$unset']
        assert stages[1] == {'$match': {'$or': [VALUE_CONDITION, {REFERENCED_MATCH_FIELD: {'$ne': []}}]}}
        assert stages[2] == {'$unset': [REFERENCED_MATCH_FIELD]}

    def test_the_join_matches_the_term_and_the_acl_and_stops_at_one(self) -> None:
        """The joined objects have to match the term and be readable, and one of them is enough"""
        join: dict[str, Any] = build_term_join_stages(VALUE_CONDITION, ACL_STAGES)[0]
        sub_pipeline: list[dict[str, Any]] = join['$lookup']['pipeline']

        assert {'$match': VALUE_CONDITION} in sub_pipeline
        assert all(stage in sub_pipeline for stage in ACL_STAGES)
        assert {'$limit': 1} in sub_pipeline

    def test_only_reference_rows_feed_the_join(self) -> None:
        """The joined ids are the values of the reference rows, filtered by kind before the join"""
        let: dict[str, Any] = build_term_join_stages(VALUE_CONDITION, [])[0]['$lookup']['let']

        assert let['references']['$map']['input']['$filter']['cond'] == {
            '$in': ['$$this.type', list(REFERENCE_FIELD_KINDS)]
        }


class TestTextTermStages:
    """Which of the three shapes a term becomes."""

    def test_no_referenced_match_is_a_plain_match(self) -> None:
        """Nothing references-worthy matched: the term matches own values, nothing else is added"""
        assert build_text_term_stages(_StubObjectsManager([]), VALUE_CONDITION, []) == [{'$match': VALUE_CONDITION}]

    def test_referenced_matches_widen_the_term(self) -> None:
        """Own values OR a reference row carrying one of the matched ids"""
        assert build_text_term_stages(_StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, []) == [
            {'$match': {'$or': [VALUE_CONDITION, build_reference_rows_condition(REFERENCED_IDS)]}}
        ]

    def test_a_term_too_broad_for_an_id_list_is_joined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Past the cap, the same rule is evaluated in the database"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', SMALL_LIMIT)

        stages = build_text_term_stages(_StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, ACL_STAGES)

        assert stages == build_term_join_stages(VALUE_CONDITION, ACL_STAGES)


OWN_CONDITION: dict[str, Any] = {'$expr': {'$eq': ['$public_id', 7]}}


class TestOwnCondition:
    """A separate condition on the candidate itself; the referenced objects keep ``value_condition``."""

    def test_the_referenced_objects_are_collected_with_the_value_condition(self) -> None:
        """Step 1 matches what may be referenced, never the candidate's own condition"""
        manager = _StubObjectsManager([])

        build_text_term_stages(manager, VALUE_CONDITION, ACL_STAGES, own_condition=OWN_CONDITION)

        assert manager.pipelines[0][0] == {'$match': VALUE_CONDITION}
        assert {'$match': OWN_CONDITION} not in manager.pipelines[0]

    def test_no_referenced_match_matches_the_own_condition(self) -> None:
        """Nothing referenced matched: only the candidate's own condition decides"""
        stages = build_text_term_stages(_StubObjectsManager([]), VALUE_CONDITION, [], own_condition=OWN_CONDITION)

        assert stages == [{'$match': OWN_CONDITION}]

    def test_referenced_matches_widen_the_own_condition(self) -> None:
        """Own condition OR a reference row carrying one of the matched ids"""
        stages = build_text_term_stages(
            _StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, [], own_condition=OWN_CONDITION,
        )

        assert stages == [{'$match': {'$or': [OWN_CONDITION, build_reference_rows_condition(REFERENCED_IDS)]}}]

    def test_the_join_matches_referenced_by_value_and_the_candidate_by_its_own(self) -> None:
        """Inside the join the value condition; outside it the candidate's own condition"""
        stages = build_term_join_stages(VALUE_CONDITION, ACL_STAGES, own_condition=OWN_CONDITION)
        sub_pipeline: list[dict[str, Any]] = stages[0]['$lookup']['pipeline']

        assert {'$match': VALUE_CONDITION} in sub_pipeline
        assert {'$match': OWN_CONDITION} not in sub_pipeline
        assert stages[1] == {'$match': {'$or': [OWN_CONDITION, {REFERENCED_MATCH_FIELD: {'$ne': []}}]}}

    def test_past_the_cap_the_join_gets_the_own_condition(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fallback keeps the split - the same answer as the id list"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', SMALL_LIMIT)

        stages = build_text_term_stages(
            _StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, ACL_STAGES, own_condition=OWN_CONDITION,
        )

        assert stages == build_term_join_stages(VALUE_CONDITION, ACL_STAGES, own_condition=OWN_CONDITION)

    def test_without_one_both_sides_use_the_value_condition(self) -> None:
        """The /search/ callers pass none, and their stages are what they were"""
        assert build_text_term_stages(_StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, []) == \
            build_text_term_stages(_StubObjectsManager(REFERENCED_IDS), VALUE_CONDITION, [], VALUE_CONDITION)
