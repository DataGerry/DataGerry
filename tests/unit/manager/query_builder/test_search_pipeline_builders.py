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
Unit tests for the search aggregation-pipeline builders

Pins the MongoDB pipeline shape produced by SearchReferencesPipelineBuilder, QuickSearchPipelineBuilder
and SearchPipelineBuilder so a future optimisation of these aggregations is safe. The builders are pure
dict constructors; the only external dependency (SearchPipelineBuilder's CategoriesManager, resolved
lazily via ManagerProvider) is stubbed, and the ACL builder needs only a group_id.
"""
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from cmdb.manager.query_builder import (
    SearchReferencesPipelineBuilder,
    QuickSearchPipelineBuilder,
    SearchPipelineBuilder,
)
from cmdb.framework.search.search_param import SearchParam
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_TYPE_IDS: list[int] = [10, 11]
GROUP_ID: int = 1


def _deep_find(obj: Any, key: str) -> Iterator[Any]:
    """Yields every value stored under `key`, at any depth, within nested dicts/lists."""
    if isinstance(obj, dict):
        for current_key, value in obj.items():
            if current_key == key:
                yield value
            yield from _deep_find(value, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _deep_find(item, key)


def _stages(pipeline: list[dict], stage_op: str) -> list[Any]:
    """Returns the bodies of every top-level stage using the given operator (e.g. '$match')."""
    return [stage[stage_op] for stage in pipeline if stage_op in stage]


class _StubCategory:
    """Minimal category exposing the .types attribute the category branch reads."""

    def __init__(self, types: list[int]) -> None:
        self.types = types


class _StubCategoriesManager:
    """Stand-in for CategoriesManager returning a fixed category for any query."""

    def get_categories_by(self, **_kwargs: Any) -> list[_StubCategory]:
        """Mirrors CategoriesManager.get_categories_by, ignoring the filter."""
        return [_StubCategory(CATEGORY_TYPE_IDS)]


@pytest.fixture(name='user')
def fixture_user() -> SimpleNamespace:
    """A minimal user stub exposing only the group_id the ACL builder reads."""
    return SimpleNamespace(group_id=GROUP_ID)


class TestSearchReferencesPipelineBuilder:
    """The reference-resolution pipeline loads referenced fields alongside the object's own."""

    def test_pipeline_shape(self) -> None:
        """build() emits lookup -> project -> group -> project -> sort."""
        pipeline = SearchReferencesPipelineBuilder().build()

        assert [next(iter(stage)) for stage in pipeline] == ['$lookup', '$project', '$group', '$project', '$sort']
        assert pipeline[0]['$lookup']['from'] == 'framework.objects'

    def test_version_uses_field_reference(self) -> None:
        """The $group stage carries the version field reference (regression for the '$version' typo fix)."""
        pipeline = SearchReferencesPipelineBuilder().build()
        group_stage = _stages(pipeline, '$group')[0]

        assert group_stage['version'] == {'$first': '$version'}


class TestQuickSearchPipelineBuilder:
    """The quick-search pipeline matches on a regex and aggregates active/inactive/total counts."""

    def test_matches_search_term_regex(self) -> None:
        """The search term is applied as a regex on fields.value."""
        pipeline = QuickSearchPipelineBuilder().build(search_term='needle')

        assert 'needle' in list(_deep_find(pipeline, '$regex'))

    def test_active_flag_adds_active_condition(self) -> None:
        """With active_flag the match $and includes an active == True condition."""
        pipeline = QuickSearchPipelineBuilder().build(search_term='x', active_flag=True)

        assert {'active': {'$eq': True}} in [c for conj in _deep_find(pipeline, '$and') for c in conj]

    def test_without_active_flag_has_no_active_condition(self) -> None:
        """Without active_flag the match $and carries an empty placeholder, not an active condition."""
        pipeline = QuickSearchPipelineBuilder().build(search_term='x', active_flag=False)

        assert {'active': {'$eq': True}} not in [c for conj in _deep_find(pipeline, '$and') for c in conj]

    def test_permission_appends_acl_stages(self, user: SimpleNamespace) -> None:
        """Passing a user + permission appends the ACL stages to the pipeline."""
        without = QuickSearchPipelineBuilder().build(search_term='x')
        with_acl = QuickSearchPipelineBuilder().build(
            search_term='x', user=user, permission=AccessControlPermission.READ
        )

        assert len(with_acl) > len(without)

    def test_final_stage_projects_counts(self) -> None:
        """The last stage projects the active / inactive / total counters."""
        pipeline = QuickSearchPipelineBuilder().build(search_term='x')

        assert set(pipeline[-1]['$project']) == {'_id', 'active', 'inactive', 'total'}


class TestSearchPipelineBuilder:
    """The full-search pipeline maps each SearchParam form onto its aggregation stage(s)."""

    @pytest.fixture(autouse=True)
    def _stub_categories_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stubs ManagerProvider.get_manager (resolved lazily in build) to a stub CategoriesManager."""
        monkeypatch.setattr(
            'cmdb.manager.manager_provider_model.ManagerProvider.get_manager',
            lambda *_a, **_k: _StubCategoriesManager(),
        )

    def test_text_param_adds_regex_match(self) -> None:
        """A text param becomes a regex match on fields.value."""
        pipeline = SearchPipelineBuilder().build([SearchParam('needle', 'text')])

        assert 'needle' in list(_deep_find(pipeline, '$regex'))

    def test_type_param_adds_type_match(self) -> None:
        """A non-disjunction type param becomes a type_id $in match."""
        pipeline = SearchPipelineBuilder().build([SearchParam('', 'type', settings={'types': [1, 2]})])

        assert {'$in': [1, 2]} in list(_deep_find(pipeline, 'type_id'))

    def test_disjunction_type_param_uses_or(self) -> None:
        """A disjunction type param is combined under an $or match."""
        pipeline = SearchPipelineBuilder().build(
            [SearchParam('', 'type', settings={'types': [1]}, disjunction=True)]
        )

        assert list(_deep_find(pipeline, '$or'))

    def test_public_id_param_adds_public_id_match(self) -> None:
        """A publicID param becomes an exact public_id match (coerced to int)."""
        pipeline = SearchPipelineBuilder().build([SearchParam('5', 'publicID')])

        assert 5 in list(_deep_find(pipeline, 'public_id'))

    def test_category_param_matches_category_type_ids(self) -> None:
        """A category param resolves the category's types into a type_id $in match."""
        pipeline = SearchPipelineBuilder().build([SearchParam('cat', 'category', settings={'categories': [1]})])

        assert {'$in': CATEGORY_TYPE_IDS} in list(_deep_find(pipeline, 'type_id'))

    def test_active_flag_adds_active_match(self) -> None:
        """The active flag adds an active == True match stage."""
        pipeline = SearchPipelineBuilder().build([], active_flag=True)

        assert {'active': {'$eq': True}} in _stages(pipeline, '$match')

    def test_permission_appends_acl_stages(self, user: SimpleNamespace) -> None:
        """Passing a user + permission appends the ACL stages."""
        without = SearchPipelineBuilder().build([])
        with_acl = SearchPipelineBuilder().build([], user=user, permission=AccessControlPermission.READ)

        assert len(with_acl) > len(without)

    def test_get_regex_pipes_values(self) -> None:
        """get_regex_pipes_values extracts the regex values from the built pipeline."""
        builder = SearchPipelineBuilder()
        builder.build([SearchParam('needle', 'text')])

        assert 'needle' in builder.get_regex_pipes_values()
