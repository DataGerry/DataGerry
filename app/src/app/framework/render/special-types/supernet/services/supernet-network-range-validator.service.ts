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

import { CmdbType } from '../../../../models/cmdb-type';
import { SpecialType } from '../../../../models/special-type';
import { SUPERNET_FIELD_NAMES } from '../models/supernet-fields';
import { SupernetValidationRequest, SupernetValidationResponse } from '../models/supernet-validation.types';
import { SupernetIpamApiService } from './supernet-ipam-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */


export const BACKEND_VALIDATION_ERROR_KEY = 'backendValidation';

const DEBOUNCE_MS = 400;


export interface SupernetNetworkRangeValidatorHandle {
    destroy(): void;
}

const NOOP_HANDLE: SupernetNetworkRangeValidatorHandle = { destroy: () => { /* no-op */ } };


@Injectable({ providedIn: 'root' })
export class SupernetNetworkRangeValidatorService {

    private readonly api = inject(SupernetIpamApiService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Wires the network-range backend validation into a supernet render form.
     * The range is validated against the selected supernet type so the backend
     * can confirm the CIDR belongs to the chosen address family.
     */
    public attach(
        form: UntypedFormGroup,
        typeInstance: CmdbType | undefined
    ): SupernetNetworkRangeValidatorHandle {
        if (!form || typeInstance?.special_type !== SpecialType.SUPERNET) {
            return NOOP_HANDLE;
        }

        const networkRange = form.get(SUPERNET_FIELD_NAMES.NETWORK_RANGE);
        const supernetType = form.get(SUPERNET_FIELD_NAMES.SUPERNET_TYPE);

        if (!networkRange || !supernetType) {
            return NOOP_HANDLE;
        }

        const validator = this.buildValidator(supernetType);
        const previousValidator = networkRange.asyncValidator;
        networkRange.addAsyncValidators(validator);
        networkRange.updateValueAndValidity({ emitEvent: false });

        const subscriptions: Subscription[] = [
            supernetType.valueChanges.pipe(distinctUntilChanged()).subscribe(() => {
                networkRange.updateValueAndValidity();
            })
        ];

        return {
            destroy: () => {
                subscriptions.forEach(sub => sub.unsubscribe());
                networkRange.removeAsyncValidators(validator);
                if (previousValidator) {
                    networkRange.setAsyncValidators(previousValidator);
                }
                networkRange.updateValueAndValidity({ emitEvent: false });
            }
        };
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildValidator(supernetType: AbstractControl): AsyncValidatorFn {
        return (control: AbstractControl): Observable<ValidationErrors | null> => {
            const networkRange = this.normalizeValue(control.value);
            const type = this.normalizeValue(supernetType.value);

            // Only reach out to the backend once both a range and a type are
            // present; the regex pattern validator already gates malformed CIDRs.
            if (!networkRange || !type) {
                return of(null);
            }

            const payload: SupernetValidationRequest = {
                network_range: networkRange,
                supernet_type: type
            };

            // timer + switchMap debounces user input and ensures only the
            // latest request resolves into the validator's outcome.
            return timer(DEBOUNCE_MS).pipe(
                switchMap(() => this.api.validateSupernet(payload)),
                map(response => this.toValidationErrors(response)),
                catchError(() => of(null))
            );
        };
    }


    private toValidationErrors(response: SupernetValidationResponse): ValidationErrors | null {
        if (!response || response.valid) {
            return null;
        }

        const firstError = response.errors?.[0];
        const message = firstError?.message ?? 'Invalid supernet network range.';

        return {
            [BACKEND_VALIDATION_ERROR_KEY]: {
                message,
                code: firstError?.code,
                errors: response.errors ?? []
            }
        };
    }


    private normalizeValue(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }
}
