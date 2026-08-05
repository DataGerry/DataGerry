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
import { CIEdge } from 'src/app/framework/models/ci-explorer.model';
import { UidBasedConnection } from '../interfaces/graph.interfaces';



@Injectable({
    providedIn: 'root'
})
export class ConnectionTrackerService {

    // Main storage: connections by UID pair (fromUid -> toUid)
    private connectionsByUidPair = new Map<string, UidBasedConnection[]>();

    // Secondary storage: connections by UID for efficient cleanup
    private connectionsByFromUid = new Map<string, UidBasedConnection[]>();
    private connectionsByToUid = new Map<string, UidBasedConnection[]>();

    // Counter to ensure unique identification of each edge instance
    private edgeInstanceCounter = 0;

    constructor() {
    }

    /**
     * Store connections from initial graph load
     */
    storeInitialConnections(
        edges: CIEdge[],
        nodeInstanceMap: Map<string, any>
    ): void {

        this.clear();

        edges.forEach(edge => {
            this.processAndStoreEdgeByUid(edge, nodeInstanceMap, 'initial');
        });

    }

    /**
     * Add connections from node expansion
     */
    addConnectionsFromExpansion(
        edges: CIEdge[],
        nodeInstanceMap: Map<string, any>
    ): void {

        edges.forEach(edge => {
            this.processAndStoreEdgeByUid(edge, nodeInstanceMap, 'expansion');
        });

    }

    /**
     * Remove connections when nodes are collapsed
     */
    removeConnectionsForCollapsedNodes(collapsedUids: string[]): void {

        const removedUidSet = new Set(collapsedUids);
        let removedCount = 0;

        // Remove from main UID-based storage
        this.connectionsByUidPair.forEach((connections, uidPairKey) => {
            const originalLength = connections.length;
            const filtered = connections.filter(conn =>
                !removedUidSet.has(conn.fromUid) && !removedUidSet.has(conn.toUid)
            );

            if (filtered.length !== originalLength) {
                removedCount += (originalLength - filtered.length);
                if (filtered.length === 0) {
                    this.connectionsByUidPair.delete(uidPairKey);
                } else {
                    this.connectionsByUidPair.set(uidPairKey, filtered);
                }
            }
        });

        // Clean up secondary storage
        collapsedUids.forEach(uid => {
            this.connectionsByFromUid.delete(uid);
            this.connectionsByToUid.delete(uid);
        });

    }

    /**
     * Get connections between two specific UIDs
     */
    getConnectionsBetweenUids(fromUid: string, toUid: string): UidBasedConnection[] {
        const uidPairKey = this.createUidPairKey(fromUid, toUid);
        const connections = this.connectionsByUidPair.get(uidPairKey) || [];

        return connections;
    }

    /**
     * Get all connections for a specific UID (as source or target)
     */
    getAllConnectionsForUid(uid: string): UidBasedConnection[] {
        const fromConnections = this.connectionsByFromUid.get(uid) || [];
        const toConnections = this.connectionsByToUid.get(uid) || [];

        // Combine and deduplicate by instanceId
        const allConnections = [...fromConnections, ...toConnections];
        const uniqueConnections = allConnections.filter((conn, index, self) =>
            index === self.findIndex(c => c.instanceId === conn.instanceId)
        );

        return uniqueConnections;
    }

    /**
     *  Process and store a single edge using UIDs - NO DUPLICATE FILTERING
     */
    private processAndStoreEdgeByUid(
        edge: CIEdge,
        nodeInstanceMap: Map<string, any>,
        source: 'initial' | 'expansion'
    ): void {
        const metadata = this.extractMetadata(edge);

        // Increment counter for each edge instance - NO DUPLICATE CHECKING
        this.edgeInstanceCounter++;

        // Find all UID combinations for this edge
        const fromUids = this.findUidsForNodeId(edge.from, nodeInstanceMap);
        const toUids = this.findUidsForNodeId(edge.to, nodeInstanceMap);

        if (fromUids.length === 0 || toUids.length === 0) {
            return;
        }


        // Create connections for all valid UID combinations
        fromUids.forEach(fromUid => {
            toUids.forEach(toUid => {
                const fromNode = nodeInstanceMap.get(fromUid);
                const toNode = nodeInstanceMap.get(toUid);

                if (!fromNode || !toNode) {
                    return;
                }

                // Skip connections between nodes at the same level
                if (fromNode.level === toNode.level) {
                    return;
                }

                // Only allow hierarchical connections (adjacent levels)
                if (Math.abs(fromNode.level - toNode.level) !== 1) {
                    return;
                }

                const connection: UidBasedConnection = {
                    fromNodeId: edge.from,
                    toNodeId: edge.to,
                    fromUid,
                    toUid,
                    metadata: {
                        relation_id: metadata.relation_id,
                        relation_name: metadata.relation_name,
                        relation_label: metadata.relation_label,
                        relation_color: metadata.relation_color,
                        relation_icon: metadata.relation_icon
                    },
                    source,
                    instanceId: this.edgeInstanceCounter
                };

                this.storeConnectionByUid(connection);
            });
        });
    }

