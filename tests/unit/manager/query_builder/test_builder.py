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
Unit tests for Builder, the shared MongoDB operator / stage vocabulary

Every constructor is a stateless staticmethod returning one plain dict, so these pin the exact
emitted shape - which is what makes the aggregation pipelines built on top of them safe to refactor.
The abstract contract is pinned too: Builder itself must not be instantiable.
"""
import re

import pytest

from cmdb.manager.query_builder.builder import (
    Builder,
    SORT_ORDER_DUPLICATED_MSG,
    SORT_ORDER_INVALID_MSG,
    SORT_ORDER_MISSING_MSG,
    SORT_SPECIFICATION_EMPTY_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'fields.value'
SEARCH_TERM: str = 'needle'


class _ConcreteBuilder(Builder):
    """Minimal concrete subclass used to prove the abstract methods are satisfiable."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def __len__(self) -> int:
        """Number of collected items."""
        return len(self.items)

    def clear(self) -> None:
        """Drops every collected item."""
        self.items = []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 abstract contract                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAbstractContract:
    """Builder is an ABC: a subclass that forgets a method fails at construction, not at call time."""

    # Instantiating the abstract classes IS what these two assert, so pylint's warning is the
    # behaviour under test rather than a defect
    # pylint: disable=abstract-class-instantiated
    def test_builder_cannot_be_instantiated(self) -> None:
        """The base class is abstract and must not be usable on its own."""
        with pytest.raises(TypeError):
            Builder()

    def test_a_subclass_missing_the_methods_cannot_be_instantiated(self) -> None:
        """Forgetting __len__ / clear is caught immediately rather than at the failing call."""
        class _Incomplete(Builder):
            """Deliberately implements neither abstract method."""

        with pytest.raises(TypeError):
            _Incomplete()
    # pylint: enable=abstract-class-instantiated

    def test_a_complete_subclass_works(self) -> None:
        """Implementing both abstract methods is enough to construct a builder."""
        assert len(_ConcreteBuilder()) == 0

    def test_clear_resets_the_subclass(self) -> None:
        """The contract the abstract clear() describes."""
        builder = _ConcreteBuilder()
        builder.items.append({'a': 1})
        builder.clear()

        assert len(builder) == 0

    def test_constructors_are_callable_on_the_class(self) -> None:
        """The constructors are stateless, so they never need an instance."""
        assert Builder.match_({}) == {'$match': {}}

    def test_constructors_are_callable_through_an_instance(self) -> None:
        """Subclasses call them as self.match_(...), which must keep working."""
        assert _ConcreteBuilder().match_({}) == {'$match': {}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             logical query operators                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLogicalOperators:
    """$and / $or wrap a list of clauses."""

    def test_and(self) -> None:
        """Clauses are passed through untouched under $and."""
        clauses = [{'a': 1}, {'b': 2}]

        assert Builder.and_(clauses) == {'$and': clauses}

    def test_or(self) -> None:
        """Clauses are passed through untouched under $or."""
        clauses = [{'a': 1}, {'b': 2}]

        assert Builder.or_(clauses) == {'$or': clauses}

    def test_empty_clause_lists_are_not_rejected(self) -> None:
        """The constructors do not validate - callers decide what is meaningful."""
        assert Builder.and_([]) == {'$and': []}


class TestIn:
    """$in matches any of the listed values."""

    def test_in(self) -> None:
        """The field is the key and the values sit under $in."""
        assert Builder.in_('type_id', [1, 2]) == {'type_id': {'$in': [1, 2]}}

    def test_in_with_no_values(self) -> None:
        """An empty value list is emitted as-is (matches nothing in Mongo)."""
        assert Builder.in_('type_id', []) == {'type_id': {'$in': []}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     regex_                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRegex:
    """$regex carries its options, and the default must not break multi-word search terms."""

    def test_shape(self) -> None:
        """The pattern and its options sit together under the field key."""
        assert Builder.regex_(FIELD, SEARCH_TERM, 'ims') == {
            FIELD: {'$regex': SEARCH_TERM, '$options': 'ims'}
        }

    def test_default_options(self) -> None:
        """Case-insensitive, multi-line, dot-matches-newline - what a search term needs."""
        assert Builder.regex_(FIELD, SEARCH_TERM)[FIELD]['$options'] == 'ims'

    def test_default_options_exclude_the_extended_flag(self) -> None:
        """Regression: a default of 'imsx' lets 'x' make the engine ignore unescaped
        whitespace in the pattern - so a search for 'Data Center' silently matched nothing."""
        assert 'x' not in Builder.regex_(FIELD, SEARCH_TERM)[FIELD]['$options']

    def test_explicit_options_are_honoured(self) -> None:
        """A caller that wants different flags still gets them."""
        assert Builder.regex_(FIELD, SEARCH_TERM, 'i')[FIELD]['$options'] == 'i'

    def test_the_term_is_not_escaped(self) -> None:
        """The term is passed through verbatim - callers search with real expressions."""
        assert Builder.regex_(FIELD, 'a.*b')[FIELD]['$regex'] == 'a.*b'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 aggregation stages                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSimpleStages:
    """The one-key stages."""

    @pytest.mark.parametrize(
        'stage, expected',
        [
            (Builder.match_({'active': True}), {'$match': {'active': True}}),
            (Builder.count_('total'), {'$count': 'total'}),
            (Builder.skip_(10), {'$skip': 10}),
            (Builder.limit_(25), {'$limit': 25}),
            (Builder.facet_({'data': []}), {'$facet': {'data': []}}),
            (Builder.project_({'_id': 0}), {'$project': {'_id': 0}}),
            (Builder.unwind_('$items'), {'$unwind': '$items'}),
        ],
        ids=['match', 'count', 'skip', 'limit', 'facet', 'project', 'unwind'],
    )
    def test_stage_shape(self, stage: dict, expected: dict) -> None:
        """Each stage wraps its argument under the matching operator."""
        assert stage == expected

    def test_skip_zero_is_still_emitted(self) -> None:
        """A zero skip is a valid stage; suppressing it is the caller's decision."""
        assert Builder.skip_(0) == {'$skip': 0}

    def test_unwind_accepts_an_option_document(self) -> None:
        """The dict form carries options such as preserveNullAndEmptyArrays."""
        options = {'path': '$type', 'preserveNullAndEmptyArrays': True}

        assert Builder.unwind_(options) == {'$unwind': options}


class TestGroup:
    """$group always carries an _id and merges any accumulators over it."""

    def test_without_accumulators(self) -> None:
        """The grouping expression alone is a valid stage."""
        assert Builder.group_('$type_id') == {'$group': {'_id': '$type_id'}}

    def test_with_accumulators(self) -> None:
        """Accumulator fields are merged alongside _id."""
        accumulators = {'total': {'$sum': 1}}

        assert Builder.group_('$type_id', accumulators) == {'$group': {'_id': '$type_id', **accumulators}}

    def test_none_id_groups_everything(self) -> None:
        """A None _id is the Mongo idiom for one bucket over all documents."""
        assert Builder.group_(None) == {'$group': {'_id': None}}

    def test_the_accumulators_are_not_mutated(self) -> None:
        """The caller's dict is merged, never modified in place."""
        accumulators = {'total': {'$sum': 1}}
        Builder.group_('$type_id', accumulators)

        assert accumulators == {'total': {'$sum': 1}}

    def test_an_accumulator_cannot_be_lost(self) -> None:
        """Every accumulator key reaches the stage."""
        stage = Builder.group_('$type_id', {'a': 1, 'b': 2})

        assert set(stage['$group']) == {'_id', 'a', 'b'}


class TestLookup:
    """$lookup joins another collection by field equality."""

    def test_shape(self) -> None:
        """The four arguments map onto Mongo's from / localField / foreignField / as."""
        assert Builder.lookup_('framework.types', 'type_id', 'public_id', 'type') == {
            '$lookup': {
                'from': 'framework.types',
                'localField': 'type_id',
                'foreignField': 'public_id',
                'as': 'type',
            }
        }

    def test_keyword_call(self) -> None:
        """Callers pass these by keyword, so the parameter names are part of the contract."""
        stage = Builder.lookup_(
            from_collection='framework.objects',
            local_field='public_id',
            foreign_field='type_id',
            as_field='type_objects',
        )

        assert stage['$lookup']['as'] == 'type_objects'

    def test_a_plain_join_carries_no_pipeline_key(self) -> None:
        """Without a pipeline the stage stays the plain equality join every other caller builds."""
        stage = Builder.lookup_('framework.types', 'type_id', 'public_id', 'type')

        assert 'pipeline' not in stage['$lookup']

    def test_a_pipeline_rides_along_with_the_equality_match(self) -> None:
        """The concise form: localField / foreignField still decide the match, the pipeline trims it."""
        sub_pipeline = [{'$limit': 1}, {'$project': {'_id': 1}}]

        stage = Builder.lookup_('framework.objects', 'object_id', 'public_id', 'object', pipeline=sub_pipeline)

        assert stage == {
            '$lookup': {
                'from': 'framework.objects',
                'localField': 'object_id',
                'foreignField': 'public_id',
                'as': 'object',
                'pipeline': sub_pipeline,
            }
        }

    def test_an_empty_pipeline_is_kept(self) -> None:
        """`[]` is a pipeline the caller asked for; only None means "no pipeline"."""
        stage = Builder.lookup_('framework.types', 'type_id', 'public_id', 'type', pipeline=[])

        assert stage['$lookup']['pipeline'] == []


class TestCorrelatedLookup:
    """The pipeline form of $lookup: let-bound variables and a sub-pipeline."""

    def test_shape(self) -> None:
        """The four arguments map onto Mongo's from / let / pipeline / as"""
        sub_pipeline: list[dict] = [{'$match': {'$expr': {'$in': ['$public_id', '$$refs']}}}]

        assert Builder.correlated_lookup_('framework.objects', {'refs': '$fields.value'}, sub_pipeline, 'hits') == {
            '$lookup': {
                'from': 'framework.objects',
                'let': {'refs': '$fields.value'},
                'pipeline': sub_pipeline,
                'as': 'hits',
            }
        }

    def test_it_carries_no_local_or_foreign_field(self) -> None:
        """Mixing the two forms is a different join - the constructor never emits the equality keys"""
        stage = Builder.correlated_lookup_('framework.objects', {}, [], 'hits')['$lookup']

        assert 'localField' not in stage and 'foreignField' not in stage


class TestUnset:
    """$unset removes the named fields and keeps the rest."""

    def test_shape(self) -> None:
        """The field list is passed through as Mongo's array form"""
        assert Builder.unset_(['working', 'other']) == {'$unset': ['working', 'other']}

    def test_the_callers_list_is_copied(self) -> None:
        """A tuple or a list the caller keeps mutating ends up as a list of its own"""
        fields: list[str] = ['working']
        stage = Builder.unset_(fields)
        fields.append('other')

        assert stage == {'$unset': ['working']}


class TestGraphLookup:
    """$graphLookup follows one edge recursively; the location tree is built on it."""

    def test_shape(self) -> None:
        """The five arguments map onto Mongo's from / startWith / connectFromField / connectToField / as."""
        assert Builder.graph_lookup_('framework.locations', '$parent', 'parent', 'public_id', 'ancestors') == {
            '$graphLookup': {
                'from': 'framework.locations',
                'startWith': '$parent',
                'connectFromField': 'parent',
                'connectToField': 'public_id',
                'as': 'ancestors',
            }
        }

    def test_keyword_call_walks_the_edge_downwards(self) -> None:
        """The same constructor builds the opposite direction, so the parameter names are the contract."""
        stage = Builder.graph_lookup_(
            from_collection='framework.locations',
            start_with='$public_id',
            connect_from_field='public_id',
            connect_to_field='parent',
            as_field='descendants',
        )

        assert stage['$graphLookup']['startWith'] == '$public_id'
        assert stage['$graphLookup']['as'] == 'descendants'


class TestSort:
    """$sort validates its direction, which is the only guard in the whole vocabulary."""

    @pytest.mark.parametrize('order', [1, -1])
    def test_valid_orders(self, order: int) -> None:
        """Both Mongo sort directions are accepted."""
        assert Builder.sort_('public_id', order) == {'$sort': {'public_id': order}}

    @pytest.mark.parametrize('order', [0, 2, -2, 'asc'])
    def test_invalid_order_raises(self, order) -> None:
        """Anything else is rejected rather than passed to Mongo."""
        with pytest.raises(ValueError):
            Builder.sort_('public_id', order)

    def test_a_specification_keeps_its_key_order(self) -> None:
        """The first key sorts and each later one breaks ties, so the order of the keys is the contract."""
        stage = Builder.sort_({'value': -1, 'public_id': 1})

        assert stage == {'$sort': {'value': -1, 'public_id': 1}}
        assert list(stage['$sort']) == ['value', 'public_id']

    def test_a_specification_is_copied(self) -> None:
        """A caller reusing its dict must not see the stage change underneath it, nor the other way round."""
        specification = {'value': -1}
        stage = Builder.sort_(specification)
        specification['public_id'] = 1

        assert stage == {'$sort': {'value': -1}}

    @pytest.mark.parametrize('specification', [{'value': 0}, {'value': 1, 'public_id': 2}, {'value': 'desc'}])
    def test_every_order_in_a_specification_is_validated(self, specification: dict) -> None:
        """One bad direction anywhere in the specification refuses the whole stage."""
        with pytest.raises(ValueError, match=re.escape(SORT_ORDER_INVALID_MSG)):
            Builder.sort_(specification)

    def test_a_single_field_needs_its_order(self) -> None:
        """The order is optional only because a specification carries its own."""
        with pytest.raises(ValueError, match=re.escape(SORT_ORDER_MISSING_MSG)):
            Builder.sort_('public_id')

    def test_a_specification_takes_no_separate_order(self) -> None:
        """Two places for one order would let them disagree."""
        with pytest.raises(ValueError, match=re.escape(SORT_ORDER_DUPLICATED_MSG)):
            Builder.sort_({'public_id': 1}, 1)

    def test_an_empty_specification_is_refused(self) -> None:
        """MongoDB refuses an empty $sort at run time; the constructor refuses it where it is built."""
        with pytest.raises(ValueError, match=re.escape(SORT_SPECIFICATION_EMPTY_MSG)):
            Builder.sort_({})


class TestFieldStages:
    """$addFields, $set and $replaceRoot - each wraps exactly what it was given."""

    def test_add_fields(self) -> None:
        """The expression map is the stage's body, unchanged."""
        fields = {'_sort_value': {'$toLower': '$name'}}

        assert Builder.add_fields_(fields) == {'$addFields': fields}

    def test_set(self) -> None:
        """`$set` stays `$set`: the alias a caller wrote is the stage it gets."""
        fields = {'status': 'done'}

        assert Builder.set_(fields) == {'$set': fields}

    @pytest.mark.parametrize('new_root', ['$type_objects', {'$mergeObjects': ['$a', '$b']}], ids=['path', 'expression'])
    def test_replace_root(self, new_root) -> None:
        """The new root sits under `newRoot`, whether a path or an expression."""
        assert Builder.replace_root_(new_root) == {'$replaceRoot': {'newRoot': new_root}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  removed surface                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemovedConstructors:
    """The unused operator constructors were removed; this pins that they stay gone."""

    @pytest.mark.parametrize(
        'name',
        ['not_', 'nor_', 'eq_', 'gt_', 'gte_', 'lt_', 'lte_', 'ne_', 'nin_',
         'exists_', 'element_match_', 'expr_', 'lookup_sub_', 'type_'],
    )
    def test_unused_constructor_is_absent(self, name: str) -> None:
        """Re-adding one is a deliberate two-line change, not an accident."""
        assert not hasattr(Builder, name)
