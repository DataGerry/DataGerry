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
import { Directive, Input, OnChanges, OnDestroy, inject } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import {
    InterfaceIpamValidatorHandle,
    InterfaceIpamValidatorService
} from '../services/interface-ipam-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Activates the dg-ipam-interface backend validation on a row form.
 *
 * Usage:
 *   <form [cmdbInterfaceIpamValidator]="renderForm"
 *         [cmdbInterfaceIpamValidatorSection]="sectionName"
 *         [cmdbInterfaceIpamValidatorObjectId]="excludeObjectId"
 *         [cmdbInterfaceIpamValidatorRowIndex]="excludeRowIndex">...</form>
 *
 * The directive only attaches when the section name matches dg-ipam-interface, leaving
 * every other multi-data section untouched.
 */
@Directive({
    selector: '[cmdbInterfaceIpamValidator]',
    standalone: false,
})
export class InterfaceIpamValidatorDirective implements OnChanges, OnDestroy {

    @Input('cmdbInterfaceIpamValidator') public form: UntypedFormGroup | undefined;
    @Input('cmdbInterfaceIpamValidatorSection') public sectionName: string | null | undefined;
    @Input('cmdbInterfaceIpamValidatorObjectId') public excludeObjectId: number | null | undefined;
    @Input('cmdbInterfaceIpamValidatorRowIndex') public excludeRowIndex: number | null | undefined;

    private readonly validatorService = inject(InterfaceIpamValidatorService);
    private handle: InterfaceIpamValidatorHandle | null = null;
    private pendingAttach: ReturnType<typeof setTimeout> | null = null;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnChanges(): void {
        this.scheduleAttach();
    }


    public ngOnDestroy(): void {
        this.cancelPendingAttach();
        this.detach();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Defer the attach so child render-element components have registered their controls
     * on the form group before the validator looks them up.
     */
    private scheduleAttach(): void {
        this.detach();
        this.cancelPendingAttach();

        this.pendingAttach = setTimeout(() => {
            this.pendingAttach = null;

            if (!this.form) {
                return;
            }

            this.handle = this.validatorService.attach(this.form, {
                sectionName: this.sectionName ?? null,
                excludeObjectId: this.normalizeId(this.excludeObjectId),
                excludeRowIndex: this.normalizeRowIndex(this.excludeRowIndex)
            });
        }, 0);
    }


    private cancelPendingAttach(): void {
        if (this.pendingAttach !== null) {
            clearTimeout(this.pendingAttach);
            this.pendingAttach = null;
        }
    }


    private detach(): void {
        if (this.handle) {
            this.handle.destroy();
            this.handle = null;
        }
    }


    private normalizeId(value: number | null | undefined): number | null {
        if (value === null || value === undefined) {
            return null;
        }

        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    }


    private normalizeRowIndex(value: number | null | undefined): number | null {
        if (value === null || value === undefined) {
            return null;
        }

        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
    }
}
