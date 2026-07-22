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

import { CmdbType } from '../../../../models/cmdb-type';
import {
    SupernetNetworkRangeValidatorHandle,
    SupernetNetworkRangeValidatorService
} from '../services/supernet-network-range-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Activates the supernet network-range backend validation on a render form.
 *
 * Usage:
 *   <div [cmdbSupernetNetworkRangeValidator]="typeInstance"
 *        [cmdbSupernetNetworkRangeValidatorForm]="renderForm">...</div>
 */
@Directive({
    selector: '[cmdbSupernetNetworkRangeValidator]',
    standalone: false,
})
export class SupernetNetworkRangeValidatorDirective implements OnChanges, OnDestroy {

    @Input('cmdbSupernetNetworkRangeValidator') public typeInstance: CmdbType | undefined;
    @Input('cmdbSupernetNetworkRangeValidatorForm') public form: UntypedFormGroup | undefined;

    private readonly validatorService = inject(SupernetNetworkRangeValidatorService);
    private handle: SupernetNetworkRangeValidatorHandle | null = null;
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
     * Defer the attach so that child render-element components have registered
     * their controls on the form group before the validator looks them up.
     */
    private scheduleAttach(): void {
        this.detach();
        this.cancelPendingAttach();

        this.pendingAttach = setTimeout(() => {
            this.pendingAttach = null;

            if (this.form && this.typeInstance) {
                this.handle = this.validatorService.attach(this.form, this.typeInstance);
            }
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
}
