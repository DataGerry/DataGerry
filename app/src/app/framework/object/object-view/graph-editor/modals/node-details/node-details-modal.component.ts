/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import {
    Component,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    AfterViewInit,
    Input,
} from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { GraphNode } from '../../interfaces/graph.interfaces';
import { LAYOUT_CONFIG } from '../../constants/graph.constants';

function normalise(v: unknown): unknown {
    return v === null || v === undefined || v === '' ? 'N/A' : v;
}

@Component({
    selector: 'app-node-details-modal',
    templateUrl: './node-details-modal.component.html',
    styleUrls: ['./node-details-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.Default,
    standalone: false
})
export class NodeDetailsModalComponent implements AfterViewInit {
    @Input() nodeTypeConfigs:
        | Map<string, { icon: string; gradient: string }>
        | null = null;


    readonly LAYOUT_CONFIG = LAYOUT_CONFIG;

    /** always-rendered array; we fill it in loadNode() */
    customFields: Array<{ key: string; value: any }> = [];
    private viewInit = false;
    private _node: GraphNode | null = null;

    constructor(
        public activeModal: NgbActiveModal,
        private cdr: ChangeDetectorRef
    ) { }

    ngAfterViewInit(): void {
        this.viewInit = true;
    }


    /**
     *  Load a GraphNode into the modal.
     * @param n the GraphNode to load
     */
    loadNode(n: GraphNode | null): void {
        this._node = n;

        // Always start fresh - clear any existing fields
        this.customFields = [];


        // Create a map of field names to labels from type_info
        const fieldLabelMap = new Map<string, string>();
        if (n?.ciNode?.type_info?.fields) {
            n.ciNode.type_info.fields.forEach(typeField => {
                fieldLabelMap.set(typeField.name, typeField.label);
            });
        }


        const built: Array<{ key: string; value: any }> = [];

        // ONLY process fields from ciNode.linked_object.fields
        if (n?.ciNode?.linked_object?.fields) {
            const processedLabels = new Map<string, any>();

            n.ciNode.linked_object.fields.forEach((field) => {

                const fieldLabel = fieldLabelMap.get(field.name);
                if (!fieldLabel) {
                    return;
                }

                if (processedLabels.has(fieldLabel)) {
                    return;
                }

                processedLabels.set(fieldLabel, field.value);

                built.push({
                    key: fieldLabel,
                    value: normalise(field.value)
                });

            });
        }

        // Set new reference to force change detection
        this.customFields = [...built];

        if (this.viewInit) {
            this.cdr.detectChanges();
        }
    }


    /**
     * Returns the icon for a node type.
     * @param type The type of the node.
     * @returns The icon string or an empty string if no icon is found.
     */
    getNodeTypeIcon(type?: string | null): string {
        return (
            this.nodeTypeConfigs?.get(type!)?.icon
        );
    }


    get node(): GraphNode | null {
        return this._node;
    }


    trackByKey(_: number, f: { key: string }): string {
        return f.key;
    }
}
