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
import { Injectable } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { TypeService } from '../../services/type.service';
import { CmdbType, CmdbTypeSection } from '../../models/cmdb-type';
import { LocationFieldUsageResponse } from '../../models/location-field-usage';
import {
    LocationFieldInUseModalComponent,
    LocationFieldDeletionScope
} from '../builder/modals/location-field-in-use-modal/location-field-in-use-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Owns the policy that prevents removing a location field (or its enclosing section)
 * while objects of the type still reference it.
 *
 * The usage information is fetched ONCE on edit-page load (via prime) so that the
 * delete action itself stays synchronous and the user never waits for the network.
 * The check is intentionally not refreshed when a location field is added in the
 * editor — only the originally persisted location field is guarded.
 */
@Injectable({ providedIn: 'root' })
export class LocationFieldDeletionService {

    private usage: LocationFieldUsageResponse | null = null;

    constructor(private typeService: TypeService, private modalService: NgbModal) {}


    /**
     * Called by the type-edit page right after the type is loaded.
     * Fetches usage information only when the loaded type already contains a
     * location field; otherwise no request is issued.
     */
    public prime(typeInstance: CmdbType): void {
        this.usage = null;

        if (!this.typeContainsLocationField(typeInstance)) {
            return;
        }

        const publicID = typeInstance?.public_id;
        if (publicID == null) {
            return;
        }

        this.typeService.getLocationFieldUsage(publicID).subscribe({
            next: (response) => { this.usage = response ?? null; }
        });
    }


    public clear(): void {
        this.usage = null;
    }


    public isLocationField(field: any): boolean {
        return field?.type === 'location';
    }


    public sectionContainsLocationField(section: CmdbTypeSection, typeInstance: CmdbType): boolean {
        if (!section?.fields?.length) {
            return false;
        }

        return section.fields.some(field => {
            const fieldName = typeof field === 'string' ? field : field?.name;
            const resolved = typeInstance?.fields?.find(f => f?.name === fieldName);
            return this.isLocationField(resolved);
        });
    }


    /**
     * Returns true when deletion may proceed. When the location field is in use,
     * shows the in-use modal as a side effect and returns false.
     */
    public canDelete(scope: LocationFieldDeletionScope): boolean {
        if (!this.usage?.in_use) {
            return true;
        }
        this.openInUseModal(scope, this.usage);
        return false;
    }


    private typeContainsLocationField(typeInstance: CmdbType): boolean {
        return (typeInstance?.fields ?? []).some(field => this.isLocationField(field));
    }


    private openInUseModal(scope: LocationFieldDeletionScope, usage: LocationFieldUsageResponse): void {
        const modalRef = this.modalService.open(LocationFieldInUseModalComponent, {
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        const instance = modalRef.componentInstance as LocationFieldInUseModalComponent;
        instance.scope = scope;
        instance.objectPublicIds = usage?.object_public_ids ?? [];
    }
}
