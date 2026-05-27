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
Edge payload composers for the CI Explorer

The route emits three distinct edge shapes:
  - relation edges carry a ``metadata`` sub-dict with the CmdbRelation id and the
    side-specific name / icon / color
  - IPAM edges carry the *same* metadata shape but with ``relation_id=None`` and an extra
    ``source='ipam'`` tag so the FE can branch on styling; the metadata's labels and icons
    come from the IpamRelationName tables (no CmdbRelation backs them)
  - location edges are bare ``{from, to}`` only; the FE renders them with fixed colors

The shape asymmetry is intentional in the FE contract so the composers are kept separate
rather than producing a single shape with optional fields
"""
from typing import Any

from cmdb.framework.ci_explorer.ipam import (
    IPAM_METADATA_SOURCE,
    IPAM_RELATION_COLOR,
    IPAM_RELATION_ICONS,
    IPAM_RELATION_LABELS,
    IpamRelationName,
)
from cmdb.framework.ci_explorer.relations import DirectionalEdge
# -------------------------------------------------------------------------------------------------------------------- #


def compose_relation_edge(
    directional_edge: DirectionalEdge,
    relation_doc: dict[str, Any],
) -> dict[str, Any]:
    """
    Builds one object-relation edge dict for the CI Explorer response

    The edge always carries parent->child direction in the relation graph (so when the
    target is the relation's parent the edge points away from the target, otherwise it
    points toward it). The per-direction labels / icon / color are taken from
    ``directional_edge`` so the consumer only deals with already-resolved values

    Args:
        directional_edge (DirectionalEdge): The direction-aware view of the object_relation
            (from ``split_object_relation_direction``)
        relation_doc (dict[str, Any]): The CmdbRelation document referenced by the
            object_relation; carries the ``public_id`` and the top-level ``relation_name``

    Returns:
        dict[str, Any]: ``{from, to, metadata: {relation_id, relation_name, relation_label,
            relation_icon, relation_color}}``
    """
    return {
        'from': directional_edge.edge_from,
        'to': directional_edge.edge_to,
        'metadata': {
            'relation_id': relation_doc.get('public_id'),
            'relation_name': relation_doc.get('relation_name'),
            'relation_label': directional_edge.edge_relation_name,
            'relation_icon': directional_edge.edge_relation_icon,
            'relation_color': directional_edge.relation_color,
        },
    }


def compose_ipam_edge(
    edge_from: int,
    edge_to: int,
    relation_name: IpamRelationName,
) -> dict[str, Any]:
    """
    Builds one IPAM edge dict for the CI Explorer response

    The shape mirrors ``compose_relation_edge`` so the FE can render IPAM neighbours with
    the same edge template as object-relation neighbours (per the requirement: "displayed as
    all other relations, not like the locations"). Two differences distinguish IPAM edges:
    ``metadata.relation_id`` is ``None`` because no CmdbRelation backs the edge, and
    ``metadata.source`` carries the fixed string ``'ipam'`` so the FE can branch on styling
    without having to look up the relation_id. The display label, icon and color are read
    from the IPAM_RELATION_* tables in ``cmdb.framework.ci_explorer.ipam`` keyed by
    ``relation_name``

    Args:
        edge_from (int): public_id of the edge source (parent end of the IPAM hierarchy)
        edge_to (int): public_id of the edge target (child end of the IPAM hierarchy)
        relation_name (IpamRelationName): The neighbour's IPAM role; selects the label /
            icon to display on the edge

    Returns:
        dict[str, Any]: ``{from, to, metadata: {relation_id, relation_name, relation_label,
            relation_icon, relation_color, source}}``
    """
    return {
        'from': edge_from,
        'to': edge_to,
        'metadata': {
            'relation_id': None,
            'relation_name': relation_name.value,
            'relation_label': IPAM_RELATION_LABELS[relation_name],
            'relation_icon': IPAM_RELATION_ICONS[relation_name],
            'relation_color': IPAM_RELATION_COLOR,
            'source': IPAM_METADATA_SOURCE,
        },
    }


def compose_location_edge(edge_from: int, edge_to: int) -> dict[str, Any]:
    """
    Builds one location-graph edge dict for the CI Explorer response

    Deliberately bare: the FE renders location edges with the fixed
    PARENT_LOCATION_REL_COLOR / CHILD_LOCATION_REL_COLOR on the *node* side, so the edge
    itself carries only endpoints. No ``metadata`` block - that distinguishes it from
    object-relation edges on the wire

    Args:
        edge_from (int): public_id of the edge source
        edge_to (int): public_id of the edge target

    Returns:
        dict[str, Any]: ``{from, to}``
    """
    return {
        'from': edge_from,
        'to': edge_to,
    }
