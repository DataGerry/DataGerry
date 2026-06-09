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
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Subject, takeUntil } from 'rxjs';

import { RenderFieldComponent } from '../../../../fields/components.fields';
import { IPAM_INTERFACE_FIELD_NAMES } from '../../models/interface-fields';
import { SubnetOption } from '../../models/subnet-option.types';
import { SubnetOptionsApiService } from '../../services/subnet-options-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Network picker for the dg-ipam-interface subnet reference. Replaces the generic ref dropdown
 * for this one field so the options come from {@code GET ipam/subnet/?type=} filtered by the
 * address family selected in the sibling dg-interface-type field. Changing the family clears the
 * previous pick (it belongs to the other family) and reloads the list.
 */
@Component({
    templateUrl: './ipam-subnet-select.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamSubnetSelectComponent extends RenderFieldComponent implements OnInit, OnDestroy {

    public readonly options = signal<SubnetOption[]>([]);
    public readonly loading = signal<boolean>(false);

    private readonly api = inject(SubnetOptionsApiService);
    private readonly destroy$ = new Subject<void>();

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnInit(): void {
        const typeControl = this.parentFormGroup.get(IPAM_INTERFACE_FIELD_NAMES.TYPE);

        this.loadOptions(this.resolveFamily(typeControl?.value));

        typeControl?.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe((family: unknown) => this.onFamilyChanged(this.resolveFamily(family)));
    }


    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                 PRIVATE FUNCTIONS                                                  */
/* ------------------------------------------------------------------------------------------------------------------ */

    private onFamilyChanged(family: string): void {
        // Drop the previous selection back to the empty placeholder, then reload so only
        // subnets of the newly selected family are offered.
        this.controller?.setValue(null);
        this.controller?.markAsPristine();
        this.controller?.markAsUntouched();
        this.loadOptions(family);
    }


    private loadOptions(family: string): void {
        this.loading.set(true);

        this.api.getSubnetOptions(family)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (rows: SubnetOption[]) => {
                    this.options.set(rows);
                    this.loading.set(false);
                },
                error: () => {
                    this.options.set([]);
                    this.loading.set(false);
                }
            });
    }


    private resolveFamily(value: unknown): string {
        return value === 'ipv6' ? 'ipv6' : 'ipv4';
    }
}
