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
dict constructors; their external dependencies are resolved lazily through ManagerProvider and stubbed
here - SearchPipelineBuilder's CategoriesManager, and the TypesManager the ACL filter reads the denied
types from.

Since 2026-09-10 also: the **stage order** (the ACL stages last of the builder's own output, since the
caller appends its facet after them), the AND path of the TYPE parameters - whose test used to assert
the OR path under a name that said otherwise, because `SearchParam.disjunction` defaults to True - the
parameters that contribute no stage at all, the pattern extraction the result highlighting depends on,
and that the category parameters cost ONE query however many of them a search carries.
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
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_TYPE_IDS: list[int] = [10, 11]
GROUP_ID: int = 1
DENIED_TYPE_IDS: list[int] = [21, 22]


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


class _CountingCategoriesManager(_StubCategoriesManager):
    """A categories stub that records how often - and with what - it was queried."""

    def __init__(self) -> None:
        """Starts with an empty call log."""
        self.calls: list[dict[str, Any]] = []

    def get_categories_by(self, **kwargs: Any) -> list[_StubCategory]:
        """Records the criteria before answering the fixed category."""
        self.calls.append(kwargs)

        return super().get_categories_by(**kwargs)


class _StubTypesManager:
    """Stand-in for TypesManager answering the ACL filter's denied-types query."""

    def __init__(self, denied_type_ids: list[int]) -> None:
        self.denied_type_ids = denied_type_ids

    def find(self, **_kwargs: Any) -> list[dict[str, int]]:
        """Mirrors BaseManager.find, ignoring the criteria and returning the configured ids."""
        return [{'public_id': type_id} for type_id in self.denied_type_ids]


