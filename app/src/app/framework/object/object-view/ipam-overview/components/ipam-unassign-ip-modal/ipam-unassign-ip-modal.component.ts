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
import { ChangeDetectionStrategy, Component, inject, Input } from '@angular/core';
import { FormControl } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { IpamUnassignMode } from '../../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

interface UnassignModeOption {
    value: IpamUnassignMode;
    label: string;
    description: string;
}

@Component({
    selector: 'cmdb-ipam-unassign-ip-modal',
    templateUrl: './ipam-unassign-ip-modal.component.html',
    styleUrls: ['./ipam-unassign-ip-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamUnassignIpModalComponent {

    @Input() public count = 1;
    @Input() public ipLabel: string | null = null;

    public readonly activeModal = inject(NgbActiveModal);
    public readonly modeControl = new FormControl<IpamUnassignMode>('reference', { nonNullable: true });

    public readonly options: UnassignModeOption[] = [
        {
            value: 'reference',
            label: 'Subnet',
            description: 'Frees the IP address but keeps the interface entry on the object.'
        },
        {
            value: 'row',
            label: 'Interface entry',
            description: 'Removes the whole interface entry from the object.'
        }
    ];

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get headerText(): string {
        if (this.count === 1) {
            return this.ipLabel ? `Unassign IP — ${this.ipLabel}` : 'Unassign IP';
        }
        return `Unassign ${this.count} IP addresses`;
    }

    public confirm(): void {
        this.activeModal.close(this.modeControl.value);
    }
}