    /**
     * Store a connection in all UID-based storage maps
     */
    private storeConnectionByUid(connection: UidBasedConnection): void {
        // Store by UID pair
        const uidPairKey = this.createUidPairKey(connection.fromUid, connection.toUid);
        if (!this.connectionsByUidPair.has(uidPairKey)) {
            this.connectionsByUidPair.set(uidPairKey, []);
        }
        this.connectionsByUidPair.get(uidPairKey)!.push(connection);

        // Store by fromUid
        if (!this.connectionsByFromUid.has(connection.fromUid)) {
            this.connectionsByFromUid.set(connection.fromUid, []);
        }
        this.connectionsByFromUid.get(connection.fromUid)!.push(connection);

        // Store by toUid
        if (!this.connectionsByToUid.has(connection.toUid)) {
            this.connectionsByToUid.set(connection.toUid, []);
        }
        this.connectionsByToUid.get(connection.toUid)!.push(connection);
    }


    /**
     * Helper methods
     */
    private extractMetadata(edge: CIEdge): any {
        if (Array.isArray(edge.metadata)) {
            return edge.metadata[0] || {};
        }
        return edge.metadata || {};
    }

    /**
     * Create a unique key for a UID pair
     */
    private createUidPairKey(fromUid: string, toUid: string): string {
        return `${fromUid}->${toUid}`;
    }


    /**
     * Find all UIDs for a given node ID in the nodeInstanceMap
     */
    private findUidsForNodeId(nodeId: number, nodeInstanceMap: Map<string, any>): string[] {
        const uids: string[] = [];
        nodeInstanceMap.forEach((node, uid) => {
            if (node.id === nodeId) {
                uids.push(uid);
            }
        });
        return uids;
    }

    /**
     * Utility methods
     */
    clear(): void {
        this.connectionsByUidPair.clear();
        this.connectionsByFromUid.clear();
        this.connectionsByToUid.clear();
        this.edgeInstanceCounter = 0; // Reset counter
    }

    /**
     * Get overall statistics of the connection tracker
     */
    getStats(): any {
        const totalConnections = Array.from(this.connectionsByUidPair.values())
            .reduce((sum, connections) => sum + connections.length, 0);

        return {
            uniqueUidPairs: this.connectionsByUidPair.size,
            totalConnections,
            totalEdgeInstances: this.edgeInstanceCounter
        };
    }

    /**
     * Debug method to get detailed information about connections
     */
    getDebugInfo(): any {
        const pairDetails: any = {};
        this.connectionsByUidPair.forEach((connections, key) => {
            pairDetails[key] = {
                count: connections.length,
                sources: connections.map(c => c.source),
                relations: connections.map(c => c.metadata.relation_name),
                nodeIds: connections.map(c => `${c.fromNodeId}->${c.toNodeId}`),
                instanceIds: connections.map(c => c.instanceId)
            };
        });

        return {
            stats: this.getStats(),
            pairDetails
        };
    }

    /**
     * Debug method to find connections by node IDs (useful for testing)
     */
    getConnectionsByNodeIds(fromNodeId: number, toNodeId: number): UidBasedConnection[] {
        const allConnections: UidBasedConnection[] = [];

        this.connectionsByUidPair.forEach(connections => {
            connections.forEach(conn => {
                if (conn.fromNodeId === fromNodeId && conn.toNodeId === toNodeId) {
                    allConnections.push(conn);
                }
            });
        });

        return allConnections;
    }

    /**
     * Get statistics for a specific node pair
     */
    getNodePairStats(fromNodeId: number, toNodeId: number): any {
        const connections = this.getConnectionsByNodeIds(fromNodeId, toNodeId);
        const uidPairs = new Set<string>();

        connections.forEach(conn => {
            uidPairs.add(`${conn.fromUid}->${conn.toUid}`);
        });

        return {
            totalConnections: connections.length,
            uniqueUidPairs: uidPairs.size,
            instanceIds: connections.map(c => c.instanceId),
            relations: connections.map(c => c.metadata.relation_name)
        };
    }
}