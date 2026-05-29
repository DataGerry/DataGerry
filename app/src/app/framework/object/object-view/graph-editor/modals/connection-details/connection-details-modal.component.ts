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
import { Component, OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

export interface ConnectionDetailsData {
  from: number;
  to: number;
  fromLevel: number;
  toLevel: number;
  fromUid: string;
  toUid: string;
  metadata: {
    relation_id: number | null;
    relation_name: string;
    relation_label: string;
    relation_color: string;
    relation_icon?: string;
    source?: string;
  } | null;
}

export interface NodeDetailsData {
  id: number;
  label: string;
  type: string;
  color: string;
  level: number;
}

@Component({
    selector: 'app-connection-details-modal',
    templateUrl: './connection-details-modal.component.html',
    styleUrls: ['./connection-details-modal.component.scss'],
    standalone: false
})
export class ConnectionDetailsModalComponent implements OnInit {
  sourceNode!: NodeDetailsData;
  targetNode!: NodeDetailsData;
  connections: ConnectionDetailsData[] = [];
  direction: 'incoming' | 'outgoing' | 'bidirectional' = 'outgoing';

  constructor(public activeModal: NgbActiveModal) {}

  ngOnInit(): void {    
    if (this.connections && this.connections.length > 0) {
      this.connections.sort((a, b) => 
        (a.metadata?.relation_name || '').localeCompare(b.metadata?.relation_name || '')
      );
    }
  }

  getTextColor(backgroundColor: string): string {
    if (!backgroundColor) return '#000000';
    
    const hex = backgroundColor.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const brightness = ((r * 299) + (g * 587) + (b * 114)) / 1000;
    
    return brightness > 155 ? '#000000' : '#ffffff';
  }

  getDirectionIcon(): string {
    switch (this.direction) {
      case 'incoming': return 'arrow_back';
      case 'outgoing': return 'arrow_forward';
      case 'bidirectional': return 'swap_horiz';
      default: return 'arrow_forward';
    }
  }

  getDirectionLabel(): string {
    switch (this.direction) {
    //   case 'incoming': return 'Incoming Connections';
    //   case 'outgoing': return 'Outgoing Connections';
    //   case 'bidirectional': return 'Bidirectional Connections';
      default: return 'Connections';
    }
  }

  close(): void {
    this.activeModal.dismiss();
  }

  trackByConnectionId(index: number, connection: ConnectionDetailsData): number {
    return connection.metadata?.relation_id || index;
  }

  hasValidNodes(): boolean {
    return !!(this.sourceNode && this.targetNode);
  }

  hasConnections(): boolean {
    return !!(this.connections && this.connections.length > 0);
  }
}