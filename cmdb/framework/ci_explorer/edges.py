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
    ``source='ipam'`` tag so the FE can branch on styling; the wire ``relation_name`` and
    ``relation_icon`` are direction-aware (the neighbour's role from the target's
    perspective, so the same edge reads 'Supernet' from the subnet side and 'Subnet' from
    the supernet side); ``relation_label`` is the fixed verb 'assigned' on every IPAM edge
    (no CmdbRelation backs them)
  - location edges are bare ``{from, to}`` only; the FE renders them with fixed colors

The shape asymmetry is intentional in the FE contract so the composers are kept separate
rather than producing a single shape with optional fields
"""
from typing import Any

from cmdb.framework.ci_explorer.ipam import (
    IPAM_EDGE_ICONS_CHILD,
    IPAM_EDGE_ICONS_PARENT,
    IPAM_EDGE_NAMES_CHILD,
    IPAM_EDGE_NAMES_PARENT,
    IPAM_METADATA_SOURCE,
    IPAM_RELATION_COLOR,
    IPAM_RELATION_LABEL,
    IpamEdgeCategory,
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
    edge_category: IpamEdgeCategory,
    is_child_of_target: bool,
) -> dict[str, Any]:
    """
    Builds one IPAM edge dict for the CI Explorer response

    The shape mirrors ``compose_relation_edge`` so the FE can render IPAM neighbours with
    the same edge template as object-relation neighbours (per the requirement: "displayed as
    all other relations, not like the locations"). Two differences distinguish IPAM edges:
    ``metadata.relation_id`` is ``None`` because no CmdbRelation backs the edge, and
    ``metadata.source`` carries the fixed string ``'ipam'`` so the FE can branch on styling
    without having to look up the relation_id. ``metadata.relation_name`` and
    ``metadata.relation_icon`` are direction-aware - the wire string describes whichever
    end the *neighbour* sits on, so the FE label reads naturally from the target's
    perspective in either direction (e.g. the same SUBNET-SUPERNET edge reports
    ``relation_name='Supernet'`` from the SUBNET side and ``'Subnet'`` from the SUPERNET
    side). ``metadata.relation_label`` is the fixed verb ``'assigned'`` for every IPAM edge

    Args:
        edge_from (int): public_id of the edge source (parent end of the IPAM hierarchy)
        edge_to (int): public_id of the edge target (child end of the IPAM hierarchy)
        edge_category (IpamEdgeCategory): The endpoint-pair category that scopes the
            name/icon lookup
        is_child_of_target (bool): True when the neighbour is a child of the target (the
            edge goes target→neighbour in the IPAM hierarchy), False when the neighbour
            is above the target (edge goes neighbour→target). Picks the CHILD vs PARENT
            name/icon tables so the wire string describes the neighbour's role

    Returns:
        dict[str, Any]: ``{from, to, metadata: {relation_id, relation_name, relation_label,
            relation_icon, relation_color, source}}``
    """
    name_table: dict[str, str] = IPAM_EDGE_NAMES_CHILD if is_child_of_target else IPAM_EDGE_NAMES_PARENT
    icon_table: dict[str, str] = IPAM_EDGE_ICONS_CHILD if is_child_of_target else IPAM_EDGE_ICONS_PARENT

    return {
        'from': edge_from,
        'to': edge_to,
        'metadata': {
            'relation_id': None,
            'relation_name': name_table[edge_category],
            'relation_label': IPAM_RELATION_LABEL,
            'relation_icon': icon_table[edge_category],
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
