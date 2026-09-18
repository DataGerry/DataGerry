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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { ResolvedCable } from '../object/object-view/ports-overview/models/port-connection.types';

/** Guards every CI Explorer read route, and with it the graph view of an object. */
export const CI_EXPLORER_VIEW_RIGHT = 'base.framework.ciExplorer.view';

/** Guards every CI Explorer write route - the filter profiles are the only one the UI writes. */
export const CI_EXPLORER_EDIT_RIGHT = 'base.framework.ciExplorer.edit';

/* -------- basic primitives -------------------------------------------- */
export interface Field {
    name: string;
    value: string;
  }
  export interface TypeFieldDef {
    type: string;
    name: string;
    label: string;
  }
  
  /* -------- CMDB object (“linked_object”) ------------------------------- */
  export interface LinkedObject {
    public_id: number;
    type_id: number;
    version: string;
    creation_time: { $date: string };
    author_id: number;
    last_edit_time: { $date: string } | null;
    editor_id: number | null;
    active: boolean;
    fields: Field[];
    multi_data_sections: any[];
  }
  
  /* -------- CMDB type information (“type_info”) ------------------------- */
  export interface TypeInfo {
    type_id: number;
    label: string;
    icon: string; 
    fields: TypeFieldDef[];
    type_color: string;
  }
  
  /* -------- Hierarchy helpers --------------------------- */
  export type Direction = 'root' | 'parent' | 'child';

  /* -------- Which edge sources the backend should walk ------------------ */
  /** The optional edge sources a CI Explorer read may include, sent as request args. */
  export interface CiExplorerScope {
    withLocations: boolean;
    withIpamRelations: boolean;
    withPortConnections: boolean;
  }

  export const DEFAULT_CI_EXPLORER_SCOPE: CiExplorerScope = {
    withLocations: true,
    withIpamRelations: true,
    withPortConnections: true
  };
  
  /* -------- Node shape received from / sent to the UI ------------------- */
  export interface CINode {
    /* frontend helpers --------------------------------------------------- */
    level: number; //  0 = root, +1 = child, –1 = parent, …
    direction: Direction; //  "root" | "child" | "parent"
    color: string; 
    title: string; //  short label shown in the node
    relation_color?: string;
    ci_explorer_tooltip?: string;
    ci_explorer_label?: string;
  
    /* domain data -------------------------------------------------------- */
    linked_object: LinkedObject;
    type_info: TypeInfo;
  }
  
  /* -------- Edge & relation metadata ----------------------------------- */
  /** One physical hop of a collapsed port connection; `cable` is absent on a panel's internal pairing. */
  export interface CiExplorerPathHop {
    public_id: number;
    endpoints: number[];
    connection_type: string;
    cable?: ResolvedCable | null;
  }

  export interface RelationMeta {
    relation_id: number | null;
    relation_name?: string;
    relation_label?: string;
    relation_icon?: string;
    relation_color?: string;
    /** Where the edge came from when it is not a modelled relation, e.g. `ipam`, `port_connection`. */
    source?: string;
    /** A port connection has no direction, so it is drawn without an arrow head. */
    undirected?: boolean;
    /** The physical hops a port connection collapsed, focal end first. */
    path?: CiExplorerPathHop[];
  }
  
  export interface CIEdge {
    from: number;
    to: number;
    metadata: RelationMeta[]; // one edge, many relations
  }
  
  /* -------- Response shapes -------------------------------------------- */
  /* Stage-1 : with_root = true, target_type = BOTH */
  export interface GraphRespWithRoot {
    root_node: CINode;
    parent_nodes: CINode[];
    child_nodes: CINode[];
    parent_edges: CIEdge[];
    child_edges: CIEdge[];
  }
  
  /* Stage-2 : with_root = false, target_type = CHILD */
  export interface GraphRespChildren {
    child_nodes: CINode[];
    child_edges: CIEdge[];
  }
  
  /* Stage-3 : with_root = false, target_type = PARENT */
  export interface GraphRespParents {
    parent_nodes: CINode[];
    parent_edges: CIEdge[];
  }
  