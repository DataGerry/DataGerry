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
import { AbstractControl, UntypedFormGroup } from '@angular/forms';
import { Observable, Subject, Subscription, of } from 'rxjs';
import { catchError, distinctUntilChanged, map, switchMap } from 'rxjs/operators';

import { ObjectService } from '../../../../services/object.service';
import { RenderResult } from '../../../../models/cmdb-render';
import { CmdbType } from '../../../../models/cmdb-type';
import { SpecialType } from '../../../../models/special-type';
import { SUBNET_FIELD_NAMES } from '../models/subnet-fields';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Handle returned by SubnetFormSyncService.attach() to release listeners
 * when the host component is destroyed or the type instance changes.
 */
export interface SubnetFormSyncHandle {
    destroy(): void;
}

type LockedBy = 'supernet' | 'parent' | null;

const NOOP_HANDLE: SubnetFormSyncHandle = { destroy: () => { /* no-op */ } };

@Injectable({ providedIn: 'root' })
export class SubnetFormSyncService {

    private readonly objectService = inject(ObjectService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Wire up subnet hierarchy synchronization on the given form.
     *
     * Behavior:
     *  - Selecting `dg-supernet-ref` locks `dg-parent-subnet-ref`.
     *  - Selecting `dg-parent-subnet-ref` auto-fills and locks `dg-supernet-ref`
     *    using the parent's own `dg-supernet-ref` reference.
     *  - Clearing the field that initiated the lock releases the other.
     *
     * Activates only when `typeInstance.special_type === SpecialType.SUBNET`
     * and both controls are present in the form.
     */
    public attach(form: UntypedFormGroup, typeInstance: CmdbType | undefined): SubnetFormSyncHandle {
        if (!form || typeInstance?.special_type !== SpecialType.SUBNET) {
            return NOOP_HANDLE;
        }

        const supernet = form.get(SUBNET_FIELD_NAMES.SUPERNET);
        const parent = form.get(SUBNET_FIELD_NAMES.PARENT_SUBNET);

        if (!supernet || !parent) {
            return NOOP_HANDLE;
        }

        const state = { lockedBy: null as LockedBy };
        const subscriptions: Subscription[] = [];

        
        // switchMap ensures only the most recent parent change wins when the user
        // switches selections faster than the API responds.
        const parentSelections$ = new Subject<unknown>();

        subscriptions.push(
            parentSelections$.pipe(
                switchMap(parentValue => this.resolveSupernetFor(parentValue))
            ).subscribe(supernetId => {
                supernet.setValue(supernetId, { emitEvent: false });
            }),

            parent.valueChanges
                .pipe(distinctUntilChanged())
                .subscribe(value => this.onParentChange(value, supernet, state, parentSelections$)),

            supernet.valueChanges
                .pipe(distinctUntilChanged())
                .subscribe(value => this.onSupernetChange(value, parent, state)),
        );

        this.applyInitialLock(supernet, parent, state, parentSelections$);

        return {
            destroy: () => {
                subscriptions.forEach(sub => sub.unsubscribe());
                parentSelections$.complete();
            }
        };
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private applyInitialLock(
        supernet: AbstractControl,
        parent: AbstractControl,
        state: { lockedBy: LockedBy },
        parentSelections$: Subject<unknown>
    ): void {
        if (this.hasValue(parent.value)) {
            this.disable(supernet);
            state.lockedBy = 'parent';
            parentSelections$.next(parent.value);
            return;
        }

        if (this.hasValue(supernet.value)) {
            this.disable(parent);
            state.lockedBy = 'supernet';
        }
    }


    private onParentChange(
        value: unknown,
        supernet: AbstractControl,
        state: { lockedBy: LockedBy },
        parentSelections$: Subject<unknown>
    ): void {
        if (this.hasValue(value)) {
            // Lock first so the field can't be edited mid-fetch, then trigger
            // the lookup. The subscriber will overwrite the supernet with the
            // latest result (including null when the parent has no supernet).
            this.disable(supernet);
            state.lockedBy = 'parent';
            parentSelections$.next(value);
            return;
        }

        if (state.lockedBy === 'parent') {
            supernet.setValue(null, { emitEvent: false });
            this.enable(supernet);
            state.lockedBy = null;
        }
    }


    private onSupernetChange(
        value: unknown,
        parent: AbstractControl,
        state: { lockedBy: LockedBy }
    ): void {
        // Ignore programmatic supernet updates triggered by a parent-subnet selection.
        if (state.lockedBy === 'parent') {
            return;
        }

        if (this.hasValue(value)) {
            this.disable(parent);
            state.lockedBy = 'supernet';
            return;
        }

        if (state.lockedBy === 'supernet') {
            this.enable(parent);
            state.lockedBy = null;
        }
    }


    /**
     * Resolves the supernet for a given parent-subnet selection. Always emits
     * exactly one value (either a numeric supernet id, or null when the parent
     * has no supernet, is invalid, or the lookup fails). Returning null is
     * intentional: it lets the caller clear stale supernet values.
     */
    private resolveSupernetFor(parentObjectId: unknown): Observable<number | null> {
        const id = this.toObjectId(parentObjectId);
        if (id === null) {
            return of(null);
        }

        return this.objectService.getObject<RenderResult>(id, false).pipe(
            map((parentObject: RenderResult) => this.extractSupernetReference(parentObject)),
            catchError(() => of(null))
        );
    }


    private extractSupernetReference(parentObject: RenderResult): number | null {
        const field = parentObject?.fields?.find(f => f?.name === SUBNET_FIELD_NAMES.SUPERNET);
        if (!field) {
            return null;
        }

        return this.toObjectId(field?.reference?.object_id) ?? this.toObjectId(field?.value);
    }


    private toObjectId(value: unknown): number | null {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    }


    private hasValue(value: unknown): boolean {
        if (value === null || value === undefined || value === '') {
            return false;
        }

        if (typeof value === 'number') {
            return value > 0;
        }

        return true;
    }


    private disable(control: AbstractControl): void {
        if (!control.disabled) {
            control.disable({ emitEvent: false });
        }
    }


    private enable(control: AbstractControl): void {
        if (control.disabled) {
            control.enable({ emitEvent: false });
        }
    }
}
