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

from cmdb.framework.ci_explorer.edges import compose_ipam_edge, compose_relation_edge
from cmdb.framework.ci_explorer.ipam import IpamRelationName
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


def test_compose_ipam_edge_emits_full_envelope_with_ipam_source_tag() -> None:
    """Pins the full ipam edge shape: relation_id=None, source='ipam', labels from the tables"""
    edge = compose_ipam_edge(edge_from=100, edge_to=200, relation_name=IpamRelationName.SUBNET)

    assert edge == {
        'from': 100,
        'to': 200,
        'metadata': {
            'relation_id': None,
            'relation_name': 'ipam-subnet',
            'relation_label': 'Subnet',
            'relation_icon': 'fa-sitemap',
            'relation_color': '#4A90E2',
            'source': 'ipam',
        },
    }


@pytest.mark.parametrize('relation_name,expected_label', [
    (IpamRelationName.SUPERNET, 'Supernet'),
    (IpamRelationName.SUBNET, 'Subnet'),
    (IpamRelationName.VLAN, 'VLAN'),
    (IpamRelationName.INTERFACE, 'Interface'),
])
def test_compose_ipam_edge_picks_label_from_relation_name_table(
    relation_name: IpamRelationName, expected_label: str,
) -> None:
    """Each IpamRelationName resolves to its agreed display label via the lookup table"""
    edge = compose_ipam_edge(edge_from=1, edge_to=2, relation_name=relation_name)

    assert edge['metadata']['relation_name'] == relation_name.value
    assert edge['metadata']['relation_label'] == expected_label
