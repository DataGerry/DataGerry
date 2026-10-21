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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectorRef, Component, Input, OnDestroy, OnInit, inject } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { Observable, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, tap } from 'rxjs/operators';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { CmdbMode } from '../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Verdict shape returned by the optional {@link PreviewModalComponent.externalValidator}.
 * Modeled after MdsCandidateValidationState but kept narrow here so the modal stays
 */
export interface PreviewModalValidationResult {
    valid: boolean;
    errors: ReadonlyArray<string>;
}


@Component({
    selector: 'cmdb-preview-modal',
    templateUrl: './preview-modal.component.html',
    styleUrls: ['./preview-modal.component.scss'],
    standalone: false
})
export class PreviewModalComponent implements OnInit, OnDestroy {
    @Input() sections: any[];
    @Input() saveValues: boolean = false;
    @Input() editValues: boolean = false;
    @Input() activateViewMode: boolean = false;

    /**
     *  async gate the caller can supply to validate the form before the user is
     * allowed to commit. The modal calls it on every (debounced) form change; while a call
     * is in flight or while the latest verdict is invalid, the Add/OK button stays disabled.
     */
    @Input() externalValidator?: (formValue: Record<string, unknown>) => Observable<PreviewModalValidationResult>;

    /** Field name to anchor inline error messages under. */
    @Input() errorAnchorField?: string | null;

    public renderForm: UntypedFormGroup;
    public modes = CmdbMode;

    public externalValid = true;
    public externalPending = false;
    public externalErrors: ReadonlyArray<string> = [];

    private readonly cdr = inject(ChangeDetectorRef);
    private valueChangesSub?: Subscription;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(public activeModal: NgbActiveModal) {
        this.renderForm = new UntypedFormGroup({});
    }


    ngOnInit(): void {
        if (!this.externalValidator) {
            return;
        }

        this.externalValid = false;

        this.valueChangesSub = this.renderForm.valueChanges.pipe(
            debounceTime(300),
            distinctUntilChanged((a, b) => this.shallowEqual(a, b)),
            tap(() => {
                this.externalPending = true;
                this.cdr.markForCheck();
            }),
            switchMap(value => this.externalValidator!(value ?? {}))
        ).subscribe({
            next: result => this.applyValidationResult(result),
            error: () => this.applyValidationResult({ valid: true, errors: [] })
        });
    }


    ngOnDestroy(): void {
        this.valueChangesSub?.unsubscribe();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    getViewMode() {
        return this.activateViewMode ? CmdbMode.View : CmdbMode.Create;
    }


    /** Header title; the modal doubles as the add/edit form for multi data sections. */
    get modalTitle(): string {
        if (this.saveValues) {
            return 'Add new entry';
        }

        if (this.editValues) {
            return 'Edit entry';
        }

        return 'Preview';
    }


    /** Header icon matching {@link modalTitle}. */
    get modalIcon(): string {
        if (this.saveValues) {
            return 'fas fa-plus';
        }

        if (this.editValues) {
            return 'fas fa-pen';
        }

        return 'fas fa-eye';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private applyValidationResult(result: PreviewModalValidationResult): void {
        this.externalValid = result.valid;
        this.externalErrors = result.errors ?? [];
        this.externalPending = false;
        this.cdr.markForCheck();
    }


    private shallowEqual(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
        if (a === b) {
            return true;
        }
        if (!a || !b) {
            return false;
        }
        const aKeys = Object.keys(a);
        const bKeys = Object.keys(b);
        if (aKeys.length !== bKeys.length) {
            return false;
        }
        for (const key of aKeys) {
            if (a[key] !== b[key]) {
                return false;
            }
        }
        return true;
    }
}
