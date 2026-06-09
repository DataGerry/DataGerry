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
import { SUBNET_FIELD_NAMES } from '../models/subnet-fields';
import { SubnetValidationRequest, SubnetValidationResponse } from '../models/subnet-validation.types';
import { SubnetIpamApiService } from './subnet-ipam-api.service';
/* ------------------------------------------------------------------------------------------------------------------ */


export const BACKEND_VALIDATION_ERROR_KEY = 'backendValidation';

const DEBOUNCE_MS = 400;


export interface SubnetNetworkRangeValidatorHandle {
    destroy(): void;
}


export interface SubnetNetworkRangeValidatorOptions {
    /** Public id of the object being edited; null in create mode. */
    excludeSubnetId: number | null;
}

const NOOP_HANDLE: SubnetNetworkRangeValidatorHandle = { destroy: () => { /* no-op */ } };


@Injectable({ providedIn: 'root' })
export class SubnetNetworkRangeValidatorService {

    private readonly api = inject(SubnetIpamApiService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Wires the network-range backend validation into the form.
     */
    public attach(
        form: UntypedFormGroup,
        typeInstance: CmdbType | undefined,
        options: SubnetNetworkRangeValidatorOptions
    ): SubnetNetworkRangeValidatorHandle {
        if (!form || typeInstance?.special_type !== SpecialType.SUBNET) {
            return NOOP_HANDLE;
        }

        const networkRange = form.get(SUBNET_FIELD_NAMES.NETWORK_RANGE);
        const supernet = form.get(SUBNET_FIELD_NAMES.SUPERNET);
        const subnetType = form.get(SUBNET_FIELD_NAMES.SUBNET_TYPE);

        if (!networkRange || !supernet) {
            return NOOP_HANDLE;
        }

        const validator = this.buildValidator(supernet, subnetType, options.excludeSubnetId);
        const previousValidator = networkRange.asyncValidator;
        networkRange.addAsyncValidators(validator);
        networkRange.updateValueAndValidity({ emitEvent: false });

        const subscriptions: Subscription[] = [
            supernet.valueChanges.pipe(distinctUntilChanged()).subscribe(() => {
                networkRange.updateValueAndValidity();
            })
        ];


        if (subnetType) {
            subscriptions.push(
                subnetType.valueChanges.pipe(distinctUntilChanged()).subscribe(() => {
                    networkRange.updateValueAndValidity();
                })
            );
        }

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

    private buildValidator(
        supernet: AbstractControl,
        subnetType: AbstractControl | null,
        excludeSubnetId: number | null
    ): AsyncValidatorFn {
        return (control: AbstractControl): Observable<ValidationErrors | null> => {
            const networkRange = this.normalizeRange(control.value);
            if (!networkRange) {
                return of(null);
            }

            // When the type field is present on the form it must be selected
            // before validating; the backend requires subnet_type and would
            // otherwise reject the range with a redundant "type is required".
            const subnetTypeValue = this.normalizeType(subnetType?.value);
            if (subnetType && !subnetTypeValue) {
                return of(null);
            }

            const payload: SubnetValidationRequest = {
                network_range: networkRange,
                parent_supernet_id: this.toObjectId(supernet.value),
                exclude_subnet_id: excludeSubnetId
            };

            if (subnetTypeValue) {
                payload.subnet_type = subnetTypeValue;
            }

            // timer + switchMap debounces user input and ensures only the
            // latest request resolves into the validator's outcome.
            return timer(DEBOUNCE_MS).pipe(
                switchMap(() => this.api.validateSubnet(payload)),
                map(response => this.toValidationErrors(response)),
                catchError(() => of(null))
            );
        };
    }


    private toValidationErrors(response: SubnetValidationResponse): ValidationErrors | null {
        if (!response || response.valid) {
            return null;
        }

        const firstError = response.errors?.[0];
        const message = firstError?.message ?? 'Invalid subnet network range.';

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


    private normalizeRange(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }


    private normalizeType(value: unknown): string | null {
        if (typeof value !== 'string') {
            return null;
        }

        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : null;
    }
}
