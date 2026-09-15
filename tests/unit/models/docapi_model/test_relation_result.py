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
Unit tests for cmdb.models.docapi_model.relation_result.RelationResult

Pure tests (no app context, no database): managers and the render collaborators are mocked.
Covers the type() filter, the relation() hop (both sides, relation_id scoping and lazy caching of
objects and their types), and the public_id / fields / relation_fields terminals.
"""
from unittest.mock import Mock, patch

from cmdb.models.docapi_model.relation_result import RelationResult
from cmdb.models.docapi_model.relation_side_enum import RelationSide
from cmdb.models.docapi_model.aggregated_fields import AggregatedFields
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.relation_result'

TYPE_ID: str = 'type_id'
PUBLIC_ID: str = 'public_id'
RELATION_ID: str = 'relation_id'
RELATION_PARENT_ID: str = 'relation_parent_id'
RELATION_CHILD_ID: str = 'relation_child_id'
FIELD_VALUES: str = 'field_values'
NAME: str = 'name'
VALUE: str = 'value'
FIELDS: str = 'fields'

SERVER_TYPE: int = 10
APP_TYPE: int = 20
REL_HOSTS: int = 100
REL_OTHER: int = 200
TEMPLATE_TYPE: str = 'OBJECT'


def _edge(relation_id: int, parent_id: int, child_id: int, field_values: list[dict] = None) -> dict:
    """Builds an object-relation edge dict as stored in the database."""
    return {
        RELATION_ID: relation_id,
        RELATION_PARENT_ID: parent_id,
        RELATION_CHILD_ID: child_id,
        FIELD_VALUES: field_values or [],
    }


def _make_result(
    object_ids: list[int],
    object_cache: dict = None,
    type_cache: dict = None,
    object_relations: list[dict] = None,
    all_object_relations: list[dict] = None,
    objects_manager: Mock = None,
    types_manager: Mock = None,
) -> RelationResult:
    """Builds a RelationResult with mocked managers (find() -> [] by default) and empty caches."""
    default_objects_manager = Mock(name='objects_manager')
    default_objects_manager.find.return_value = []
    default_types_manager = Mock(name='types_manager')
    default_types_manager.find.return_value = []

    return RelationResult(
        object_ids,
        object_cache if object_cache is not None else {},
        type_cache if type_cache is not None else {},
        object_relations if object_relations is not None else [],
        all_object_relations if all_object_relations is not None else [],
        Mock(name='request_user'),
        objects_manager or default_objects_manager,
        types_manager or default_types_manager,
        TEMPLATE_TYPE,
    )


class TestTypeFilter:
    """type() narrows objects by type_id while preserving the caches and scoped relations."""

    def test_keeps_only_matching_type(self) -> None:
        """Only object_ids whose cached object has the given type_id survive."""
        cache = {1: {TYPE_ID: SERVER_TYPE}, 2: {TYPE_ID: APP_TYPE}, 3: {TYPE_ID: SERVER_TYPE}}
        result = _make_result([1, 2, 3], object_cache=cache).type(SERVER_TYPE)

        assert result.object_ids == [1, 3]

    def test_uncached_ids_are_dropped(self) -> None:
        """An object_id missing from the cache cannot match and is dropped."""
        cache = {1: {TYPE_ID: SERVER_TYPE}}
        result = _make_result([1, 99], object_cache=cache).type(SERVER_TYPE)

        assert result.object_ids == [1]

    def test_scoped_relations_and_caches_preserved(self) -> None:
        """The scoped relations and both caches are carried over unchanged."""
        cache = {1: {TYPE_ID: SERVER_TYPE}}
        types = {SERVER_TYPE: {PUBLIC_ID: SERVER_TYPE}}
        scoped = [_edge(REL_HOSTS, 5, 1)]
        source = _make_result([1], object_cache=cache, type_cache=types, object_relations=scoped)

        result = source.type(SERVER_TYPE)

        assert result.object_relations is scoped
        assert result.object_cache is cache
        assert result.type_cache is types


class TestRelationHop:
    """relation() follows one edge, scoping by relation_id and side and lazily filling the caches."""

    def test_child_side_collects_children(self) -> None:
        """side=child from a parent collects the child ids of matching edges."""
        edges = [_edge(REL_HOSTS, 1, 2), _edge(REL_HOSTS, 1, 3)]
        cache = {1: {TYPE_ID: SERVER_TYPE}, 2: {}, 3: {}}
        result = _make_result([1], object_cache=cache, all_object_relations=edges)

        hop = result.relation(REL_HOSTS, RelationSide.CHILD)

        assert hop.object_ids == [2, 3]
        assert hop.object_relations == edges

    def test_parent_side_collects_parents(self) -> None:
        """side=parent from a child collects the parent ids of matching edges."""
        edges = [_edge(REL_HOSTS, 5, 2)]
        cache = {2: {TYPE_ID: SERVER_TYPE}, 5: {}}
        result = _make_result([2], object_cache=cache, all_object_relations=edges)

        hop = result.relation(REL_HOSTS, RelationSide.PARENT)

        assert hop.object_ids == [5]

    def test_other_relation_id_ignored(self) -> None:
        """Edges of a different relation_id do not contribute to the hop."""
        edges = [_edge(REL_HOSTS, 1, 2), _edge(REL_OTHER, 1, 9)]
        cache = {1: {TYPE_ID: SERVER_TYPE}, 2: {}}
        result = _make_result([1], object_cache=cache, all_object_relations=edges)

        hop = result.relation(REL_HOSTS, RelationSide.CHILD)

        assert hop.object_ids == [2]

    def test_wrong_side_endpoint_ignored(self) -> None:
        """An edge whose current-side endpoint is not in object_ids is skipped."""
        edges = [_edge(REL_HOSTS, 7, 2)]
        result = _make_result([1], object_cache={1: {}}, all_object_relations=edges)

        hop = result.relation(REL_HOSTS, RelationSide.CHILD)

        assert hop.object_ids == []

    def test_missing_objects_and_types_are_cached(self) -> None:
        """Objects reached by the hop, and their types, are lazily loaded into the shared caches."""
        edges = [_edge(REL_HOSTS, 1, 2)]
        cache = {1: {TYPE_ID: SERVER_TYPE}}
        type_cache = {}
        objects_manager = Mock()
        objects_manager.find.return_value = [{PUBLIC_ID: 2, TYPE_ID: APP_TYPE}]
        types_manager = Mock()
        types_manager.find.return_value = [{PUBLIC_ID: APP_TYPE}]

        result = _make_result(
            [1],
            object_cache=cache,
            type_cache=type_cache,
            all_object_relations=edges,
            objects_manager=objects_manager,
            types_manager=types_manager,
        )
        result.relation(REL_HOSTS, RelationSide.CHILD)

        assert cache[2] == {PUBLIC_ID: 2, TYPE_ID: APP_TYPE}
        assert type_cache[APP_TYPE] == {PUBLIC_ID: APP_TYPE}


class TestPublicId:
    """public_id returns a defensive copy of the object ids."""

    def test_returns_ids(self) -> None:
        """The property returns the current object ids."""
        assert _make_result([1, 2]).public_id == [1, 2]

    def test_returns_copy(self) -> None:
        """Mutating the returned list does not affect the result."""
        result = _make_result([1, 2])
        returned = result.public_id
        returned.append(3)

        assert result.object_ids == [1, 2]


class TestFields:
    """fields renders the cached objects (batched) and aggregates their template fields."""

    def test_renderable_objects_are_batched_and_aggregated(self) -> None:
        """All renderable objects are rendered in a single CmdbMultiRender pass and aggregated."""
        cache = {1: {TYPE_ID: SERVER_TYPE}, 2: {TYPE_ID: SERVER_TYPE}}
        type_cache = {SERVER_TYPE: {PUBLIC_ID: SERVER_TYPE}}
        result = _make_result([1, 2], object_cache=cache, type_cache=type_cache)

        with patch(f'{MODULE}.CmdbObject') as cmdb_object, \
             patch(f'{MODULE}.CmdbMultiRender') as multi_render, \
             patch(f'{MODULE}.ObjectTemplateData') as template_data:
            cmdb_object.from_data.side_effect = lambda o: Mock(get_type_id=Mock(return_value=o[TYPE_ID]))
            multi_render.return_value.result.return_value = ['render_1', 'render_2']
            template_data.return_value.get_template_data.return_value = {FIELDS: {'city': 'NYC'}}

            aggregated = result.fields

            assert isinstance(aggregated, AggregatedFields)
            assert aggregated['city'] == 'NYC, NYC'
            multi_render.assert_called_once()

    def test_uncached_object_skipped(self) -> None:
        """An object_id absent from the cache contributes nothing and is not rendered."""
        result = _make_result([99], object_cache={}, type_cache={})

        with patch(f'{MODULE}.CmdbMultiRender') as multi_render:
            aggregated = result.fields

            assert aggregated['any'] == ''
            multi_render.assert_not_called()

    def test_object_with_uncached_type_skipped(self) -> None:
        """An object whose type is not cached is skipped and never rendered."""
        cache = {1: {TYPE_ID: SERVER_TYPE}}
        result = _make_result([1], object_cache=cache, type_cache={})

        with patch(f'{MODULE}.CmdbObject') as cmdb_object, \
             patch(f'{MODULE}.CmdbMultiRender') as multi_render:
            cmdb_object.from_data.side_effect = lambda o: Mock(get_type_id=Mock(return_value=o[TYPE_ID]))

            aggregated = result.fields

            assert aggregated['any'] == ''
            multi_render.assert_not_called()


class TestRelationFields:
    """relation_fields aggregates the field_values carried by the scoped edges."""

    def test_collects_named_field_values(self) -> None:
        """Named field values across scoped edges are aggregated."""
        scoped = [
            _edge(REL_HOSTS, 1, 2, [{NAME: 'role', VALUE: 'primary'}]),
            _edge(REL_HOSTS, 1, 3, [{NAME: 'role', VALUE: 'backup'}]),
        ]
        result = _make_result([1], object_relations=scoped)

        assert result.relation_fields['role'] == 'primary, backup'

    def test_unnamed_field_values_ignored(self) -> None:
        """A field value without a name is skipped, and an edge with no usable fields is dropped."""
        scoped = [_edge(REL_HOSTS, 1, 2, [{VALUE: 'orphan'}])]
        result = _make_result([1], object_relations=scoped)

        assert result.relation_fields['role'] == ''

    def test_ignores_object_ids(self) -> None:
        """relation_fields reads scoped edges regardless of the current object_ids."""
        scoped = [_edge(REL_HOSTS, 1, 2, [{NAME: 'role', VALUE: 'primary'}])]
        result = _make_result([], object_relations=scoped)

        assert result.relation_fields['role'] == 'primary'
