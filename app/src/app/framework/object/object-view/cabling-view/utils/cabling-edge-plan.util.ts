/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { PortSide } from '../../ports-overview/models/ports-overview.types';
import { CablingEdgeEnd, CablingEdgePlan, CablingRouteKind } from '../models/cabling-routing.types';
import { CablingAnchorSide, CablingEdge, CablingNodeLayout, CablingPoint } from '../models/cabling.types';
import { anchorOffset } from './cabling-node-frame.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Anchors both ends of a cable and picks how it is routed; null when either end is not on the canvas. */
export function planEdge(
    edge: CablingEdge,
    layouts: ReadonlyMap<number, CablingNodeLayout>,
    focal: CablingNodeLayout | null
): CablingEdgePlan | null {
    const fromNode = layouts.get(edge.from.object_id);
    const toNode = layouts.get(edge.to.object_id);

    if (!fromNode || !toNode) {
        return null;
    }

    const fromSide = anchorSide(fromNode, edge.from.side, toNode, edge.to.side, focal);
    const toSide = anchorSide(toNode, edge.to.side, fromNode, edge.from.side, focal);
    const from = { node: fromNode, point: anchorPoint(fromNode, edge.from.port_id, fromSide), side: fromSide };
    const to = { node: toNode, point: anchorPoint(toNode, edge.to.port_id, toSide), side: toSide };

    return { edge, from, to, kind: routeKind(from, to) };
}


export function direction(side: CablingAnchorSide): number {
    return side === 'left' ? -1 : 1;
}


/** The port's face points away from the far end, so the cable has to turn back around its card. */
export function facesAway(end: CablingEdgeEnd, other: CablingEdgeEnd): boolean {
    return direction(end.side) * (other.point.x - end.point.x) <= 0;
}


/** From the focal object's right face to a card of a second sub-column. */
export function passesWrap(near: CablingEdgeEnd, far: CablingEdgeEnd): boolean {
    return near.node.focal && near.side === 'right' && far.node.wrapped;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function routeKind(from: CablingEdgeEnd, to: CablingEdgeEnd): CablingRouteKind {
    if (sharesColumn(from.node, to.node) && from.side === to.side) {
        return 'bracket';
    }

    if (passesWrap(from, to) || passesWrap(to, from)) {
        return 'passage';
    }

    return facesAway(from, to) || facesAway(to, from) ? 'hook' : 'curve';
}


function sharesColumn(first: CablingNodeLayout, second: CablingNodeLayout): boolean {
    return first.column === second.column && first.wrapped === second.wrapped;
}


/**
 * A panel's front is its left face and its rear the right. A plain port faces its peer: the panel face it meets
 * when they share a column, else the peer's side, or outwards when level.
 */
function anchorSide(
    layout: CablingNodeLayout,
    side: PortSide | null,
    peer: CablingNodeLayout,
    peerSide: PortSide | null,
    focal: CablingNodeLayout | null
): CablingAnchorSide {
    const face = panelFace(layout, side) ?? (sharesColumn(layout, peer) ? panelFace(peer, peerSide) : null);

    if (face) {
        return face;
    }

    const own = centre(layout);
    const other = centre(peer);

    if (own !== other) {
        return other < own ? 'left' : 'right';
    }

    return focal && own < centre(focal) ? 'left' : 'right';
}


function panelFace(layout: CablingNodeLayout, side: PortSide | null): CablingAnchorSide | null {
    if (!layout.patchPanel) {
        return null;
    }

    if (side === PortSide.FRONT) {
        return 'left';
    }

    return side === PortSide.REAR ? 'right' : null;
}


function centre(layout: CablingNodeLayout): number {
    return layout.x + layout.width / 2;
}


function anchorPoint(layout: CablingNodeLayout, portId: number, side: CablingAnchorSide): CablingPoint {
    return {
        x: side === 'left' ? layout.x : layout.x + layout.width,
        y: layout.y + anchorOffset(layout, portId)
    };
}
