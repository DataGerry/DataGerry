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
Unit tests for cmdb.framework.ci_explorer.edges

``compose_relation_edge`` and ``compose_ipam_edge`` are exercised here.
``compose_location_edge`` is a single-line dict construction and is skipped per
feedback_skip_trivial_methods
"""
import pytest

from cmdb.framework.ci_explorer.connections import (
    PORT_CONNECTION_METADATA_SOURCE,
    PORT_CONNECTION_RELATION_LABEL,
)
from cmdb.framework.ci_explorer.edges import (
    compose_ipam_edge,
    compose_port_connection_edge,
    compose_relation_edge,
)
from cmdb.framework.ci_explorer.ipam import IpamEdgeCategory
from cmdb.framework.ci_explorer.relations import DirectionalEdge
# -------------------------------------------------------------------------------------------------------------------- #


def test_compose_relation_edge_emits_full_envelope_with_metadata() -> None:
    """Pins the from/to keys and the five-field metadata block on a composed relation edge"""
    directional = DirectionalEdge(
        linked_is_child=True,
        linked_id=200,
        linked_type_id=11,
        edge_from=100,
        edge_to=200,
        relation_color='#33aa33',
        edge_relation_name='hosts',
        edge_relation_icon='fa-arrow-right',
    )
    relation_doc = {
        'public_id': 500,
        'relation_name': 'connected',
    }

    edge = compose_relation_edge(directional, relation_doc)

    assert edge == {
        'from': 100,
        'to': 200,
        'metadata': {
            'relation_id': 500,
            'relation_name': 'connected',
            'relation_label': 'hosts',
            'relation_icon': 'fa-arrow-right',
            'relation_color': '#33aa33',
        },
    }


def test_compose_ipam_edge_parent_direction_emits_full_envelope() -> None:
    """Parent direction (is_child_of_target=False): name/icon describe the parent end (neighbour)"""
    edge = compose_ipam_edge(
        edge_from=80, edge_to=64,
        edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
        is_child_of_target=False,
    )

    assert edge == {
        'from': 80,
        'to': 64,
        'metadata': {
            'relation_id': None,
            'relation_name': 'Supernet',
            'relation_label': 'assigned',
            'relation_icon': 'fa-network-wired',
            'relation_color': '#4A90E2',
            'source': 'ipam',
        },
    }


def test_compose_ipam_edge_child_direction_emits_full_envelope() -> None:
    """Child direction (is_child_of_target=True): name/icon describe the child end (neighbour)"""
    edge = compose_ipam_edge(
        edge_from=80, edge_to=64,
        edge_category=IpamEdgeCategory.SUBNET_SUPERNET,
        is_child_of_target=True,
    )

    assert edge == {
        'from': 80,
        'to': 64,
        'metadata': {
            'relation_id': None,
            'relation_name': 'Subnet',
            'relation_label': 'assigned',
            'relation_icon': 'fa-sitemap',
            'relation_color': '#4A90E2',
            'source': 'ipam',
        },
    }


@pytest.mark.parametrize('edge_category,is_child_of_target,expected_relation_name,expected_icon', [
    # Parent direction (neighbour is parent of target)
    (IpamEdgeCategory.SUBNET_SUPERNET, False, 'Supernet', 'fa-network-wired'),
    (IpamEdgeCategory.SUBNET_VLAN, False, 'Subnet', 'fa-sitemap'),
    (IpamEdgeCategory.SUBNET_INTERFACE, False, 'Subnet-IP', 'fa-sitemap'),
    # Child direction (neighbour is child of target)
    (IpamEdgeCategory.SUBNET_SUPERNET, True, 'Subnet', 'fa-sitemap'),
    (IpamEdgeCategory.SUBNET_VLAN, True, 'VLAN', 'fa-tag'),
    (IpamEdgeCategory.SUBNET_INTERFACE, True, 'Interface', 'fa-ethernet'),
])
def test_compose_ipam_edge_emits_direction_aware_name_and_icon(
    edge_category: IpamEdgeCategory,
    is_child_of_target: bool,
    expected_relation_name: str,
    expected_icon: str,
) -> None:
    """All six (category, direction) pairs emit the agreed wire relation_name + relation_icon"""
    edge = compose_ipam_edge(
        edge_from=1, edge_to=2,
        edge_category=edge_category,
        is_child_of_target=is_child_of_target,
    )

    assert edge['metadata']['relation_name'] == expected_relation_name
    assert edge['metadata']['relation_icon'] == expected_icon
    assert edge['metadata']['relation_label'] == 'assigned'


def test_compose_port_connection_edge_is_tagged_and_undirected() -> None:
    """
    The two flags the frontend branches on

    ``source`` distinguishes a collapsed physical edge from a CmdbRelation or IPAM one, and
    ``undirected`` is what suppresses the arrowhead - a cable runs between two ports, not from one
    to the other.
    """
    edge = compose_port_connection_edge(edge_from=100, edge_to=101, path=[])

    assert edge['from'] == 100
    assert edge['to'] == 101
    assert edge['metadata']['source'] == PORT_CONNECTION_METADATA_SOURCE
    assert edge['metadata']['undirected'] is True
    assert edge['metadata']['relation_label'] == PORT_CONNECTION_RELATION_LABEL


def test_compose_port_connection_edge_has_no_relation_id() -> None:
    """No CmdbRelation backs it, exactly as for an IPAM edge - the key is present and null."""
    edge = compose_port_connection_edge(edge_from=100, edge_to=101, path=[])

    assert edge['metadata']['relation_id'] is None


def test_compose_port_connection_edge_carries_the_collapsed_path() -> None:
    """
    Case C5: the hidden physical path travels on the edge

    Ordered from the focal end outwards, so a frontend can render 'Server A -> P.F07 -> ...' without
    having to re-derive which end it started from.
    """
    path = [
        {'public_id': 900, 'connection_type': 'CABLE'},
        {'public_id': 901, 'connection_type': 'INTERNAL'},
        {'public_id': 902, 'connection_type': 'CABLE'},
    ]

    edge = compose_port_connection_edge(edge_from=100, edge_to=101, path=path)

    assert [hop['public_id'] for hop in edge['metadata']['path']] == [900, 901, 902]


def test_compose_port_connection_edge_keeps_the_ipam_metadata_shape() -> None:
    """
    The FE renders every non-location edge with one template

    So the four presentation keys must be present here too, even though nothing about them is
    configurable for a physical edge.
    """
    edge = compose_port_connection_edge(edge_from=100, edge_to=101, path=[])
    ipam_edge = compose_ipam_edge(
        edge_from=1, edge_to=2, edge_category=IpamEdgeCategory.SUBNET_SUPERNET, is_child_of_target=True,
    )

    assert set(ipam_edge['metadata']).issubset(set(edge['metadata']))
