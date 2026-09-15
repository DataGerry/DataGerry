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
import { ChangeDetectorRef, Component, Input, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { MovingDirection, WizardComponent } from '@rg-software/angular-archwizard';

import { Subject, finalize, takeUntil } from 'rxjs';

import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { PortOptionType } from 'src/app/framework/models/port-option-type';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { PortDeviceKind, PortNamePreview } from '../../models/port-bulk.types';
import { PORT_OPTION_TYPES } from '../../models/ports-overview.types';
import { PortService } from '../../services/port.service';
import { EMPTY_PREVIEW_SUMMARY, PortPreviewSummary, toPreviewSummary } from '../../utils/port-preview.util';
import { DEVICE_KIND_CHOICES, labelOfDeviceKind } from './port-device-kinds';
import { PortCreateWizardForm, PortWizardFormGroup, PortWizardTextControl } from './port-create-wizard.form';
/* ------------------------------------------------------------------------------------------------------------------ */

/** 0-based position of the step that previews the names and creates them. */
const PREVIEW_STEP = 3;


/**
 * Creates a whole device's ports in one pass: device kind, naming, numbering, then the preview the
 * user approves before anything is written.
 *
 * Names and collisions come from the server - `name_preview` and the bulk creation run the same
 * builder, so what is approved is what is stored. Closes with `true` once the batch is in.
 */
@Component({
    selector: 'cmdb-port-create-wizard-modal',
    templateUrl: './port-create-wizard-modal.component.html',
    styleUrls: ['./port-create-wizard-modal.component.scss'],
    standalone: false
})
export class PortCreateWizardModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly portService = inject(PortService);
    private readonly optionCatalog = inject(ExtendableOptionCatalogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public objectId: number | null = null;

    /** The object the ports are created on, shown as the subtitle. */
    @Input() public objectLabel = '';

    @ViewChild(WizardComponent) private wizard: WizardComponent;

    public readonly wizardForm = new PortCreateWizardForm();
    public readonly deviceKinds = DEVICE_KIND_CHOICES;
    public readonly isLoading$ = this.loaderService.isLoading$;

    public statusOptions: FieldOption[] = [];
    public portTypeOptions: FieldOption[] = [];
    public speedOptions: FieldOption[] = [];

    /** 0-based position of the step the user is on, which the footer navigates from. */
    public stepIndex = 0;

    public preview: PortPreviewSummary = EMPTY_PREVIEW_SUMMARY;

    /** Set when the preview could not be built - its message is the backend's refusal. */
    public previewError = '';

    private namePreview: PortNamePreview | null = null;
    private isCreating = false;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadOptions();

        // A changed value invalidates the approved preview, so the last step has to ask for a new one.
        this.wizardForm.group.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => this.dropPreview());

        this.wizardForm.group.controls.syntax.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => this.wizardForm.revalidateRearSyntax());
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSelectDeviceKind(kind: PortDeviceKind): void {
        this.wizardForm.selectDeviceKind(kind);
    }


    public onStepEnter(index: number): void {
        this.stepIndex = index;

        if (this.isPreviewStep) {
            this.runPreview();
        }
    }


    public onBack(): void {
        this.wizard?.goToPreviousStep();
    }


    /** The footer carries one primary action, which is "next" until the preview is on screen. */
    public onPrimary(): void {
        if (this.isPreviewStep) {
            this.onCreate();
            return;
        }

        this.onNext();
    }


    public onNext(): void {
        if (!this.canLeaveCurrentStep) {
            this.wizardForm.markStepTouched(this.stepIndex);
            this.changesRef.markForCheck();
            return;
        }

        this.wizard?.goToNextStep();
    }


    public onCreate(): void {
        const deviceKind = this.wizardForm.deviceKind;

        if (this.objectId == null || deviceKind === null || !this.canCreate) {
            return;
        }

        this.createPorts(this.objectId, deviceKind);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The template binds the group directly, both as `[formGroup]` and for the device-kind cards. */
    public get form(): PortWizardFormGroup {
        return this.wizardForm.group;
    }


    public get isPatchPanel(): boolean {
        return this.wizardForm.isPatchPanel;
    }


    public get isPreviewStep(): boolean {
        return this.stepIndex === PREVIEW_STEP;
    }


    public get primaryLabel(): string {
        return this.isPreviewStep ? 'Create ports' : 'Next';
    }


    public get primaryIcon(): string {
        return this.isPreviewStep ? 'fas fa-plus' : '';
    }


    public get primaryDisabled(): boolean {
        return this.isPreviewStep && !this.canCreate;
    }


    public get selectedKindLabel(): string {
        return labelOfDeviceKind(this.wizardForm.deviceKind);
    }


    /** The wizard only lets a step be left once its own fields hold up. */
    public get canLeaveCurrentStep(): boolean {
        return this.wizardForm.isStepValid(this.stepIndex);
    }


    public get canCreate(): boolean {
        return this.namePreview !== null && !this.preview.hasCollisions && !this.previewError && !this.isCreating;
    }


    /** Going back is always allowed: a half-filled step still has to be correctable. */
    public readonly canExitStep = (direction: MovingDirection): boolean => {
        return direction !== MovingDirection.Forwards || this.canLeaveCurrentStep;
    };


    public errorOf(controlName: PortWizardTextControl): string {
        return this.wizardForm.errorOf(controlName);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** One request for all three option lists, then cached by the catalog. */
    private loadOptions(): void {
        this.loaderService.show();

        this.optionCatalog.optionsForTypes(PORT_OPTION_TYPES)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (optionsByType) => {
                    this.statusOptions = optionsByType.get(PortOptionType.STATUS) ?? [];
                    this.portTypeOptions = optionsByType.get(PortOptionType.PORT_TYPE) ?? [];
                    this.speedOptions = optionsByType.get(PortOptionType.SPEED) ?? [];
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private runPreview(): void {
        const deviceKind = this.wizardForm.deviceKind;

        if (this.objectId == null || deviceKind === null || this.wizardForm.group.invalid) {
            return;
        }

        this.dropPreview();
        this.loaderService.show();

        this.portService.previewPortNames(this.objectId, this.wizardForm.toNamingRequest(deviceKind))
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (preview) => this.applyPreview(preview),
                error: (err) => {
                    this.previewError = err?.error?.message
                        || 'The names could not be worked out. Check the name and the numbering.';
                }
            });
    }


    private applyPreview(preview: PortNamePreview): void {
        this.namePreview = preview ?? null;
        this.preview = toPreviewSummary(this.namePreview);
    }


    private dropPreview(): void {
        this.namePreview = null;
        this.preview = EMPTY_PREVIEW_SUMMARY;
        this.previewError = '';
    }


    private createPorts(objectId: number, deviceKind: PortDeviceKind): void {
        this.isCreating = true;
        this.loaderService.show();

        this.portService.bulkCreatePorts(objectId, this.wizardForm.toBulkRequest(deviceKind))
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isCreating = false;
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (result) => {
                    const created = result?.total_ports ?? 0;

                    this.toastService.success(`${ created } ports were successfully created!`);
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
