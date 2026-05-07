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
import {
    AbstractControl,
    AsyncValidatorFn,
    UntypedFormGroup,
    ValidationErrors
} from '@angular/forms';
import { Observable, Subscription, of, timer } from 'rxjs';
import { catchError, distinctUntilChanged, map, switchMap } from 'rxjs/operators';

import { BACKEND_VALIDATION_ERROR_KEY } from '../../subnet/services/subnet-network-range-validator.service';
import {
    IPAM_INTERFACE_FIELD_NAMES,
    IPAM_INTERFACE_REQUIRED_FIELDS,
    IPAM_INTERFACE_SECTION_NAME
} from '../models/interface-fields';
import {
    InterfaceValidationRequest,
    InterfaceValidationResponse
} from '../models/interface-validation.types';
import { InterfaceIpamApiService } from './interface-ipam-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */


const DEBOUNCE_MS = 400;


export interface InterfaceIpamValidatorHandle {
    destroy(): void;
}


export interface InterfaceIpamValidatorOptions {
    /** Identifies the MDS section the modal is editing; validation only attaches for the interface section. */
    sectionName: string | null | undefined;
    /** Public id of the object being edited; null in object create mode. */
    excludeObjectId: number | null;
    /** multi_data_id of the row being edited; null when adding a new row. */
    excludeRowIndex: number | null;
}

const NOOP_HANDLE: InterfaceIpamValidatorHandle = { destroy: () => { /* no-op */ } };


@Injectable({ providedIn: 'root' })
export class InterfaceIpamValidatorService {

    private readonly api = inject(InterfaceIpamApiService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Wires the dg-ipam-interface backend validation into the row form. Only activates when
     * the modal is rendering the dg-ipam-interface MDS section, leaving every other multi-data
     * section untouched.
     */
    public attach(
        form: UntypedFormGroup,
        options: InterfaceIpamValidatorOptions
    ): InterfaceIpamValidatorHandle {
        if (!form || options.sectionName !== IPAM_INTERFACE_SECTION_NAME) {
            return NOOP_HANDLE;
        }

        // Validation only runs when the section exposes the full IPAM interface schema.
        for (const fieldName of IPAM_INTERFACE_REQUIRED_FIELDS) {
            if (!form.get(fieldName)) {
                return NOOP_HANDLE;
            }
        }

        const ipAddress = form.get(IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS);
        const subnet = form.get(IPAM_INTERFACE_FIELD_NAMES.SUBNET);

        if (!ipAddress || !subnet) {
            return NOOP_HANDLE;
        }

        const validator = this.buildValidator(subnet, options.excludeObjectId, options.excludeRowIndex);
        ipAddress.addAsyncValidators(validator);
        ipAddress.updateValueAndValidity({ emitEvent: false });

        const subscriptions: Subscription[] = [
            subnet.valueChanges.pipe(distinctUntilChanged()).subscribe(() => {
                ipAddress.updateValueAndValidity();
            })
        ];

        return {
            destroy: () => {
                subscriptions.forEach(sub => sub.unsubscribe());
                ipAddress.removeAsyncValidators(validator);
                ipAddress.updateValueAndValidity({ emitEvent: false });
            }
        };
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildValidator(
        subnet: AbstractControl,
        excludeObjectId: number | null,
        excludeRowIndex: number | null
    ): AsyncValidatorFn {
        return (control: AbstractControl): Observable<ValidationErrors | null> => {
            const ipAddress = this.normalizeIp(control.value);
            const subnetId = this.toObjectId(subnet.value);

            // Avoid hitting the backend until both halves of the candidate row are present.
            if (!ipAddress || subnetId === null) {
                return of(null);
            }

            const payload: InterfaceValidationRequest = {
                subnet_id: subnetId,
                ip_address: ipAddress,
                exclude_object_id: excludeObjectId,
                exclude_row_index: excludeRowIndex
            };

            // timer + switchMap debounces user input and ensures only the
            // latest request resolves into the validator's outcome.
            return timer(DEBOUNCE_MS).pipe(
                switchMap(() => this.api.validateInterface(payload)),
                map(response => this.toValidationErrors(response)),
                catchError(() => of(null))
            );
        };
    }


    private toValidationErrors(response: InterfaceValidationResponse): ValidationErrors | null {
        if (!response || response.valid) {
            return null;
        }

        const firstError = response.errors?.[0];
        const message = firstError?.message ?? 'Invalid interface IP address.';

        return {
            [BACKEND_VALIDATION_ERROR_KEY]: {
                message,
                code: firstError?.code,
                errors: response.errors ?? []
            }
        };
    }


    private toObjectId(value: unknown): number | null {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    }


    private normalizeIp(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }
}
