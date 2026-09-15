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
Unit tests for cmdb.framework.ci_explorer.graph

Pure tests: no Mongo, no Flask. The seven sibling modules each own their own piece (argparsing, edges,
nodes, relations, ipam, locations, enrichment); this module owns the **assembly** - which was the only
layer of the package without a test of its own, and where every uncovered branch sat.

The managers are stubs, so what is exercised is the orchestration: which reads happen, what is skipped
and reported, and which bucket a composed neighbour lands in.

Four rules are pinned here:

  - the focal object must exist; a missing one raises rather than returning an empty graph, which used
    to make a typo'd id indistinguishable from an isolated CI - and with a 200
  - the focal object's CmdbType must resolve, because a graph with no root node is not the graph that
    was asked for; every OTHER missing piece is skipped and logged instead
  - the neighbour cap reads in a deterministic order, so the same request truncates the same way twice
  - the dg_location directions are inverted on purpose: the location parent lands in the CHILDREN
    bucket, the location children in the PARENT bucket
  - nothing the requesting user's object ACL denies reaches the payload, from any of the four
    sources, and a denied focal object is answered the same way a missing one is
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.ci_explorer.context import CiExplorerGraphRequest, CiExplorerManagers
from cmdb.framework.ci_explorer.connections import ConnectionNeighbour
from cmdb.framework.ci_explorer.graph import (
    ConnectionNeighbourhood,
    GraphBuckets,
    LocationNeighbourhood,
    RelationNeighbourhood,
    build_ci_explorer_graph,
    drop_denied_neighbours,
    index_by_public_id,
    load_relation_neighbourhood,
    resolve_composable,
)
from cmdb.framework.ci_explorer.ipam import IpamEdgeCategory, IpamNeighbour
from cmdb.models.ci_explorer_model import NodeType
from cmdb.errors.ci_explorer import CiExplorerGraphBuildError, CiExplorerTargetNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.framework.ci_explorer.graph'

TARGET_ID: int = 1
NEIGHBOUR_ID: int = 2
OTHER_NEIGHBOUR_ID: int = 3
TYPE_ID: int = 9
RELATION_ID: int = 5
LOCATION_PARENT_ID: int = 40
LOCATION_CHILD_ID: int = 41


def _object(public_id: int, type_id: int = TYPE_ID) -> dict[str, Any]:
    """Builds a minimal CmdbObject document"""
    return {'public_id': public_id, 'type_id': type_id, 'fields': []}


def _type_doc(public_id: int = TYPE_ID) -> dict[str, Any]:
    """Builds a minimal CmdbType document"""
    return {
        'public_id': public_id,
        'label': 'Server',
        'fields': [],
        'render_meta': {'icon': 'fa fa-server', 'summary': {'fields': []}},
    }


def _relation_doc() -> dict[str, Any]:
    """Builds a minimal CmdbRelation document"""
    return {
        'public_id': RELATION_ID,
        'relation_name_parent': 'runs',
        'relation_name_child': 'runs on',
        'relation_color_parent': '#ffffff',
        'relation_color_child': '#000000',
        'relation_icon_parent': 'fa fa-link',
        'relation_icon_child': 'fa fa-link',
    }


def _object_relation(child_id: int = NEIGHBOUR_ID) -> dict[str, Any]:
    """Builds an object relation with the target on the parent side"""
    return {
        'public_id': 11,
        'relation_id': RELATION_ID,
        'relation_parent_id': TARGET_ID,
        'relation_parent_type_id': TYPE_ID,
        'relation_child_id': child_id,
        'relation_child_type_id': TYPE_ID,
        'field_values': [],
    }


def _managers(
    root: dict[str, Any] | None = None,
    object_relations: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    linked_objects: list[dict[str, Any]] | None = None,
    types: list[dict[str, Any]] | None = None,
    location: dict[str, Any] | None = None,
) -> CiExplorerManagers:
    """
    Builds a manager bundle whose reads answer the given documents

    Args:
        root (dict | None): What get_object returns for the focal object
        object_relations (list | None): The object relations of the target
        relations (list | None): The CmdbRelation documents those reference
        linked_objects (list | None): The neighbour CmdbObjects
        types (list | None): The CmdbType documents of every object in scope
        location (dict | None): The dg_location of the target, if any

    Returns:
        CiExplorerManagers: The bundle, with every manager a MagicMock
    """
    objects_manager, types_manager = MagicMock(), MagicMock()
    relations_manager, object_relations_manager, locations_manager = MagicMock(), MagicMock(), MagicMock()

    objects_manager.get_object.return_value = root if root is not None else _object(TARGET_ID)
    objects_manager.find.return_value = linked_objects if linked_objects is not None else []
    object_relations_manager.find.return_value = object_relations or []
    relations_manager.find.return_value = relations or []
    types_manager.find.return_value = types if types is not None else [_type_doc()]
    locations_manager.get_location_for_object.return_value = location
    locations_manager.find.return_value = []

    return CiExplorerManagers(
        objects=objects_manager,
        types=types_manager,
        relations=relations_manager,
        object_relations=object_relations_manager,
        locations=locations_manager,
    )


