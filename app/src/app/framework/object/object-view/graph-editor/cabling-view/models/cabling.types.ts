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
import { PortDeviceKind } from '../../../ports-overview/models/port-bulk.types';
import { ResolvedCable } from '../../../ports-overview/models/port-connection.types';
import {
    PatchPanelOverviewRow,
    PortSide,
    StandardOverviewRow
} from '../../../ports-overview/models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How the CI Explorer presents a type; the cabling view reuses it so an object looks the same in both. */
export interface CablingTypeInfo {
    type_id: number | null;
    type_color: string | null;
    label: string | null;
    icon: string | null;
}


/** An object the user may read, with every one of its ports as the ports overview rows them. */
export interface ReadableCablingNode {
    object_id: number;
    restricted?: false;
    /** The type's CI Explorer label field; null when the type names none. */
    title: string | number | null;
    type_info: CablingTypeInfo | null;
    device_kind: PortDeviceKind | null;
    /** Counts ports, not rows: a patch panel row holds two. */
    port_count: number;
    rows: Array<StandardOverviewRow | PatchPanelOverviewRow>;
}


/** An object at the far end of a visible cable that the user may not read: its id and nothing else. */
export interface RestrictedCablingNode {
    object_id: number;
    restricted: true;
}


export type CablingNode = ReadableCablingNode | RestrictedCablingNode;


/** One end of a cable. Name and side are null when the end sits on a restricted object. */
export interface CablingEnd {
    object_id: number | null;
    port_id: number;
    port_name: string | null;
    side: PortSide | null;
}


/** One cable between two ports. `from`/`to` follow the stored endpoint order, not a direction. */
export interface CablingEdge {
    connection_id: number;
    from: CablingEnd;
    to: CablingEnd;
    cable: ResolvedCable | null;
}


/** Both cabling routes answer with this envelope, so one merge handles the ring and an expansion. */
export interface CablingResponse {
    focal_object_id: number;
    nodes: CablingNode[];
    edges: CablingEdge[];
}


/** How a node came onto the canvas, which is what the layout places it by. */
export interface CablingReveal {
    parentId: number | null;
    parentPortId: number | null;
    ownPortId: number | null;
    column: number;
    generation: number;
}


/** Everything drawn so far. Maps keep insertion order, which is the order nodes were revealed in. */
export interface CablingGraph {
    focalId: number | null;
    nodes: ReadonlyMap<number, CablingNode>;
    reveals: ReadonlyMap<number, CablingReveal>;
    edges: ReadonlyMap<number, CablingEdge>;
}


/** What the toolbar controls. */
export interface CablingDisplayOptions {
    detail: boolean;
    showCableInfo: boolean;
    showPorts: boolean;
    onlyConnected: boolean;
}


export interface CablingPoint {
    x: number;
    y: number;
}


export interface CablingBounds {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
}


export type CablingAnchorSide = 'left' | 'right';


/** One port as a node card draws it. */
export interface CablingPortView {
    portId: number;
    name: string;
    side: PortSide;
    cabled: boolean;
    connectionId: number | null;
    /** The far end as text; "Restricted object" when the user may not read it. */
    farEnd: string | null;
    /** Port type, speed and status, shown in the detail density. */
    meta: string | null;
    /** Cabled to an object that is not on the canvas yet. */
    expandable: boolean;
    expandLabel: string;
}


/** One visible row of a node, at its offset from the node's top edge. */
export interface CablingRowLayout {
    key: string;
    top: number;
    height: number;
    /** Set on a standard device's row. */
    port: CablingPortView | null;
    /** Set on a patch panel's row; either face may be missing. */
    front: CablingPortView | null;
    rear: CablingPortView | null;
    paired: boolean;
}


/** The "more ports" line under a node's rows. */
export interface CablingFooterLayout {
    top: number;
    hiddenPorts: number;
    expanded: boolean;
}


/** One node card, sized and placed. */
export interface CablingNodeLayout {
    objectId: number;
    focal: boolean;
    restricted: boolean;
    patchPanel: boolean;
    title: string;
    subtitle: string;
    icon: string;
    accent: string;
    portCount: number;
    x: number;
    y: number;
    width: number;
    height: number;
    rows: CablingRowLayout[];
    footer: CablingFooterLayout | null;
    emptyMessage: string | null;
    /** Where each port's cable meets the card, measured from its top edge. */
    anchors: ReadonlyMap<number, number>;
    /** Used for a port that has no visible row of its own. */
    defaultAnchor: number;
}


/** One cable, routed between its two port anchors. */
export interface CablingEdgeLayout {
    connectionId: number;
    path: string;
    from: CablingPoint;
    to: CablingPoint;
    labelAt: CablingPoint;
    label: string;
    description: string;
    stroke: string;
}
