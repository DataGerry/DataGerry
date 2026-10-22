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
Unit tests for the client-pipeline guard

Two halves, and the second is the one that keeps the product working:

* **what must be refused** - the stages and expressions that were verified reading foreign collections,
  executing JavaScript, or making one document cost more than the query's whole time budget, each
  pinned here so a widened allow-list fails loudly
* **what must keep being accepted** - the pipelines the Angular frontend actually builds, transcribed
  from `app/src` verbatim. `$lookup` and `$group` are in the allow-list *only* because of these, so a
  future tightening has to break a test here before it breaks a live screen

The pipelines below are copies of frontend source, not inventions. If a screen changes, the copy is
what needs updating - and noticing that is the point.
"""
from typing import Any

import pytest

from cmdb.interface.rest_api.responses.response_parameters.pipeline_guard import (
    assert_client_filter_is_allowed,
    assert_expressions_are_allowed,
    count_array_building_operators,
    count_stages,
    count_value_reads,
    loop_variables_of,
    variable_name,
)
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    MAX_ARRAY_BUILDING_OPERATORS,
    MAX_FILTER_STAGES,
)
from tests.utils.filter_cost_payloads import (
    FIFTY_FIELDS,
    FRONTEND_OBJECTS_BY_TYPE_SEARCH,
    MEASURED_PAYLOADS,
    nested_map,
)
# -------------------------------------------------------------------------------------------------------------------- #

JS_FUNCTION: dict[str, Any] = {'$function': {'body': 'function(){ return 1; }', 'args': [], 'lang': 'js'}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                     reading a collection the caller did not ask for                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestForeignCollectionReads:
    """The disclosure half, which the guard is what closes."""

    def test_a_lookup_into_the_user_collection_is_refused(self) -> None:
        """
        The exact request that returned a password digest

        `GET /users/?filter=[…{"$lookup":{"from":"management.users",…,"as":"email"}}]` answered 200
        with the stored digest in the body, aliased over a field the model serialises.
        """
        with pytest.raises(ValueError, match='management.users'):
            assert_client_filter_is_allowed([
                {'$match': {}},
                {'$lookup': {'from': 'management.users', 'pipeline': [{'$limit': 1}], 'as': 'email'}},
            ])

    def test_a_lookup_without_a_from_is_refused(self) -> None:
        """An absent target is not an allow-listed target - the check is membership, not inequality."""
        with pytest.raises(ValueError, match=r'\$lookup'):
            assert_client_filter_is_allowed([{'$lookup': {'as': 'x'}}])

    def test_a_lookup_that_is_not_a_document_is_refused(self) -> None:
        """A stage body of the wrong type must not reach MongoDB to be complained about there."""
        with pytest.raises(ValueError, match='document'):
            assert_client_filter_is_allowed([{'$lookup': ['management.users']}])

    @pytest.mark.parametrize('stage', [
        {'$graphLookup': {'from': 'management.users', 'startWith': '$public_id',
                          'connectFromField': 'public_id', 'connectToField': 'public_id', 'as': 'email'}},
        {'$unionWith': {'coll': 'management.users'}},
    ])
    def test_the_other_cross_collection_stages_are_refused(self, stage: dict[str, Any]) -> None:
        """
        Both were verified answering 200 with foreign documents

        They are refused by absence from the allow-list rather than by a rule of their own, which is
        the property worth having: a stage nobody thought about is refused by default.
        """
        with pytest.raises(ValueError, match='not permitted'):
            assert_client_filter_is_allowed([{'$match': {}}, stage])


# -------------------------------------------------------------------------------------------------------------------- #
#                                        executing JavaScript inside a filter                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestJavaScriptExpressions:
    """
    The half a stage-name allow-list does NOT close

    `$function` is an expression, not a stage, so it rides inside a permitted one. It was verified
    executing from inside `$match`/`$expr` - a plain filtered read.
    """

    def test_a_function_inside_a_permitted_add_fields_is_refused(self) -> None:
        """Where it was first found."""
        with pytest.raises(ValueError, match=r'\$function'):
            assert_client_filter_is_allowed([{'$addFields': {'email': JS_FUNCTION}}])

    def test_a_function_inside_a_match_expression_is_refused(self) -> None:
        """The decisive case: `$match` is the stage every allow-list has to permit."""
        with pytest.raises(ValueError, match=r'\$function'):
            assert_client_filter_is_allowed([{'$match': {'$expr': {'$eq': [JS_FUNCTION, 1]}}}])

    def test_a_dict_shaped_filter_is_scanned_too(self) -> None:
        """
        A dict filter becomes a single `$match` downstream, so it carries expressions just as well

        Guarding only the list shape would leave the simpler one open.
        """
        with pytest.raises(ValueError, match=r'\$where'):
            assert_client_filter_is_allowed({'$where': 'function(){ return true; }'})

    def test_it_is_found_at_depth(self) -> None:
        """Nesting is not a hiding place - the walk is recursive through dicts and lists alike."""
        with pytest.raises(ValueError, match=r'\$accumulator'):
            assert_expressions_are_allowed(
                {'a': [{'b': {'c': [{'$accumulator': {'lang': 'js'}}]}}]},
            )

    def test_a_function_nested_in_a_lookups_own_pipeline_is_refused(self) -> None:
        """A `$lookup`'s sub-pipeline is a pipeline, and would otherwise be a second unguarded door."""
        with pytest.raises(ValueError, match=r'\$function'):
            assert_client_filter_is_allowed([{'$lookup': {
                'from': 'framework.objects',
                'pipeline': [{'$addFields': {'x': JS_FUNCTION}}],
                'as': 'data',
            }}])

    def test_a_foreign_lookup_nested_in_a_lookups_own_pipeline_is_refused(self) -> None:
        """The same door, used for the disclosure rather than for the JavaScript."""
        with pytest.raises(ValueError, match='not permitted|may only target'):
            assert_client_filter_is_allowed([{'$lookup': {
                'from': 'framework.objects',
                'pipeline': [{'$unionWith': {'coll': 'management.users'}}],
                'as': 'data',
            }}])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    write stages                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWriteStages:
    """
    Refused by name, not by accident

    Before the guard, `$out` and `$merge` failed only because the pager appends `$sort` / `$skip`
    after the client's stages and a write stage must be last. Any pipeline that put a client stage
    last would have turned disclosure into arbitrary writes.
    """

    @pytest.mark.parametrize('stage', [{'$out': 'sink'}, {'$merge': {'into': 'sink'}}])
    def test_a_write_stage_is_refused_and_says_so(self, stage: dict[str, Any]) -> None:
        """The message has to name writing, or the next reader re-derives why it is refused."""
        with pytest.raises(ValueError, match='may not write'):
            assert_client_filter_is_allowed([{'$match': {}}, stage])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    stage shape                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStageShape:
    """A stage is one document naming one operator; anything else is not a pipeline."""

    @pytest.mark.parametrize('stages', ['not-a-list', {'$match': {}}, 7])
    def test_a_lookups_nested_pipeline_must_be_a_list(self, stages: Any) -> None:
        """Checked where it matters - the outer filter's shape is settled by the caller."""
        with pytest.raises(ValueError, match='must be a list'):
            assert_client_filter_is_allowed([{'$lookup': {
                'from': 'framework.objects', 'pipeline': stages, 'as': 'data',
            }}])

    @pytest.mark.parametrize('stage', [
        {'$match': {}, '$project': {}},
        {},
        'raw-string',
        ['$match'],
    ])
    def test_an_entry_that_is_not_one_stage_is_refused(self, stage: Any) -> None:
        """Two operators in one document is not a stage MongoDB would accept either."""
        with pytest.raises(ValueError, match='one aggregation stage'):
            assert_client_filter_is_allowed([stage])