def _request(**overrides: Any) -> CiExplorerGraphRequest:
    """Builds a graph request for the target, with the given fields replaced"""
    defaults: dict[str, Any] = {'target_id': TARGET_ID, 'target_type': NodeType.BOTH}
    defaults.update(overrides)

    return CiExplorerGraphRequest(**defaults)


class TestTheFocalObjectMustExist:
    """The 404 half of the contract."""

    def test_a_missing_target_raises(self) -> None:
        """
        An empty graph and a graph of nothing used to be the same 200 response

        Which meant a mistyped id looked exactly like an isolated CI, and nothing in the payload could
        tell the two apart.
        """
        managers = _managers()
        managers.objects.get_object.return_value = None

        with pytest.raises(CiExplorerTargetNotFoundError) as caught:
            build_ci_explorer_graph(_request(), managers)

        assert str(TARGET_ID) in str(caught.value)

    def test_the_target_is_loaded_even_without_root_or_ipam(self) -> None:
        """
        The read used to be skipped unless the root block or the IPAM walk needed it

        Existence is now checked on every request, which is what the 404 rests on - one indexed read
        by public_id.
        """
        managers = _managers()

        build_ci_explorer_graph(_request(with_root=False, with_ipam_relations=False), managers)

        managers.objects.get_object.assert_called_once_with(TARGET_ID)

    def test_a_missing_root_type_raises_rather_than_dropping_the_root_node(self) -> None:
        """
        with_root=True and no CmdbType used to answer 200 with no root_node at all

        The frontend then draws neighbours around nothing. A type cannot be deleted while its objects
        exist, so reaching this means the data is inconsistent - which is worth reporting, not hiding.
        """
        managers = _managers(types=[])

        with pytest.raises(CiExplorerGraphBuildError):
            build_ci_explorer_graph(_request(with_root=True), managers)

    def test_a_missing_root_type_is_tolerated_when_no_root_was_asked_for(self) -> None:
        """Nothing is raised for a block the caller did not request."""
        managers = _managers(types=[])

        response = build_ci_explorer_graph(_request(with_root=False), managers)

        assert 'root_node' not in response


