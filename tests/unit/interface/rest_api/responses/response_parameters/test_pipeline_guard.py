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

* **what must be refused** - the stages and expressions that were verified reading foreign collections
  and executing JavaScript, each pinned here so a widened allow-list fails loudly
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
    assert_no_denied_expressions,
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
            assert_no_denied_expressions(
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

#: `type.service.ts:386-404` - the uncategorized-types screen, joining framework.categories
FRONTEND_UNCATEGORIZED_TYPES: list[dict[str, Any]] = [
    {'$match': {}},
    {'$lookup': {'from': 'framework.categories', 'localField': 'public_id',
                 'foreignField': 'types', 'as': 'categories'}},
    {'$match': {'categories': {'$size': 0}}},
    {'$project': {'categories': 0}},
]

#: `type.service.ts:457-470` - types by category, the one FE lookup that carries its own sub-pipeline
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


class TestTheFrontendKeepsWorking:
    """
    The constraint on every future tightening of the allow-list

    `$lookup` and `$group` are permitted only because these pipelines exist. Removing either needs
    server-side routes first - and a change that skips that step fails here.
    """

    @pytest.mark.parametrize('pipeline', [
        pytest.param(FRONTEND_OBJECT_SEARCH, id='object-list search'),
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