def _stub_manager_provider(
        monkeypatch: pytest.MonkeyPatch,
        denied_type_ids: list[int],
        categories_manager: Any = None) -> None:
    """Routes ManagerProvider.get_manager to the right stub for the requested ManagerType."""
    def _get_manager(manager_type: ManagerType, *_a: Any, **_k: Any) -> Any:
        if manager_type == ManagerType.TYPES:
            return _StubTypesManager(denied_type_ids)
        return categories_manager or _StubCategoriesManager()

    monkeypatch.setattr(
        'cmdb.manager.manager_provider_model.ManagerProvider.get_manager', _get_manager
    )


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

    def test_permission_appends_acl_stage(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """A user + permission whose group is denied a type appends the excluding $match."""
        _stub_manager_provider(monkeypatch, DENIED_TYPE_IDS)

        pipeline = QuickSearchPipelineBuilder().build(
            search_term='x', user=user, permission=AccessControlPermission.READ
        )

        assert {'type_id': {'$nin': DENIED_TYPE_IDS}} in _stages(pipeline, '$match')

    def test_permission_adds_nothing_when_no_type_is_denied(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A group that may access every type costs no extra stage at all."""
        _stub_manager_provider(monkeypatch, [])

        without = QuickSearchPipelineBuilder().build(search_term='x')
        with_acl = QuickSearchPipelineBuilder().build(
            search_term='x', user=user, permission=AccessControlPermission.READ
        )

        assert with_acl == without

    def test_final_stage_projects_counts(self) -> None:
        """The last stage projects the active / inactive / total counters."""
        pipeline = QuickSearchPipelineBuilder().build(search_term='x')

        assert set(pipeline[-1]['$project']) == {'_id', 'active', 'inactive', 'total'}


class TestSearchPipelineBuilder:
    """The full-search pipeline maps each SearchParam form onto its aggregation stage(s)."""

    @pytest.fixture(autouse=True)
    def _stub_managers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stubs the managers build() resolves lazily: CategoriesManager and the ACL TypesManager."""
        _stub_manager_provider(monkeypatch, DENIED_TYPE_IDS)

    def test_text_param_adds_regex_match(self) -> None:
        """A text param becomes a regex match on fields.value."""
        pipeline = SearchPipelineBuilder().build([SearchParam('needle', 'text')])

        assert 'needle' in list(_deep_find(pipeline, '$regex'))

    def test_type_param_adds_type_match(self) -> None:
        """
        A type param becomes a type_id $in match

        Note what this does NOT assert: `SearchParam.disjunction` defaults to True, so this param is
        DISJUNCTIVE and the match sits under an `$or`. The test used to claim the opposite in its
        docstring while asserting only the `$in`, which is why the AND path below was never executed.
        """
        pipeline = SearchPipelineBuilder().build([SearchParam('', 'type', settings={'types': [1, 2]})])

        assert {'$in': [1, 2]} in list(_deep_find(pipeline, 'type_id'))
        assert list(_deep_find(pipeline, '$or'))

    def test_non_disjunction_type_param_is_its_own_match(self) -> None:
        """
        With disjunction off, each type param is its own $match - which is AND

        Only an API client can ask for this: the search bar never sets the key, so the default (OR)
        is what every UI request gets.
        """
        pipeline = SearchPipelineBuilder().build([
            SearchParam('', 'type', settings={'types': [1, 2]}, disjunction=False),
        ])

        assert {'type_id': {'$in': [1, 2]}} in _stages(pipeline, '$match')
        assert not list(_deep_find(pipeline, '$or'))

    def test_two_non_disjunction_type_params_narrow_the_search(self) -> None:
        """Two AND-ed type filters are two separate $match stages, not one $or"""
        pipeline = SearchPipelineBuilder().build([
            SearchParam('', 'type', settings={'types': [1]}, disjunction=False),
            SearchParam('', 'type', settings={'types': [2]}, disjunction=False),
        ])
        matches = _stages(pipeline, '$match')

        assert {'type_id': {'$in': [1]}} in matches
        assert {'type_id': {'$in': [2]}} in matches

    def test_a_type_param_without_ids_adds_no_stage(self) -> None:
        """A cleared type filter must not narrow the search to nothing"""
        with_empty = SearchPipelineBuilder().build([SearchParam('', 'type', settings={'types': []})])
        without_any = SearchPipelineBuilder().build([])

        assert with_empty == without_any

    def test_a_type_param_without_settings_adds_no_stage(self) -> None:
        """`settings` is optional on a SearchParam, and None becomes {}"""
        with_none = SearchPipelineBuilder().build([SearchParam('', 'type')])

        assert with_none == SearchPipelineBuilder().build([])

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

    def test_two_category_params_cost_one_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Every category tag of a search is resolved in ONE read

        It used to be one query per tag, inside the loop - and the criteria of the batched read is
        an $or of the label patterns, since the categories are matched by LABEL.
        """
        categories_manager = _CountingCategoriesManager()
        _stub_manager_provider(monkeypatch, [], categories_manager)

        SearchPipelineBuilder().build([
            SearchParam('network', 'category', settings={'categories': [1]}),
            SearchParam('storage', 'category', settings={'categories': [2]}),
        ])

        assert len(categories_manager.calls) == 1
        assert '$or' in categories_manager.calls[0]

    def test_one_category_param_keeps_the_plain_criteria(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A single tag is not wrapped in an $or of one"""
        categories_manager = _CountingCategoriesManager()
        _stub_manager_provider(monkeypatch, [], categories_manager)

        SearchPipelineBuilder().build([SearchParam('cat', 'category', settings={'categories': [1]})])

        assert list(categories_manager.calls[0]) == ['label']

    def test_a_category_param_without_categories_reads_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A cleared category filter must not query, and must not narrow the search"""
        categories_manager = _CountingCategoriesManager()
        _stub_manager_provider(monkeypatch, [], categories_manager)

        pipeline = SearchPipelineBuilder().build([SearchParam('cat', 'category', settings={'categories': []})])

        assert not categories_manager.calls
        assert pipeline == SearchPipelineBuilder().build([])

    def test_active_flag_adds_active_match(self) -> None:
        """The active flag adds an active == True match stage."""
        pipeline = SearchPipelineBuilder().build([], active_flag=True)

        assert {'active': {'$eq': True}} in _stages(pipeline, '$match')

    def test_permission_appends_acl_stage(self, user: SimpleNamespace) -> None:
        """A user + permission whose group is denied a type appends the excluding $match."""
        pipeline = SearchPipelineBuilder().build([], user=user, permission=AccessControlPermission.READ)

        assert {'type_id': {'$nin': DENIED_TYPE_IDS}} in _stages(pipeline, '$match')

    def test_permission_adds_nothing_when_no_type_is_denied(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A group that may access every type costs no extra stage at all."""
        _stub_manager_provider(monkeypatch, [])

        without = SearchPipelineBuilder().build([])
        with_acl = SearchPipelineBuilder().build([], user=user, permission=AccessControlPermission.READ)

        assert with_acl == without

    def test_the_acl_stages_come_last(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The ACL filter must be in the pipeline before the caller appends its facet

        SearcherFramework adds a $facet AFTER this pipeline, and the facet takes both the page and
        the counts from whatever the stream holds at that point - so an ACL stage that ended up
        after it would count and answer documents the user may not read.
        """
        _stub_manager_provider(monkeypatch, DENIED_TYPE_IDS)

        without_acl = SearchPipelineBuilder().build([SearchParam('needle', 'text')])
        with_acl = SearchPipelineBuilder().build(
            [SearchParam('needle', 'text')], user=user, permission=AccessControlPermission.READ,
        )

        assert with_acl[:len(without_acl)] == without_acl
        assert len(with_acl) > len(without_acl)

    def test_the_reference_stages_come_first(self) -> None:
        """
        Every filter matches against fields.value, which the reference stages fold into

        A filter placed before them would search the object's own fields only, silently missing the
        hits inside referenced objects.
        """
        reference_stages = SearchReferencesPipelineBuilder().build()
        pipeline = SearchPipelineBuilder().build([SearchParam('needle', 'text')])

        assert pipeline[:len(reference_stages)] == reference_stages

    def test_build_ignores_a_pipeline_the_builder_was_constructed_with(self) -> None:
        """
        `build()` assembles a COMPLETE pipeline of its own

        Which is why SearcherFramework - handed a pipeline that is already built - never calls it.
        Asserted so the discard is a documented property rather than a surprise.
        """
        pre_set = [{'$match': {'public_id': 999}}]
        pipeline = SearchPipelineBuilder(pre_set).build([])

        assert pre_set[0] not in pipeline

    def test_get_regex_pipes_values(self) -> None:
        """get_regex_pipes_values extracts the regex values from the built pipeline."""
        builder = SearchPipelineBuilder()
        builder.build([SearchParam('needle', 'text')])

        assert 'needle' in builder.get_regex_pipes_values()

    def test_every_text_pattern_is_extracted_in_order(self) -> None:
        """
        One missed pattern silently costs the highlighting of that search parameter

        The searcher reads these back out of the built pipeline and the result highlights each hit's
        fields against them.
        """
        builder = SearchPipelineBuilder()
        builder.build([SearchParam('first', 'text'), SearchParam('second', 'regex')])

        assert builder.get_regex_pipes_values() == ['first', 'second']

    def test_a_pattern_nested_under_an_or_is_found(self) -> None:
        """A $match nests its expressions in lists, and a category or type filter is one level deeper"""
        builder = SearchPipelineBuilder([
            {'$match': {'$or': [{'fields.value': {'$regex': 'deep', '$options': 'ims'}}]}},
        ])

        assert builder.get_regex_pipes_values() == ['deep']

    def test_a_pattern_nested_in_a_list_of_lists_is_found(self) -> None:
        """
        The walk goes all the way down

        It used to recurse into dicts and into the dicts of a list, but not into a list inside a
        list - so a pattern one level deeper than any current stage would have been missed.
        """
        builder = SearchPipelineBuilder([
            {'$match': {'$and': [[{'fields.value': {'$regex': 'deeper'}}]]}},
        ])

        assert builder.get_regex_pipes_values() == ['deeper']

    def test_a_pipeline_without_patterns_answers_empty(self) -> None:
        """A type-only or id-only search has nothing to highlight"""
        builder = SearchPipelineBuilder()
        builder.build([SearchParam('5', 'publicID')])

        assert builder.get_regex_pipes_values() == []

    def test_an_empty_pipeline_answers_empty(self) -> None:
        """Called before build() - the searcher constructs the builder around a pipeline"""
        assert SearchPipelineBuilder().get_regex_pipes_values() == []
