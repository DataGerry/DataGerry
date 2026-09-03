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
import { CmdbType } from '../../models/cmdb-type';
import { UsesPortsUsageResponse } from '../../models/uses-ports-usage';
import { BuilderSection } from 'src/app/framework/builder/schema/builder-section.model';
import { isPortsTemplateName } from 'src/app/framework/section_templates/models/virtual-section-template.model';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Prevents removing the ports section while ports of the type still exist, which the update route
 * refuses anyway.
 *
 * The usage information is fetched ONCE on edit-page load (via prime) so that the delete action
 * itself stays synchronous, and only for a type that already uses ports.
 */
@Injectable({ providedIn: 'root' })
export class PortsUsageService {

    private usage: UsesPortsUsageResponse | null = null;

    constructor(private typeService: TypeService, private modalService: NgbModal) {}


    public prime(typeInstance: CmdbType): void {
        this.usage = null;

        const publicID = typeInstance?.public_id;

        if (!typeInstance?.uses_ports || publicID == null) {
            return;
        }

        this.typeService.getUsesPortsUsage(publicID).subscribe({
            next: (response) => { this.usage = response ?? null; }
        });
    }


    public clear(): void {
        this.usage = null;
    }


    /** False only for the ports section while ports of the type exist. */
    public canRemoveSection(section: BuilderSection): boolean {
        if (!isPortsTemplateName(section?.name) || !this.usage?.in_use) {
            return true;
        }

        this.openInUseModal(this.usage);
        return false;
    }


    private openInUseModal(usage: UsesPortsUsageResponse): void {
        const modalRef = this.modalService.open(CoreWarningModalComponent, {
            centered: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.title = 'Ports are still in use';
        modalRef.componentInstance.message = this.buildMessage(usage);
    }


    private buildMessage(usage: UsesPortsUsageResponse): string {
        const ports = `${usage.port_count} ${usage.port_count === 1 ? 'port' : 'ports'}`;
        const objects = `${usage.object_count} ${usage.object_count === 1 ? 'object' : 'objects'}`;

        return `This type still has ${ports} on ${objects}. Delete them before removing the Ports section.`;
    }
}