class TestTheCapIsDeterministic:
    """The truncation half of the contract."""

    def test_the_linked_objects_are_read_sorted_and_capped(self) -> None:
        """
        A 'limit' without a 'sort' returns natural order, which MongoDB does not guarantee

        So which 50 of 500 neighbours a user saw could differ between two identical requests, and
        change as documents were rewritten.
        """
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        build_ci_explorer_graph(_request(item_limit=50), managers)

        assert managers.objects.find.call_args.kwargs['sort'] == [('public_id', 1)]
        assert managers.objects.find.call_args.kwargs['limit'] == 50

    def test_an_unlimited_request_reads_without_a_cap(self) -> None:
        """item_limit=0 means unlimited, and the sort costs nothing there either."""
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        build_ci_explorer_graph(_request(item_limit=0), managers)

        assert managers.objects.find.call_args.kwargs['limit'] == 0

    def test_truncation_is_reported_in_the_log(self) -> None:
        """
        The payload has no field that could say "this graph is partial"

        So the one place it can be noticed is the log - which is what makes a support question about a
        missing neighbour answerable.
        """
        managers = _managers(
            object_relations=[_object_relation(), _object_relation(OTHER_NEIGHBOUR_ID)],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            build_ci_explorer_graph(_request(item_limit=1), managers)

        assert any('truncated' in str(call) for call in mock_logger.warning.call_args_list)

    def test_an_edge_whose_neighbour_lost_the_cap_is_dropped_with_it(self) -> None:
        """An edge to a node that is not in the payload would be an edge to nowhere."""
        managers = _managers(
            object_relations=[_object_relation(), _object_relation(OTHER_NEIGHBOUR_ID)],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        response = build_ci_explorer_graph(_request(item_limit=1), managers)

        assert len(response['child_edges']) == 1
        assert len(response['children_nodes']) == 1


class TestNothingIsDroppedSilently:
    """Every skip is logged, because a partial graph reads exactly like a complete one."""

    def test_an_object_relation_naming_a_missing_relation_is_reported(self) -> None:
        """The CmdbRelation is gone but the instance survived - the edge cannot be drawn."""
        managers = _managers(object_relations=[_object_relation()], relations=[])

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            response = build_ci_explorer_graph(_request(), managers)

        assert response['child_edges'] == []
        assert mock_logger.warning.called

    def test_a_neighbour_without_a_type_is_reported(self) -> None:
        """A neighbour whose CmdbType cannot be resolved is skipped, not crashed on."""
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID, type_id=404)],
            types=[],
        )

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            response = build_ci_explorer_graph(_request(), managers)

        assert response['children_nodes'] == []
        assert mock_logger.warning.called

    def test_documents_without_a_public_id_are_counted_in_one_warning(self) -> None:
        """
        index_by_public_id drops what it cannot key, and says how many

        One warning rather than one per document: a malformed batch is a single event.
        """
        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            indexed = index_by_public_id([{'public_id': 1}, {'public_id': 'x'}, {}])

        assert indexed == {1: {'public_id': 1}}
        mock_logger.warning.assert_called_once()

    def test_a_clean_batch_logs_nothing(self) -> None:
        """The normal case has to stay quiet, or the warning means nothing."""
        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            index_by_public_id([{'public_id': 1}, {'public_id': 2}])

        mock_logger.warning.assert_not_called()

    def test_an_object_relation_naming_neither_side_is_reported(self) -> None:
        """A relation instance that does not involve the target cannot be given a direction."""
        unrelated: dict[str, Any] = _object_relation()
        unrelated['relation_parent_id'] = 77
        unrelated['relation_child_id'] = 88

        managers = _managers(
            object_relations=[unrelated],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            neighbourhood = load_relation_neighbourhood(_request(), managers)

        assert neighbourhood.directional_edges == []
        assert mock_logger.warning.called


class TestTheLocationDirectionsAreInverted:
    """The rule most likely to be 'fixed' by a later reader."""

    def test_the_location_parent_lands_in_the_children_bucket(self) -> None:
        """
        The graph reads "contains" downwards while the location tree reads "is contained by" upwards

        So the object's location parent is drawn as one of its children.
        """
        managers = _managers(
            linked_objects=[],
            types=[_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object',
                   return_value=_object(LOCATION_PARENT_ID)), \
             patch(f'{MODULE_PATH}.collect_location_children_objects', return_value=[]):
            response = build_ci_explorer_graph(_request(with_locations=True), managers)

        assert [node['linked_object']['public_id'] for node in response['children_nodes']] == [
            LOCATION_PARENT_ID,
        ]
        assert response['parent_nodes'] == []

    def test_the_location_children_land_in_the_parent_bucket(self) -> None:
        """The mirror of the same inversion."""
        managers = _managers(
            linked_objects=[],
            types=[_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object', return_value=None), \
             patch(f'{MODULE_PATH}.collect_location_children_objects',
                   return_value=[_object(LOCATION_CHILD_ID)]):
            response = build_ci_explorer_graph(_request(with_locations=True), managers)

        assert [node['linked_object']['public_id'] for node in response['parent_nodes']] == [
            LOCATION_CHILD_ID,
        ]
        assert response['children_nodes'] == []

    def test_no_location_read_happens_when_the_flag_is_off(self) -> None:
        """The location branch costs nothing for the default request."""
        managers = _managers()

        build_ci_explorer_graph(_request(with_locations=False), managers)

        managers.locations.get_location_for_object.assert_not_called()


class TestTheResponseShape:
    """Which keys the envelope carries, and why."""

    @pytest.mark.parametrize('target_type, expected_keys', [
        (NodeType.BOTH, {'children_nodes', 'child_edges', 'parent_nodes', 'parent_edges'}),
        (NodeType.CHILD, {'children_nodes', 'child_edges'}),
        (NodeType.PARENT, {'parent_nodes', 'parent_edges'}),
    ], ids=['BOTH', 'CHILD', 'PARENT'])
    def test_the_direction_decides_the_buckets(
        self, target_type: NodeType, expected_keys: set[str],
    ) -> None:
        """A caller asking for one direction is not handed the other one's empty lists."""
        response = build_ci_explorer_graph(_request(target_type=target_type), _managers())

        assert set(response) == expected_keys

    def test_the_root_block_is_present_only_when_asked_for(self) -> None:
        """with_root is the only thing that puts a root_node in the envelope."""
        with_root = build_ci_explorer_graph(_request(with_root=True), _managers())
        without_root = build_ci_explorer_graph(_request(with_root=False), _managers())

        assert 'root_node' in with_root
        assert 'root_node' not in without_root

    def test_the_root_node_carries_no_relation_colour(self) -> None:
        """
        The focal node is not reached through a relation, so it has no edge colour to inherit

        Every other composed node carries the colour of the edge that led to it - a relation's, a
        location's or IPAM's - which is what makes None here meaningful rather than missing.
        """
        response = build_ci_explorer_graph(_request(with_root=True), _managers())

        assert response['root_node']['linked_object']['public_id'] == TARGET_ID
        assert response['root_node']['relation_color'] is None


class TestBuckets:
    """The container the three compose passes share."""

    def test_a_node_grafted_twice_appears_once(self) -> None:
        """
        Nodes are keyed by public_id, edges are not

        An object that is both a relation neighbour and a location neighbour is one node with two
        edges, not two nodes.
        """
        buckets = GraphBuckets()
        buckets.child_nodes_by_id[NEIGHBOUR_ID] = {'linked_object': {'public_id': NEIGHBOUR_ID}}
        buckets.child_nodes_by_id[NEIGHBOUR_ID] = {'linked_object': {'public_id': NEIGHBOUR_ID}}
        buckets.child_edges.extend([{'edge': 1}, {'edge': 2}])

        assert len(buckets.child_nodes_by_id) == 1
        assert len(buckets.child_edges) == 2

    def test_each_bucket_starts_empty(self) -> None:
        """The default factories keep two graphs from sharing one list."""
        first, second = GraphBuckets(), GraphBuckets()
        first.child_edges.append({'edge': 1})

        assert second.child_edges == []


class TestTheLocationBudget:
    """How the location branch spends the slots the relation branch left."""

    def test_a_target_without_a_location_grafts_nothing(self) -> None:
        """with_locations only means "look"; an object outside the location tree simply has no hop."""
        managers = _managers(location=None)

        with patch(f'{MODULE_PATH}.collect_location_parent_object') as mock_parent:
            response = build_ci_explorer_graph(_request(with_locations=True), managers)

        mock_parent.assert_not_called()
        assert response['children_nodes'] == []

    def test_the_parent_hop_spends_one_slot(self) -> None:
        """
        The children hop is offered what the parent hop left, not the original budget

        Spending the cap twice is how a limit of 1 used to return two location neighbours.
        """
        managers = _managers(
            types=[_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object',
                   return_value=_object(LOCATION_PARENT_ID)), \
             patch(f'{MODULE_PATH}.collect_location_children_objects', return_value=[]) as mock_children:
            build_ci_explorer_graph(_request(with_locations=True, item_limit=3), managers)

        assert mock_children.call_args.args[2] == 2

    def test_the_children_hop_spends_what_it_used(self) -> None:
        """The IPAM branch then starts from what is genuinely left."""
        managers = _managers(
            types=[_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object', return_value=None), \
             patch(f'{MODULE_PATH}.collect_location_children_objects',
                   return_value=[_object(LOCATION_CHILD_ID)]), \
             patch(f'{MODULE_PATH}.collect_ipam_neighbours', return_value=[]) as mock_ipam:
            build_ci_explorer_graph(
                _request(with_locations=True, with_ipam_relations=True, item_limit=3), managers,
            )

        assert mock_ipam.call_args.kwargs['remaining'] == 2

    def test_an_unlimited_request_spends_nothing(self) -> None:
        """With no cap the budget is meaningless, and the helpers ignore it."""
        managers = _managers(
            types=[_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object',
                   return_value=_object(LOCATION_PARENT_ID)), \
             patch(f'{MODULE_PATH}.collect_location_children_objects', return_value=[]) as mock_children:
            build_ci_explorer_graph(_request(with_locations=True, item_limit=0), managers)

        assert mock_children.call_args.args[3] is False


class TestTheGraftedNeighboursCanAlsoBeSkipped:
    """The same "log it, do not crash" rule on the location and IPAM branches."""

    def test_a_location_parent_without_a_type_is_reported(self) -> None:
        """Skipped like a relation neighbour, and reported the same way."""
        managers = _managers(
            types=[],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object',
                   return_value=_object(LOCATION_PARENT_ID, type_id=404)), \
             patch(f'{MODULE_PATH}.collect_location_children_objects', return_value=[]), \
             patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            response = build_ci_explorer_graph(_request(with_locations=True), managers)

        assert response['children_nodes'] == []
        assert mock_logger.warning.called

    def test_a_location_child_without_a_type_is_reported(self) -> None:
        """The loop continues, so one broken child does not lose the others."""
        managers = _managers(
            types=[],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object', return_value=None), \
             patch(f'{MODULE_PATH}.collect_location_children_objects',
                   return_value=[_object(LOCATION_CHILD_ID, type_id=404)]), \
             patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            response = build_ci_explorer_graph(_request(with_locations=True), managers)

        assert response['parent_nodes'] == []
        assert mock_logger.warning.called

    def test_an_ipam_neighbour_without_a_type_is_reported(self) -> None:
        """Same rule on the third branch."""
        neighbour = IpamNeighbour(
            neighbour_object=_object(77, type_id=404),
            is_child_of_target=True,
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
        )
        managers = _managers(types=[])

        with patch(f'{MODULE_PATH}.collect_ipam_neighbours', return_value=[neighbour]), \
             patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            response = build_ci_explorer_graph(_request(with_ipam_relations=True), managers)

        assert response['children_nodes'] == []
        assert mock_logger.warning.called

    def test_an_object_without_a_public_id_is_dropped_from_the_enrichment(self) -> None:
        """
        The enrichment keys by public_id, so a document without one cannot be composed later

        Reported once here rather than silently vanishing between the load and the compose pass.
        """
        neighbour = IpamNeighbour(
            neighbour_object={'type_id': TYPE_ID, 'fields': []},
            is_child_of_target=True,
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
        )
        managers = _managers()

        with patch(f'{MODULE_PATH}.collect_ipam_neighbours', return_value=[neighbour]), \
             patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            build_ci_explorer_graph(_request(with_ipam_relations=True), managers)

        assert any('public_id' in str(call) for call in mock_logger.warning.call_args_list)


class TestTheIpamNeighboursFoldIntoTheStandardBuckets:
    """IPAM hops are drawn as ordinary parent/child neighbours, with a marked edge."""

    @pytest.mark.parametrize('is_child, node_key, edge_key', [
        (True, 'children_nodes', 'child_edges'),
        (False, 'parent_nodes', 'parent_edges'),
    ], ids=['child_of_target', 'parent_of_target'])
    def test_the_direction_decides_the_bucket(
        self, is_child: bool, node_key: str, edge_key: str,
    ) -> None:
        """A SUBNET hangs under its SUPERNET the same way a relation child hangs under its parent."""
        neighbour = IpamNeighbour(
            neighbour_object=_object(77),
            is_child_of_target=is_child,
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
        )
        managers = _managers(types=[_type_doc()])

        with patch(f'{MODULE_PATH}.collect_ipam_neighbours', return_value=[neighbour]):
            response = build_ci_explorer_graph(_request(with_ipam_relations=True), managers)

        assert [node['linked_object']['public_id'] for node in response[node_key]] == [77]
        assert len(response[edge_key]) == 1

    def test_no_ipam_walk_happens_when_the_flag_is_off(self) -> None:
        """The IPAM branch costs nothing for the default request."""
        managers = _managers()

        with patch(f'{MODULE_PATH}.collect_ipam_neighbours') as mock_ipam:
            build_ci_explorer_graph(_request(with_ipam_relations=False), managers)

        mock_ipam.assert_not_called()


class TestTheTypeLoad:
    """The single $in that resolves every in-scope object's CmdbType."""

    def test_the_types_are_read_once_for_the_whole_union(self) -> None:
        """One round trip whatever the graph contains - the property the pipeline is built around."""
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        build_ci_explorer_graph(_request(), managers)

        managers.types.find.assert_called_once()

    def test_no_type_read_happens_when_nothing_declares_one(self) -> None:
        """
        An object without a type_id cannot contribute an id to the '$in'

        Skipping the query is what keeps a malformed graph from costing a round trip that could only
        return nothing.
        """
        managers = _managers(root={'public_id': TARGET_ID, 'fields': []})

        build_ci_explorer_graph(_request(with_root=False), managers)

        managers.types.find.assert_not_called()


class TestResolveComposable:
    """The guard the three compose passes share."""

    def test_a_neighbour_without_a_public_id_is_skipped_not_crashed_on(self) -> None:
        """
        The compose passes used to dereference public_id with '[]'

        One step after the enrichment had deliberately skipped that document - so a single malformed
        neighbour turned the whole request into a 500 instead of a graph missing one node.
        """
        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            resolved = resolve_composable({'type_id': TYPE_ID}, {TYPE_ID: _type_doc()}, {}, 'IPAM neighbour')

        assert resolved is None
        assert 'public_id' in str(mock_logger.warning.call_args)

    def test_a_neighbour_without_a_type_is_skipped(self) -> None:
        """A node needs its CmdbType for label, icon and colour; there is nothing to draw without it."""
        with patch(f'{MODULE_PATH}.LOGGER'):
            resolved = resolve_composable(_object(NEIGHBOUR_ID), {}, {NEIGHBOUR_ID: {}}, 'Location child')

        assert resolved is None

    def test_a_neighbour_without_enrichment_is_skipped(self) -> None:
        """The enrichment is what turns stored fields into the flat shape the node composer reads."""
        with patch(f'{MODULE_PATH}.LOGGER'):
            resolved = resolve_composable(_object(NEIGHBOUR_ID), {TYPE_ID: _type_doc()}, {}, 'Relation neighbour')

        assert resolved is None

    def test_a_complete_neighbour_resolves_to_its_three_parts(self) -> None:
        """The happy path returns exactly what compose_node needs, so no caller re-reads the maps."""
        enriched: dict[str, Any] = {'public_id': NEIGHBOUR_ID}

        resolved = resolve_composable(
            _object(NEIGHBOUR_ID), {TYPE_ID: _type_doc()}, {NEIGHBOUR_ID: enriched}, 'Relation neighbour',
        )

        assert resolved == (NEIGHBOUR_ID, _type_doc(), enriched)

    def test_the_role_names_what_was_dropped(self) -> None:
        """Three call sites share this guard, so the warning has to say which branch lost a node."""
        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            resolve_composable(_object(NEIGHBOUR_ID), {}, {}, 'Location parent')

        assert 'Location parent' in str(mock_logger.warning.call_args)


class TestTheLocationBranchFollowsTheRequestedDirection:
    """A one-directional request does not pay for the hop it will not show."""

    def test_a_parent_only_request_skips_the_location_parent_hop(self) -> None:
        """
        target_type=PARENT shows only the parent bucket, which the location CHILDREN feed

        So the location parent hop - whose result would land in the children bucket - is not walked at
        all, and its read is not paid for.
        """
        managers = _managers(location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID})

        with patch(f'{MODULE_PATH}.collect_location_parent_object') as mock_parent, \
             patch(f'{MODULE_PATH}.collect_location_children_objects', return_value=[]) as mock_children:
            build_ci_explorer_graph(
                _request(target_type=NodeType.PARENT, with_locations=True), managers,
            )

        mock_parent.assert_not_called()
        mock_children.assert_called_once()

    def test_a_child_only_request_skips_the_location_children_hop(self) -> None:
        """The mirror of the same inversion, on the other direction."""
        managers = _managers(location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID})

        with patch(f'{MODULE_PATH}.collect_location_parent_object', return_value=None) as mock_parent, \
             patch(f'{MODULE_PATH}.collect_location_children_objects') as mock_children:
            build_ci_explorer_graph(
                _request(target_type=NodeType.CHILD, with_locations=True), managers,
            )

        mock_parent.assert_called_once()
        mock_children.assert_not_called()


# --------------------------------------------- OBJECT ACL (backlog #146) -------------------------------------------- #

DENIED_TYPE_ID: int = 77
GROUP_ID: int = 2


def _user(group_id: int = GROUP_ID) -> Any:
    """A CmdbUser stand-in carrying the two attributes the access filter reads"""
    return SimpleNamespace(group_id=group_id, public_id=1)


def _locked_type_doc(public_id: int = DENIED_TYPE_ID) -> dict[str, Any]:
    """A CmdbType whose activated ACL names no group, so it denies every user"""
    return _type_doc(public_id) | {'acl': {'activated': True, 'groups': {'includes': {}}}}


class TestTheObjectAclFiltersEverySource:
    """
    Backlog #146: until 2026-09-15 the graph consulted no ACL at all

    A user who could open the CI Explorer learned the label, type and neighbourhood of objects they
    could not read anywhere else in the product. Each source is pinned separately because each one
    grafts its neighbours through a different branch.
    """

    def test_a_denied_relation_neighbour_is_omitted(self) -> None:
        """The neighbour and its edge go together - an edge to a node that is not there draws nothing."""
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID)],
            types=[_type_doc(), _locked_type_doc()],
        )

        response = build_ci_explorer_graph(_request(), managers, _user())

        assert response['children_nodes'] == []
        assert response['child_edges'] == []

    def test_an_open_neighbour_of_the_same_request_survives(self) -> None:
        """The filter is per type, so a mixed neighbourhood keeps the half the user may read."""
        managers = _managers(
            object_relations=[_object_relation(), _object_relation() | {
                'public_id': 12, 'relation_child_id': OTHER_NEIGHBOUR_ID, 'relation_child_type_id': DENIED_TYPE_ID,
            }],
            relations=[_relation_doc()],
            linked_objects=[
                _object(NEIGHBOUR_ID),
                _object(OTHER_NEIGHBOUR_ID, type_id=DENIED_TYPE_ID),
            ],
            types=[_type_doc(), _locked_type_doc()],
        )

        response = build_ci_explorer_graph(_request(), managers, _user())

        assert [node['linked_object']['public_id'] for node in response['children_nodes']] == [NEIGHBOUR_ID]
        assert len(response['child_edges']) == 1

    def test_a_denied_location_neighbour_is_omitted(self) -> None:
        """The location branch grafts raw objects, so it needs the filter as much as the relations do."""
        managers = _managers(
            linked_objects=[],
            types=[_type_doc(), _locked_type_doc()],
            location={'public_id': 60, 'parent': 61, 'object_id': TARGET_ID},
        )

        with patch(f'{MODULE_PATH}.collect_location_parent_object',
                   return_value=_object(LOCATION_PARENT_ID, type_id=DENIED_TYPE_ID)), \
             patch(f'{MODULE_PATH}.collect_location_children_objects',
                   return_value=[_object(LOCATION_CHILD_ID, type_id=DENIED_TYPE_ID)]):
            response = build_ci_explorer_graph(_request(with_locations=True), managers, _user())

        assert response['children_nodes'] == []
        assert response['parent_nodes'] == []
        assert response['child_edges'] == []
        assert response['parent_edges'] == []

    def test_a_denied_ipam_neighbour_is_omitted(self) -> None:
        """The IPAM walk reaches supernets and VLANs, which carry their own ACLs like anything else."""
        managers = _managers(linked_objects=[], types=[_type_doc(), _locked_type_doc()])
        neighbour = IpamNeighbour(
            neighbour_object=_object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID),
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
            is_child_of_target=True,
        )

        with patch(f'{MODULE_PATH}.collect_ipam_neighbours', return_value=[neighbour]):
            response = build_ci_explorer_graph(_request(with_ipam_relations=True), managers, _user())

        assert response['children_nodes'] == []
        assert response['child_edges'] == []

    def test_a_denied_focal_object_is_reported_as_missing(self) -> None:
        """
        A 403 would confirm the object exists, which is exactly what the ACL hides

        So the denial raises what a missing target raises, and the route answers the same 404.
        """
        managers = _managers(
            root=_object(TARGET_ID, type_id=DENIED_TYPE_ID),
            types=[_locked_type_doc()],
        )

        with pytest.raises(CiExplorerTargetNotFoundError):
            build_ci_explorer_graph(_request(with_root=True), managers, _user())

    def test_a_denied_neighbour_costs_no_enrichment(self) -> None:
        """
        The filter runs before the enrichment pass, not after it

        Otherwise a denied object still pays for its summary and dg_location lookups, and its
        referenced ids still travel in the $in of a query built for a user who may not see it.
        """
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID)],
            types=[_type_doc(), _locked_type_doc()],
        )

        with patch(f'{MODULE_PATH}.enrich_in_scope_objects', return_value={}) as mock_enrich:
            build_ci_explorer_graph(_request(), managers, _user())

        in_scope_objects = mock_enrich.call_args.args[0]

        assert [obj['public_id'] for obj in in_scope_objects] == [TARGET_ID]

    def test_without_a_user_nothing_is_filtered(self) -> None:
        """
        The convention every manager here follows: an internal caller with no user is not checked

        Passing None must not quietly turn the graph into an empty one.
        """
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID)],
            types=[_type_doc(), _locked_type_doc()],
        )

        response = build_ci_explorer_graph(_request(), managers)

        assert [node['linked_object']['public_id'] for node in response['children_nodes']] == [NEIGHBOUR_ID]

    def test_an_open_graph_is_untouched_by_the_filter(self) -> None:
        """The common case - no type in scope carries an activated ACL - behaves as it always did."""
        managers = _managers(
            object_relations=[_object_relation()],
            relations=[_relation_doc()],
            linked_objects=[_object(NEIGHBOUR_ID)],
        )

        with_user = build_ci_explorer_graph(_request(with_root=True), managers, _user())
        without_user = build_ci_explorer_graph(_request(with_root=True), managers)

        assert with_user == without_user


