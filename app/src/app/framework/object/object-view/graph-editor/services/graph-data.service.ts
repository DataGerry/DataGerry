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
import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import {
  CINode,
  CIEdge,
  GraphRespWithRoot,
  GraphRespChildren,
  GraphRespParents
} from 'src/app/framework/models/ci-explorer.model';
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { GraphNode, Connection } from '../interfaces/graph.interfaces';

@Injectable()
export class GraphDataService {
  private destroy$ = new Subject<void>();
  private nodeInstanceMap = new Map<string, GraphNode>();
  private edgeKeySet = new Set<string>();
  private nodesMap = new Map<number, CINode>();
  private edgesMap = new Map<string, CIEdge>();
  private nodesByLevelMap = new Map<string, CINode>();
  private expandedNodes = new Set<number>();
  private nodeCounter = 0;
  private skipBackendEdgesDuringExpansion = false;

  private edgeIndex = new Map<string, CIEdge[]>();
  private processedEdgeIds = new Set<string>();

  constructor(private ci: CiExplorerService) { }

  /*
  * Clear all data structures used for graph management.
  */
  clearAllData(): void {
    this.nodeInstanceMap?.clear();
    this.edgeKeySet?.clear();
    this.nodesMap?.clear();
    this.edgesMap?.clear();
    this.nodesByLevelMap?.clear();
    this.expandedNodes?.clear();
    this.edgeIndex.clear();          // <<< FIX
    this.processedEdgeIds.clear();
    this.nodeCounter = 0;
  }


  indexEdge(edge: CIEdge): void {
    const key = this.edgeKey(edge.from, edge.to);
    if (!this.edgeIndex.has(key)) {
      this.edgeIndex.set(key, []);
    }

    // Simply add the edge - no duplicate checking
    this.edgeIndex.get(key)!.push(edge);

  }

  private edgeKey(from: number, to: number): string {
    return `${from}-${to}`;
  }

  private extractEdgeMetadata(edge: CIEdge): any {
    if (Array.isArray(edge.metadata)) {
      return edge.metadata[0] || {};
    }
    return edge.metadata || {};
  }

  getAllEdgesBetween(from: number, to: number): CIEdge[] {
    const key = this.edgeKey(from, to);
    return this.edgeIndex.get(key) || [];
  }



  storeAndIndexEdge(edge: CIEdge): void {
    const meta = this.extractEdgeMetadata(edge);

    // FIX: Create unique edge keys for each instance
    const timestamp = Date.now();
    const randomSuffix = Math.random().toString(36).substr(2, 5);
    const edgeKey = `${edge.from}-${edge.to}-${meta.relation_id || 'unknown'}-${timestamp}-${randomSuffix}`;

    // Store in edges map with unique key
    this.edgesMap.set(edgeKey, edge);

    // Index the edge (this will now store all instances)
    this.indexEdge(edge);
  }

  rebuildEdgeIndex(): void {
    this.edgeIndex.clear();
    this.processedEdgeIds.clear();

    // Re-index all existing edges
    this.edgesMap.forEach(edge => {
      this.indexEdge(edge);
    });

  }


  getEdgeIndexDebugInfo(): any {
    const info = {
      totalKeys: this.edgeIndex.size,
      totalEdges: 0,
      keyDetails: {} as any
    };

    this.edgeIndex.forEach((edges, key) => {
      info.totalEdges += edges.length;
      info.keyDetails[key] = edges.length;
    });

    return info;
  }


  clearEdgeIndex(): void {
    this.edgeIndex.clear();
    this.processedEdgeIds.clear();
  }

  /*
  * Get the map of node instances.
  */
  getNodeInstanceMap(): Map<string, GraphNode> {
    return this.nodeInstanceMap;
  }


  getExpandedNodes(): Set<number> {
    return this.expandedNodes;
  }

  addExpandedNode(nodeId: number): void {
    this.expandedNodes?.add(nodeId);
  }