# -------------------------------------------------------------------------------------------------------------------- #
#                            what the frontend sends - transcribed from app/src, must pass                             #
# -------------------------------------------------------------------------------------------------------------------- #
#: `object.component.ts:288-415` - the object list's free-text search. Reference fields are resolved by
#: joining framework.objects onto itself, which is why `$lookup` and `$group` are allow-listed at all
FRONTEND_OBJECT_SEARCH: list[dict[str, Any]] = [
    {'$lookup': {'from': 'framework.objects', 'localField': 'fields.value',
                 'foreignField': 'public_id', 'as': 'data'}},
    {'$project': {'_id': 1, 'public_id': 1, 'type_id': 1, 'active': 1, 'author_id': 1,
                  'creation_time': 1, 'last_edit_time': 1, 'fields': 1,
                  'simple': {'$reduce': {'input': '$data.fields', 'initialValue': [],
                                         'in': {'$setUnion': ['$$value', '$$this']}}}}},
    {'$group': {'_id': '$_id', 'public_id': {'$first': '$public_id'}, 'type_id': {'$first': '$type_id'},
                'active': {'$first': '$active'}, 'author_id': {'$first': '$author_id'},
                'creation_time': {'$first': '$creation_time'}, 'last_edit_time': {'$first': '$last_edit_time'},
                'fields': {'$first': '$fields'}, 'simple': {'$first': '$simple'}}},
    {'$project': {'_id': '$_id', 'public_id': 1, 'type_id': 1, 'active': 1, 'author_id': 1,
                  'creation_time': 1, 'last_edit_time': 1, 'fields': 1,
                  'references': {'$setUnion': ['$fields', '$simple']}}},
    {'$addFields': {'creationString': {'$dateToString': {'format': '%Y-%m-%dT%H:%M:%S.%LZ',
                                                         'date': '$creation_time'}}}},
    {'$addFields': {'editString': {'$dateToString': {'format': '%Y-%m-%dT%H:%M:%S.%LZ',
                                                     'date': '$last_edit_time'}}}},
    {'$addFields': {'public_id': {'$toString': '$public_id'}}},
    {'$match': {'$or': [{'creationString': {'$regex': 'abc', '$options': 'ims'}},
                        {'references': {'$elemMatch': {'value': {'$regex': 'abc', '$options': 'ism'}}}}]}},
]