class TestDropDeniedNeighbours:
    """The filter itself, driven directly - the orchestrator only decides when to call it."""

    def test_the_relation_edge_goes_with_its_object(self) -> None:
        """A surviving edge whose far end was dropped would point at nothing."""
        directional_edge = SimpleNamespace(linked_id=NEIGHBOUR_ID)
        relation_neighbourhood = RelationNeighbourhood(
            directional_edges=[(directional_edge, _relation_doc())],
            linked_objects={NEIGHBOUR_ID: _object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID)},
        )

        drop_denied_neighbours(
            relation_neighbourhood, LocationNeighbourhood(), [], {DENIED_TYPE_ID},
        )

        assert not relation_neighbourhood.directional_edges
        assert not relation_neighbourhood.linked_objects

    def test_both_location_directions_are_filtered(self) -> None:
        """The parent hop and the children hop are separate fields and both can be denied."""
        location_neighbourhood = LocationNeighbourhood(
            parent_object=_object(LOCATION_PARENT_ID, type_id=DENIED_TYPE_ID),
            children_objects=[
                _object(LOCATION_CHILD_ID, type_id=DENIED_TYPE_ID),
                _object(OTHER_NEIGHBOUR_ID),
            ],
        )

        drop_denied_neighbours(
            RelationNeighbourhood(), location_neighbourhood, [], {DENIED_TYPE_ID},
        )

        assert location_neighbourhood.parent_object is None
        assert [obj['public_id'] for obj in location_neighbourhood.children_objects] == [OTHER_NEIGHBOUR_ID]

    def test_the_ipam_list_is_returned_rather_than_mutated(self) -> None:
        """It arrives as a plain list, unlike the two dataclasses the function edits in place."""
        denied = IpamNeighbour(
            neighbour_object=_object(NEIGHBOUR_ID, type_id=DENIED_TYPE_ID),
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
            is_child_of_target=True,
        )
        kept = IpamNeighbour(
            neighbour_object=_object(OTHER_NEIGHBOUR_ID),
            edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
            is_child_of_target=True,
        )

        remaining = drop_denied_neighbours(
            RelationNeighbourhood(), LocationNeighbourhood(), [denied, kept], {DENIED_TYPE_ID},
        )

        assert remaining == [kept]