  removeExpandedNode(nodeId: number): void {
    this.expandedNodes?.delete(nodeId);
  }

  getCINode(id: number): CINode | undefined {
    return this.nodesMap?.get(id);
  }

  // Backend API calls
  loadWithRoot(
    rootNodeId: number,
    typesFilter: number[] = [],
    relationsFilter: number[] = [],
    withLocations: boolean = true,
    withIpamRelations: boolean = true
  ): Observable<GraphRespWithRoot> {
    return this.ci?.loadWithRoot(rootNodeId, typesFilter, relationsFilter, withLocations, withIpamRelations);
  }

  expandChild(
    id: number,
    typesFilter: number[] = [],
    relationsFilter: number[] = []
  ): Observable<GraphRespChildren> {
    return this.ci?.expandChild(id, typesFilter, relationsFilter);
  }

  expandParent(
    id: number,
    typesFilter: number[] = [],
    relationsFilter: number[] = []
  ): Observable<GraphRespParents> {
    return this.ci?.expandParent(id, typesFilter, relationsFilter);
  }

  // Helper methods
  getNodes(r: any, kind: 'child' | 'parent'): CINode[] {
    return r[`${kind}_nodes`] ?? r[`${kind}ren_nodes`] ?? [];
  }

  getEdges(r: any, kind: 'child' | 'parent'): CIEdge[] {
    return r[`${kind}_edges`] ?? r[`${kind}ren_edges`] ?? [];
  }

  generateTrueUniqueUid(id: number, level: number): string {
    return `node_${Date.now()}_${this.nodeCounter++}_${id}_L${level}`;
  }

  //   extractLabel(cn: CINode): string {
  //     // return (cn as any).ci_explorer_label ||
  //       return cn.title || cn.title !== null ? cn.title :
  //       'Label not Selected';
  //   }

  extractLabel(cn: CINode): string {
    if (cn.title === null) {
      return 'Label not selected';
    } else if (cn.title === '') {
      return 'Label is empty';
    } else {
      return cn.title;
    }
  }


  // Node and Edge Management
  mergeNodes(nodes: GraphNode[], cis: CINode[], nodeTypeConfigs: Map<string, { icon: string; gradient: string }>): void {
    cis.forEach(cn => {
      const id = cn?.linked_object?.public_id;
      const level = cn?.level;
      const uid = this.generateTrueUniqueUid(id, level);
      const type = cn?.type_info.label;

      if (!nodeTypeConfigs.has(type)) {
        nodeTypeConfigs?.set(type, {
          icon: cn?.type_info?.icon,
          gradient: cn?.type_info?.type_color
        });
      }

      const newNode: GraphNode = {
        uid, id, level,
        label: this.extractLabel(cn),
        type, color: cn?.type_info?.type_color,
        icon: cn?.type_info?.icon,
        x: 0, y: 0,
        expanded: false,
        isLoading: false,
        hasChildren: true,
        hasParents: true,
        fields: [...cn?.linked_object?.fields],
        ciNode: { ...cn },
        isRoot: (cn as any)?.isRoot || false,
        connectionCount: { parents: 0, children: 0 },
        status: cn?.linked_object.active ? 'active' : 'inactive',
        metadata: [...cn?.linked_object?.fields]
      };

      this.nodeInstanceMap?.set(uid, newNode);
      nodes?.push(newNode);
      this.nodesMap?.set(id, cn);

    });
  }

  // mergeEdges(connections: Connection[], nodes: GraphNode[], edges: CIEdge[]): void {
  //     if (this.skipBackendEdgesDuringExpansion) { return; }

  //     edges?.forEach(raw => {
  //         const meta = Array.isArray(raw?.metadata) ? raw?.metadata[0] : raw?.metadata;

  //         const fromCopies = nodes?.filter(n => n?.id === raw?.from);
  //         const toCopies = nodes?.filter(n => n?.id === raw?.to);

  //         fromCopies?.forEach(f => {
  //             toCopies?.forEach(t => {
  //                 if (Math.abs(f?.level - t?.level) !== 1) { return; }

