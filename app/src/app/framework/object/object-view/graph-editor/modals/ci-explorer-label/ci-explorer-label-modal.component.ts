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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, Input, OnDestroy, OnInit } from '@angular/core';
import { FormControl, FormGroup } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { CiExplorerService } from 'src/app/framework/services/ci-explorer.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { GraphNode } from '../../interfaces/graph.interfaces';
import { LabelFieldOption, labelFieldOptions, titleForLabelField } from '../../utils/graph-label.util';

/** The option panel renders here so the scrolling modal body cannot clip the field list. */
const DROPDOWN_HOST = '.dg-modal-window';

/**
 * Picks the field whose value names a type's nodes in the CI Explorer.
 *
 * Closes with the saved field name, or with `undefined` when nothing was written.
 */
@Component({
    selector: 'cmdb-ci-explorer-label-modal',
    templateUrl: './ci-explorer-label-modal.component.html',
    styleUrls: ['./ci-explorer-label-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class CiExplorerLabelModalComponent implements OnInit, OnDestroy {
    @Input() typeId!: number;
    @Input() typeLabel = '';
    /** The right-clicked node, used only to preview what the chosen field would show. */
    @Input() sampleNode: GraphNode | null = null;

    readonly activeModal = inject(NgbActiveModal);

    readonly form = new FormGroup({
        labelField: new FormControl<string | null>(null)
    });

    readonly dropdownHost = DROPDOWN_HOST;

    fieldOptions: LabelFieldOption[] = [];
    loadFailed = false;
    preview: string | null = null;

    private initialField: string | null = null;
    private saving = false;

    private readonly ciExplorerService = inject(CiExplorerService);
    private readonly typeService = inject(TypeService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly cdr = inject(ChangeDetectorRef);
    private readonly unsubscribe$ = new Subject<void>();

    readonly isLoading$ = this.loaderService.isLoading$;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngOnInit(): void {
        this.form.controls.labelField.valueChanges
            .pipe(takeUntil(this.unsubscribe$))
            .subscribe(field => this.updatePreview(field));

        this.loadType();
    }


    ngOnDestroy(): void {
        this.unsubscribe$.next();
        this.unsubscribe$.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** What the node would read once the picked field is saved, worded as the canvas words it. */
    get previewLabel(): string {
        if (this.preview === null) {
            return 'Label not selected';
        }
        return this.preview === '' ? 'Label is empty' : this.preview;
    }


    get canSave(): boolean {
        return !this.loadFailed && !this.saving && this.form.controls.labelField.value !== this.initialField;
    }


    save(): void {
        if (!this.canSave) {
            return;
        }

        const field = this.form.controls.labelField.value ?? null;

        this.saving = true;
        this.loaderService.show();
        this.ciExplorerService.updateLabelField(this.typeId, field)
            .pipe(
                takeUntil(this.unsubscribe$),
                finalize(() => {
                    this.saving = false;
                    this.loaderService.hide();
                    this.cdr.markForCheck();
                })
            )
            .subscribe({
                next: response => {
                    this.toastService.success('CI Explorer label updated.');
                    this.activeModal.close(response?.ci_explorer_label ?? null);
                },
                error: () => this.toastService.error('The CI Explorer label could not be saved. Please try again.')
            });
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadType(): void {
        this.loaderService.show();
        this.typeService.getType(this.typeId)
            .pipe(
                takeUntil(this.unsubscribe$),
                finalize(() => {
                    this.loaderService.hide();
                    this.cdr.markForCheck();
                })
            )
            .subscribe({
                next: (type: CmdbType) => {
                    this.fieldOptions = labelFieldOptions(type);
                    this.initialField = this.resolveInitialField(type);
                    this.form.controls.labelField.setValue(this.initialField, { emitEvent: false });
                    this.updatePreview(this.initialField);
                },
                error: () => {
                    this.loadFailed = true;
                    this.form.controls.labelField.disable({ emitEvent: false });
                    this.toastService.error('The fields of this type could not be loaded.');
                }
            });
    }


    /** A label pointing at a field that no longer qualifies is shown as unset. */
    private resolveInitialField(type: CmdbType): string | null {
        const current = type?.ci_explorer_label || null;
        return this.fieldOptions.some(option => option.name === current) ? current : null;
    }


    private updatePreview(field: string | null): void {
        this.preview = this.sampleNode?.ciNode
            ? titleForLabelField(this.sampleNode.ciNode, field)
            : null;
        this.cdr.markForCheck();
    }
}