# ------------------------------------ PORT CONNECTIVITY (step 14) ---------------------------------------------------- #

CONNECTED_CI_ID: int = 55


def _connection_neighbourhood(neighbour_id: int = CONNECTED_CI_ID, type_id: int = TYPE_ID) -> Any:
    """What the connection source hands the orchestrator for one physically connected CI"""
    return ConnectionNeighbourhood(
        neighbours=[ConnectionNeighbour(neighbour_object_id=neighbour_id, path=[{'public_id': 900}])],
        objects={neighbour_id: _object(neighbour_id, type_id=type_id)},
    )


class TestThePortConnectionSource:
    """
    Step 14: the CI-level projection of the physical layer, folded into the existing envelope

    The walk itself is tested in test_connections.py; what is pinned here is the wiring - when the
    source runs, which bucket its result lands in, and that the ACL reaches it like every other one.
    """

    def test_the_source_is_off_by_default(self) -> None:
        """It matches with_locations and with_ipam_relations: opt-in, and free when not asked for."""
        managers = _managers()

        with patch(f'{MODULE_PATH}.collect_connection_neighbours') as mock_collect:
            build_ci_explorer_graph(_request(), managers)

        mock_collect.assert_not_called()

    def test_a_connected_ci_lands_in_the_children_bucket(self) -> None:
        """
        Q37: an undirected edge has no parent side, so it rides in the children bucket

        With metadata.undirected set, which is what tells the frontend to draw no arrowhead.
        """
        managers = _managers(types=[_type_doc()])

        with patch(f'{MODULE_PATH}.load_connection_neighbourhood',
                   return_value=_connection_neighbourhood()):
            response = build_ci_explorer_graph(_request(with_port_connections=True), managers)

        assert [node['linked_object']['public_id'] for node in response['children_nodes']] == [CONNECTED_CI_ID]
        assert response['child_edges'][0]['to'] == CONNECTED_CI_ID
        assert response['child_edges'][0]['metadata']['undirected'] is True
        assert response['parent_nodes'] == []

    def test_a_parents_only_request_gets_no_connections(self) -> None:
        """
        Q37 again, from the other side

        A caller asking for parents must not silently receive undirected content it has nowhere to
        put - so the source is not even consulted.
        """
        managers = _managers()

        with patch(f'{MODULE_PATH}.collect_connection_neighbours') as mock_collect:
            build_ci_explorer_graph(
                _request(with_port_connections=True, target_type=NodeType.PARENT), managers,
            )

        mock_collect.assert_not_called()

    def test_without_the_port_managers_the_source_is_skipped(self) -> None:
        """
        The three managers are optional on the bundle, because the route resolves them only for
        this flag

        An internal caller that does not know about a licensed source must get a graph, not a 500.
        """
        managers = _managers()

        response = build_ci_explorer_graph(_request(with_port_connections=True), managers)

        assert response['children_nodes'] == []

    def test_a_denied_connected_ci_is_omitted(self) -> None:
        """Backlog #146 reaches the newest source too - it was the one that sharpened the question."""
        managers = _managers(types=[_type_doc(), _locked_type_doc()])

        with patch(f'{MODULE_PATH}.load_connection_neighbourhood',
                   return_value=_connection_neighbourhood(type_id=DENIED_TYPE_ID)):
            response = build_ci_explorer_graph(
                _request(with_port_connections=True), managers, _user(),
            )

        assert response['children_nodes'] == []
        assert response['child_edges'] == []

    def test_the_connected_ci_is_enriched_like_any_other_node(self) -> None:
        """It goes through the same bulk type load and enrichment pass, not a path of its own."""
        managers = _managers(types=[_type_doc()])

        with patch(f'{MODULE_PATH}.load_connection_neighbourhood',
                   return_value=_connection_neighbourhood()), \
             patch(f'{MODULE_PATH}.enrich_in_scope_objects', return_value={}) as mock_enrich:
            build_ci_explorer_graph(_request(with_port_connections=True), managers)

        in_scope_ids = [obj['public_id'] for obj in mock_enrich.call_args.args[0]]

        assert CONNECTED_CI_ID in in_scope_ids