  //                 const uidA = f?.uid;
  //                 const uidB = t?.uid;
  //                 const pairKey = uidA < uidB ? `${uidA}|${uidB}` : `${uidB}|${uidA}`;
  //                 if (this.edgeKeySet?.has(pairKey)) { return; }
  //                 this.edgeKeySet?.add(pairKey);

  //                 connections.push({
  //                     from: f?.id, to: t?.id,
  //                     fromLevel: f?.level, toLevel: t?.level,
  //                     fromUid: f?.uid, toUid: t?.uid,
  //                     relationLabel: meta?.relation_label,
  //                     relationColor: meta?.relation_color,
  //                     relationIcon: meta?.relation_icon,
  //                     metadata: meta,
  //                     isValid: true,
  //                     strength: 1,
  //                     dataFlow: false
  //                 });
  //             });
  //         });
  //     });
  // }


  mergeEdges(connections: Connection[], nodes: GraphNode[], edges: CIEdge[]): void {
    if (this.skipBackendEdgesDuringExpansion) { return; }

    edges.forEach(raw => {
      const meta = Array.isArray(raw.metadata) ? raw.metadata[0] : raw.metadata;

      // Find the ORIGINAL from and to nodes based on the backend edge direction
      const fromCopies = nodes.filter(n => n.id === raw.from);
      const toCopies = nodes.filter(n => n.id === raw.to);

      // Determine the expected direction based on the backend edge
      const isParentToChild = raw.from < raw.to; // Simple heuristic, adjust as needed

      fromCopies.forEach(f => {
        toCopies.forEach(t => {
          // Only connect adjacent levels
          if (Math.abs(f.level - t.level) !== 1) { return; }

          // CRITICAL: Only create connection if it matches the expected hierarchy
          let shouldConnect = false;

          if (f.level < t.level) {
            // f is parent, t is child - this is correct hierarchical flow
            shouldConnect = true;
          } else if (t.level < f.level) {
            // t is parent, f is child - this is reverse flow, skip it
            shouldConnect = false;
          }

          if (!shouldConnect) return;

          const uidA = f.uid;
          const uidB = t.uid;
          const pairKey = uidA < uidB ? `${uidA}|${uidB}` : `${uidB}|${uidA}`;
          if (this.edgeKeySet.has(pairKey)) { return; }
          this.edgeKeySet.add(pairKey);

          connections.push({
            from: f.id, to: t.id,
            fromLevel: f.level, toLevel: t.level,
            fromUid: f.uid, toUid: t.uid,
            relationLabel: meta?.relation_label,
            relationColor: meta?.relation_color,
            relationIcon: meta?.relation_icon,
            metadata: meta,
            isValid: true,
            strength: 1,
            dataFlow: false
          });

        });
      });
    });
  }

  setSkipBackendEdges(skip: boolean): void {
    this.skipBackendEdgesDuringExpansion = skip;
  }

  removeNodeInstancesByUID(nodes: GraphNode[], connections: Connection[], uidsToRemove: string[]): void {
    const doomed = new Set(uidsToRemove);

    // Remove from nodes array
    const indicesToRemove: number[] = [];
    nodes?.forEach((n, index) => {
      if (doomed?.has(n.uid)) {
        indicesToRemove.push(index);
        this.nodeInstanceMap?.delete(n?.uid);
      }
    });

    // Remove in reverse order to maintain indices
    indicesToRemove?.reverse()?.forEach(index => {
      nodes?.splice(index, 1);
    });

    // Remove from connections array
    const connectionIndicesToRemove: number[] = [];
    connections?.forEach((c, index) => {
      if (doomed?.has(c?.fromUid!) || doomed?.has(c?.toUid!)) {
        connectionIndicesToRemove.push(index);
      }
    });

    connectionIndicesToRemove?.reverse()?.forEach(index => {
      connections?.splice(index, 1);
    });

  }

  destroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }
}