#: The uncategorized-types screen's pipeline, joining framework.categories. The screen now asks
#: `GET /types/?uncategorized=` instead, but an API caller may still send it, so the shape stays accepted
FRONTEND_UNCATEGORIZED_TYPES: list[dict[str, Any]] = [
    {'$match': {}},
    {'$lookup': {'from': 'framework.categories', 'localField': 'public_id',
                 'foreignField': 'types', 'as': 'categories'}},
    {'$match': {'categories': {'$size': 0}}},
    {'$project': {'categories': 0}},
]

#: Types by category, a lookup that carries its own sub-pipeline. The screen now asks
#: `GET /types/?category=` instead; the shape stays accepted for the same reason
FRONTEND_TYPES_BY_CATEGORY: list[dict[str, Any]] = [
    {'$lookup': {'from': 'framework.categories',
                 'let': {'type_public_id': '$public_id'},
                 'pipeline': [{'$match': {'public_id': 3}},
                              {'$match': {'$expr': {'$in': ['$$type_public_id', '$types']}}}],
                 'as': 'category'}},
    {'$match': {'category.0': {'$exists': True}}},
    {'$project': {'category': 0}},
]

#: `webhook-log-viewer.component.ts:230-262` - the delivery-log search box
FRONTEND_WEBHOOK_LOG_SEARCH: list[dict[str, Any]] = [
    {'$addFields': {'webhook_id_str': {'$toString': '$webhook_id'},
                    'response_code_str': {'$toString': '$response_code'},
                    'event_time_str': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$event_time'}}}},
    {'$match': {'$or': [{'webhook_id_str': {'$regex': '7', '$options': 'i'}}]}},
]


# -------------------------------------------------------------------------------------------------------------------- #
#                         one document costing more than the query's whole time budget                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPerDocumentCost:
    """
    MongoDB checks `maxTimeMS` between documents, not inside an expression

    So the budget bounds a read over many documents, and only the guard can bound one document. Its
    rules keep the work per document in proportion to the document's own size.
    """

    @pytest.mark.parametrize('pipeline,reason', [payload[1:] for payload in MEASURED_PAYLOADS],
                             ids=[payload[0] for payload in MEASURED_PAYLOADS])
    def test_a_measured_payload_is_refused(self, pipeline: list[dict[str, Any]], reason: str) -> None:
        """Each one, as it was measured, and the refusal names what gave it away"""
        with pytest.raises(ValueError, match=reason):
            assert_client_filter_is_allowed(pipeline)

    def test_the_same_shapes_are_refused_in_a_dict_filter(self) -> None:
        """A dict filter is a `$match`, and `$expr` carries the same expressions into it"""
        with pytest.raises(ValueError, match='inside the'):
            assert_client_filter_is_allowed({'$expr': {'$gt': [nested_map(2), 0]}})


class TestTheOperatorAllowList:
    """Below the stages, an operator nobody has considered is refused by default - as an unknown stage is."""

    @pytest.mark.parametrize('operator', ['$range', '$let', '$filter', '$zip', '$concat', '$text', '$comment'])
    def test_an_operator_outside_the_list_is_refused_by_name(self, operator: str) -> None:
        """The message names the operator, so a caller knows which part to change"""
        with pytest.raises(ValueError, match=rf"'\{operator}' is not permitted \(allowed:"):
            assert_client_filter_is_allowed([{'$addFields': {'x': {operator: []}}}])

    def test_the_javascript_operators_keep_their_own_message(self) -> None:
        """Refused by the deny-list first, so the refusal still says why"""
        with pytest.raises(ValueError, match='executes JavaScript'):
            assert_client_filter_is_allowed({'$where': 'true'})

    @pytest.mark.parametrize('criteria', [
        {'public_id': {'$gte': 3, '$lt': 9}},
        {'$nor': [{'active': False}], 'fields.value': {'$nin': [1, 2]}},
        {'tags': {'$all': ['a'], '$size': 1}, 'name': {'$not': {'$regex': 'x'}}},
    ])
    def test_an_ordinary_query_operator_is_accepted(self, criteria: dict[str, Any]) -> None:
        """The query operators an API caller's filters use cost constant work per value"""
        assert_client_filter_is_allowed(criteria)


class TestTheLoopRules:
    """What a `$map` / `$reduce` may do, so one pass over an array stays one pass."""

    def test_a_loop_inside_another_loops_in_is_refused(self) -> None:
        """Nested, they multiply"""
        with pytest.raises(ValueError, match=r"'\$reduce' is not permitted inside"):
            assert_client_filter_is_allowed([{'$addFields': {'x': {'$map': {
                'input': FIFTY_FIELDS, 'in': {'$reduce': {'input': '$$this.list', 'initialValue': 0, 'in': 1}},
            }}}}])

    def test_a_loop_feeding_another_is_accepted(self) -> None:
        """In the `input`, one loop runs after the other - the costs add, they do not multiply"""
        assert_client_filter_is_allowed([{'$addFields': {'x': {'$map': {
            'input': {'$map': {'input': FIFTY_FIELDS, 'in': '$$this.value'}}, 'in': '$$this',
        }}}}])

    @pytest.mark.parametrize('reference', ['$fields', '$$ROOT', '$$CURRENT.fields', '$$other'])
    def test_an_in_reading_beyond_its_own_variables_is_refused(self, reference: str) -> None:
        """A field path or a foreign variable re-reads the document per element"""
        with pytest.raises(ValueError, match='only read the loop'):
            assert_client_filter_is_allowed([{'$addFields': {'x': {'$map': {
                'input': FIFTY_FIELDS, 'as': 'row', 'in': {'$concatArrays': [[reference], ['$$row']]},
            }}}}])

    @pytest.mark.parametrize('as_name,reference', [('row', '$$row.value'), (None, '$$this.name')])
    def test_an_in_reading_its_own_variable_is_accepted(self, as_name: str | None, reference: str) -> None:
        """The `as` name, or `this` when the body names none - a path below it included"""
        body: dict[str, Any] = {'input': FIFTY_FIELDS, 'in': {'$toString': reference}}

        if as_name:
            body['as'] = as_name

        assert_client_filter_is_allowed([{'$addFields': {'x': {'$map': body}}}])

    def test_a_literal_string_in_an_in_is_accepted(self) -> None:
        """A format or a type name is not a reference"""
        assert_client_filter_is_allowed([{'$addFields': {'x': {'$map': {
            'input': FIFTY_FIELDS, 'in': {'$eq': [{'$type': '$$this.value'}, 'date']},
        }}}}])

    def test_a_reduce_reading_its_value_through_a_path_twice_is_refused(self) -> None:
        """`$$value.items` is still the running value"""
        with pytest.raises(ValueError, match='only once'):
            assert_client_filter_is_allowed([{'$addFields': {'x': {'$reduce': {
                'input': FIFTY_FIELDS, 'initialValue': {'items': []},
                'in': {'$concatArrays': ['$$value.items', '$$value.items']},
            }}}}])

    @pytest.mark.parametrize('operator', ['$map', '$reduce'])
    def test_a_loop_body_that_is_not_a_document_is_refused(self, operator: str) -> None:
        """Checked here rather than left to MongoDB"""
        with pytest.raises(ValueError, match='must be a document'):
            assert_client_filter_is_allowed([{'$addFields': {'x': {operator: [FIFTY_FIELDS]}}}])

    @pytest.mark.parametrize('operator', ['$concatArrays', '$setUnion'])
    @pytest.mark.parametrize('operands', [[FIFTY_FIELDS, FIFTY_FIELDS, FIFTY_FIELDS], FIFTY_FIELDS])
    def test_an_array_join_takes_a_list_of_two(self, operator: str, operands: Any) -> None:
        """Three operands triple an array; a bare value is not the list MongoDB expects"""
        with pytest.raises(ValueError, match='at most 2 arrays'):
            assert_client_filter_is_allowed([{'$addFields': {'x': {operator: operands}}}])


class TestTheFilterSize:
    """The caps that bound how often a filter can grow an array."""

    def test_the_stage_cap_is_inclusive(self) -> None:
        """Exactly the cap is accepted; one more is refused"""
        assert_client_filter_is_allowed([{'$match': {}}] * MAX_FILTER_STAGES)

        with pytest.raises(ValueError, match=f'at most {MAX_FILTER_STAGES} stages'):
            assert_client_filter_is_allowed([{'$match': {}}] * (MAX_FILTER_STAGES + 1))

    def test_a_lookups_own_stages_count_towards_the_cap(self) -> None:
        """Otherwise the cap would be one `$lookup` away from meaningless"""
        lookup: dict[str, Any] = {'$lookup': {'from': 'framework.objects', 'as': 'data',
                                              'pipeline': [{'$match': {}}] * MAX_FILTER_STAGES}}

        with pytest.raises(ValueError, match='nested pipelines included'):
            assert_client_filter_is_allowed([lookup])

    def test_the_array_operator_cap_is_inclusive(self) -> None:
        """Exactly the cap is accepted; one more is refused - counted across stages"""
        stage: dict[str, Any] = {'$addFields': {'x': {'$setUnion': [FIFTY_FIELDS, FIFTY_FIELDS]}}}

        assert_client_filter_is_allowed([stage] * MAX_ARRAY_BUILDING_OPERATORS)

        with pytest.raises(ValueError, match=f'at most {MAX_ARRAY_BUILDING_OPERATORS}'):
            assert_client_filter_is_allowed([stage] * (MAX_ARRAY_BUILDING_OPERATORS + 1))

    def test_a_dict_filter_is_held_to_the_array_operator_cap(self) -> None:
        """Its `$expr` can build arrays as well as a stage can"""
        joins: list[Any] = [{'$concatArrays': [FIFTY_FIELDS, FIFTY_FIELDS]}] * (MAX_ARRAY_BUILDING_OPERATORS + 1)

        with pytest.raises(ValueError, match=f'at most {MAX_ARRAY_BUILDING_OPERATORS}'):
            assert_client_filter_is_allowed({'$expr': {'$in': [1, joins]}})


class TestTheHelpers:
    """The small functions the rules are built from, one by one."""

    @pytest.mark.parametrize('reference,expected', [
        ('$$this', 'this'), ('$$row.value.deep', 'row'), ('$fields', None), ('date', None),
    ])
    def test_variable_name(self, reference: str, expected: str | None) -> None:
        """The variable without its path; None for anything that is not a `$$`-reference"""
        assert variable_name(reference) == expected

    @pytest.mark.parametrize('operator,body,expected', [
        ('$reduce', {'as': 'ignored'}, frozenset({'value', 'this'})),
        ('$map', {'as': 'row'}, frozenset({'row'})),
        ('$map', {}, frozenset({'this'})),
    ])
    def test_loop_variables_of(self, operator: str, body: dict[str, Any], expected: frozenset[str]) -> None:
        """A `$reduce` ignores `as`; a `$map` binds it, or `this`"""
        assert loop_variables_of(operator, body) == expected

    def test_count_value_reads(self) -> None:
        """Every reference to the running value, a path below it included - and nothing else, numbers neither"""
        assert count_value_reads({'a': ['$$value', {'b': '$$value.x'}], 'c': '$$this', 'd': '$value', 'e': 7}) == 2

    def test_count_array_building_operators(self) -> None:
        """At any depth, each of the four once; other operators not at all"""
        value: Any = [{'$map': {'in': {'$setUnion': [[], []]}}}, {'$reduce': {}}, {'$concatArrays': []},
                      {'$cond': [1, 2, 3]}]

        assert count_array_building_operators(value) == 4

    def test_count_stages(self) -> None:
        """A `$lookup`'s own pipeline is counted, recursively"""
        inner: dict[str, Any] = {'$lookup': {'pipeline': [{'$match': {}}, {'$match': {}}]}}
        outer: dict[str, Any] = {'$lookup': {'pipeline': [inner, {'$match': {}}]}}

        assert count_stages([outer, {'$match': {}}, {'$project': {}}]) == 7


class TestTheFrontendKeepsWorking:
    """
    The constraint on every future tightening of the allow-list

    `$lookup` and `$group` are permitted only because these pipelines exist. Removing either needs
    server-side routes first - and a change that skips that step fails here.
    """

    @pytest.mark.parametrize('pipeline', [
        pytest.param(FRONTEND_OBJECT_SEARCH, id='object-list search'),
        pytest.param(FRONTEND_OBJECTS_BY_TYPE_SEARCH, id='objects-by-type search'),
        pytest.param(FRONTEND_UNCATEGORIZED_TYPES, id='uncategorized types'),
        pytest.param(FRONTEND_TYPES_BY_CATEGORY, id='types by category'),
        pytest.param(FRONTEND_WEBHOOK_LOG_SEARCH, id='webhook delivery-log search'),
    ])
    def test_a_real_frontend_pipeline_is_accepted(self, pipeline: list[dict[str, Any]]) -> None:
        """Transcribed from app/src - accepting these is the definition of not breaking the UI."""
        assert_client_filter_is_allowed(pipeline)

    def test_an_ordinary_dict_filter_is_accepted(self) -> None:
        """The common shape by far: most list calls send a plain match document."""
        assert_client_filter_is_allowed({'type_id': 3, 'active': True})

    @pytest.mark.parametrize('empty', [None, {}, []])
    def test_an_absent_filter_is_accepted(self, empty: Any) -> None:
        """No filter is not a refused filter."""
        assert_client_filter_is_allowed(empty)
