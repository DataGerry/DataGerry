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
import { Injectable, inject } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { BehaviorSubject, Observable, Subject, Subscription, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { MultiDataSectionSet } from '../../../../models/cmdb-object';
import { CmdbMultiDataSection } from '../../../../models/cmdb-type';
import {
    MdsRowValidator,
    MdsRowValidatorHandle,
    MdsRowValidatorOptions,
    MdsValidationState,
    VALID_MDS_STATE
} from '../../../sections/multi-data-section/mds-row-validator';
import {
    IPAM_INTERFACE_FIELD_NAMES,
    IPAM_INTERFACE_REQUIRED_FIELDS,
    IPAM_INTERFACE_SECTION_NAME
} from '../models/interface-fields';
import {
    InterfaceRowPayload,
    InterfaceValidationRequest,
    InterfaceValidationResponse
} from '../models/interface-validation.types';
import { InterfaceIpamApiService } from './interface-ipam-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */


/**
 * Implementation of {@link MdsRowValidator} for the dg-ipam-interface MDS section. Plugs
 * into the MDS component via the {@code MDS_ROW_VALIDATORS} multi-provider, so the generic
 * MDS component carries no IPAM-specific knowledge.
 */
@Injectable({ providedIn: 'root' })
export class InterfaceMdsValidatorService implements MdsRowValidator {

    private readonly api = inject(InterfaceIpamApiService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public attach(
        form: UntypedFormGroup,
        section: CmdbMultiDataSection,
        options: MdsRowValidatorOptions
    ): MdsRowValidatorHandle | null {
        if (section?.name !== IPAM_INTERFACE_SECTION_NAME) {
            return null;
        }

        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            if (!form.get(fieldName)) {
                return null;
            }
        }

        return new InterfaceMdsValidatorHandle(this.api, options.excludeObjectId);
    }
}


/**
 * Holds per-section validation state and serializes API calls so a fresh row commit
 * cancels any in-flight validation for stale row state.
 */
class InterfaceMdsValidatorHandle implements MdsRowValidatorHandle {

    private readonly stateSubject = new BehaviorSubject<MdsValidationState>(VALID_MDS_STATE);
    private readonly trigger = new Subject<ReadonlyArray<MultiDataSectionSet>>();
    private readonly subscription: Subscription;

    public readonly state$ = this.stateSubject.asObservable();

    constructor(
        private readonly api: InterfaceIpamApiService,
        private readonly excludeObjectId: number | null
    ) {
        this.subscription = this.trigger.pipe(
            switchMap(rows => this.runValidation(rows))
        ).subscribe(state => this.stateSubject.next(state));
    }


    public validate(rows: ReadonlyArray<MultiDataSectionSet>): void {
        this.trigger.next(rows);
    }


    public destroy(): void {
        this.subscription.unsubscribe();
        this.trigger.complete();
        this.stateSubject.complete();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private runValidation(
        rows: ReadonlyArray<MultiDataSectionSet>
    ): Observable<MdsValidationState> {
        if (!rows || rows.length === 0) {
            return of(VALID_MDS_STATE);
        }

        const payload: InterfaceValidationRequest = {
            rows: rows.map(set => this.toRowPayload(set)),
            exclude_object_id: this.excludeObjectId
        };

        return this.api.validateInterface(payload).pipe(
            map(response => this.toState(response)),
            catchError(() => of(VALID_MDS_STATE))
        );
    }


    private toRowPayload(set: MultiDataSectionSet): InterfaceRowPayload {
        let subnet: number | null = null;
        let ip: string | null = null;

        for (const entry of set.data ?? []) {
            if (entry.name === IPAM_INTERFACE_FIELD_NAMES.SUBNET) {
                subnet = this.toObjectId(entry.value);
            } else if (entry.name === IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS) {
                ip = this.toTrimmedString(entry.value);
            }
        }

        return {
            row_index: set.multi_data_id,
            subnet_id: subnet,
            ip_address: ip
        };
    }


    private toState(response: InterfaceValidationResponse | null): MdsValidationState {
        if (!response || response.valid) {
            return VALID_MDS_STATE;
        }

        const invalid = new Set<number>();

        for (const err of response.errors ?? []) {
            const details = (err.details ?? {}) as Record<string, unknown>;
            for (const key of ['row_index', 'first_row_index', 'duplicate_row_index']) {
                const value = details[key];
                if (typeof value === 'number') {
                    invalid.add(value);
                }
            }
        }

        return {
            valid: false,
            invalidRowIndices: Array.from(invalid)
        };
    }


    private toObjectId(value: unknown): number | null {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    }


    private toTrimmedString(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }
}
