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

import { Observable, Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { FieldOption } from 'src/app/framework/models/cmdb-section-template';
import { ToastService } from 'src/app/layout/toast/toast.service';

import {
    CableManagementMode,
    CableSource,
    CmdbPortConnection,
    ConnectionEndpoint,
    ConnectionType
} from '../../models/port-connection.types';
import { CmdbPort } from '../../models/ports-overview.types';
import { CableCatalogService } from '../../services/cable-catalog.service';
import { ConnectionEndpointService } from '../../services/connection-endpoint.service';
import { PortConnectionService } from '../../services/port-connection.service';
import { CableOption } from '../cable-ci-picker/cable-ci-picker.component';
import { ChoiceCard } from '../choice-card-group/choice-card-group.component';
import { ConnectionForm, ConnectionFormGroup, ConnectionStep } from './connection-form';
import { ReviewRow, buildEndpointRows, buildReviewRows } from './connection-review';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Where the option panels are rendered.
 *
 * The modal body is the element that scrolls, so a panel left inline is clipped by it and the user
 * has to scroll the dialog to read its own dropdown. The window sits outside that scroll box.
 */
const DROPDOWN_HOST = '.dg-modal-window';

/** The two ways of managing a cable, as the choice is presented. */
const MANAGEMENT_CHOICES: readonly ChoiceCard<CableManagementMode>[] = [
    {
        value: CableManagementMode.METADATA,
        icon: 'fas fa-tag',
        label: 'Metadata only',
        text: 'Described on the connection. No extra object to maintain.'
    },
    {
        value: CableManagementMode.CABLE_CI,
        icon: 'fas fa-boxes-stacked',
        label: 'Link a cable CI',
        text: 'The cable is its own object, with serial number, cost and history.'
    }
];


/**
 * Connects two ports, or edits the cable of a connection that already exists.
 *
 * Both writes are one wizard because they ask the same questions - only what is being joined differs,
 * and that is immutable once stored, so the first step states it instead of asking again. Closes with
 * `true` as soon as the connection is written.
 */
@Component({
    selector: 'cmdb-connection-form-modal',
    templateUrl: './connection-form-modal.component.html',
    styleUrls: ['./connection-form-modal.component.scss'],
    standalone: false
})
export class ConnectionFormModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);

    private readonly portConnectionService = inject(PortConnectionService);
    private readonly endpointService = inject(ConnectionEndpointService);
    private readonly cableCatalog = inject(CableCatalogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    /** The port the dialog was opened from - the near end of the cable. */
    @Input() public port: CmdbPort | null = null;

    /** The object that port belongs to, named the way the user recognises it. */
    @Input() public objectLabel = '';

    /** The connection being edited, or null to cable the port for the first time. */
    @Input() public connection: CmdbPortConnection | null = null;

    @ViewChild(WizardComponent) private wizard: WizardComponent;

    public readonly connectionForm = new ConnectionForm();
    public readonly managementChoices = MANAGEMENT_CHOICES;
    public readonly dropdownHost = DROPDOWN_HOST;
    public readonly step = ConnectionStep;

    /** The near end, named the way the user recognises it: device first, then port. */
    public nearEndpoint: ConnectionEndpoint | null = null;

    /** The other end, filled in by the picker while creating and resolved while editing. */
    public farEndpoint: ConnectionEndpoint | null = null;

    public cableTypeOptions: FieldOption[] = [];

    /** Types carrying the CABLE marker; only their objects can be an inventoried cable. */
    public cableCiTypeIds: number[] = [];

    /** The step the user is on. Named rather than numbered: the cable step comes and goes. */
    public currentStep = ConnectionStep.ENDPOINTS;

    public readonly isLoading$ = this.loaderService.isLoading$;

    /** Label of the linked cable CI, so the review step names it rather than showing its id. */
    private cableCiLabel = '';

    private isWriting = false;

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.nearEndpoint = this.port ? this.endpointService.nearEndpoint(this.port, this.objectLabel) : null;

        if (this.connection) {
            this.resolveFarEndpoint(this.connection);
        }

        if (this.isInternal) {
            // A panel's internal pairing carries no cable at all, so there is nothing to ask for.
            return;
        }

        if (this.connection) {
            this.connectionForm.lockEndpoints();
            this.connectionForm.prefill(this.connection);

            // The read already names the linked cable, so the review need not wait for a re-pick.
            if (this.connection.cable?.source === CableSource.CI) {
                this.cableCiLabel = this.connection.cable.name ?? '';
            }
        }

        this.loadCatalog();
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onStepEnter(step: ConnectionStep): void {
        this.currentStep = step;
    }


    public onBack(): void {
        this.wizard?.goToPreviousStep();
    }


    /** The footer carries one primary action, which is "next" until the review is on screen. */
    public onPrimary(): void {
        if (this.isReviewStep) {
            this.onSubmit();
            return;
        }

        this.onNext();
    }


    public onNext(): void {
        if (!this.canLeaveCurrentStep) {
            this.connectionForm.markStepTouched(this.currentStep);
            this.changesRef.markForCheck();
            return;
        }

        this.wizard?.goToNextStep();
    }


    public onSelectManagementMode(mode: CableManagementMode): void {
        this.connectionForm.selectManagementMode(mode);

        if (mode === CableManagementMode.METADATA) {
            this.cableCiLabel = '';
        }
    }


    public onFarEndpointChange(endpoint: ConnectionEndpoint | null): void {
        this.farEndpoint = endpoint;
    }


    public onCableCiSelected(cableCi: CableOption | null): void {
        this.cableCiLabel = cableCi?.option_label ?? '';
    }


    public onSubmit(): void {
        if (this.port == null || this.isInternal || !this.canWrite) {
            return;
        }

        if (this.connection) {
            this.write(
                this.portConnectionService.updateCableInfo(this.connection.public_id, this.connectionForm.toCableInfo()),
                'The cable was successfully updated!'
            );

            return;
        }

        this.write(
            this.portConnectionService.createConnection(this.connectionForm.toCreatePayload(this.port.public_id)),
            'The ports were successfully connected!'
        );
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The template binds the group directly, both as `[formGroup]` and for the mode cards. */
    public get form(): ConnectionFormGroup {
        return this.connectionForm.group;
    }


    public get isEdit(): boolean {
        return this.connection != null;
    }


    /** An internal pairing is read-only: the backend refuses every cable field on one. */
    public get isInternal(): boolean {
        return this.connection?.connection_type === ConnectionType.INTERNAL;
    }


    public get title(): string {
        if (this.isInternal) {
            return 'Internal pairing';
        }

        return this.isEdit ? 'Edit cable' : 'Connect port';
    }


    public get isReviewStep(): boolean {
        return this.currentStep === ConnectionStep.REVIEW;
    }


    /** Back is offered from every step but the first one of the sequence this mode goes through. */
    public get canGoBack(): boolean {
        return this.connectionForm.activeSteps().indexOf(this.currentStep) > 0;
    }


    /** The footer carries one primary action: "next" until the review is on screen, then the write. */
    public get primaryAction(): { label: string; icon: string } {
        if (!this.isReviewStep) {
            return { label: 'Next', icon: '' };
        }

        return this.isEdit
            ? { label: 'Save cable', icon: 'fas fa-save' }
            : { label: 'Connect ports', icon: 'fas fa-link' };
    }


    public get primaryDisabled(): boolean {
        return this.isReviewStep && !this.canWrite;
    }


    /** The wizard only lets a step be left once its own fields hold up. */
    public get canLeaveCurrentStep(): boolean {
        return this.connectionForm.isStepValid(this.currentStep);
    }


    public get canWrite(): boolean {
        return this.form.valid && !this.isWriting;
    }


    /** Going back is always allowed: a half-filled step still has to be correctable. */
    public readonly canExitStep = (direction: MovingDirection): boolean => {
        return direction !== MovingDirection.Forwards || this.canLeaveCurrentStep;
    };


    public get reviewRows(): ReviewRow[] {
        return [
            ...buildEndpointRows(this.nearEndpoint, this.farEndpoint),
            ...buildReviewRows(this.connectionForm, this.cableTypeOptions, this.linkedCableLabel)
        ];
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** The linked cable, named where it is known and by its id where the label has not arrived. */
    private get linkedCableLabel(): string {
        return this.cableCiLabel || `Cable #${ this.form.controls.cableCiId.value }`;
    }


    /** The cable types and the types a cable CI may have, in one round trip. */
    private loadCatalog(): void {
        this.loaderService.show();

        this.cableCatalog.read()
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: ({ cableTypeOptions, cableCiTypeIds }) => {
                    this.cableTypeOptions = cableTypeOptions;
                    this.cableCiTypeIds = cableCiTypeIds;
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private resolveFarEndpoint(connection: CmdbPortConnection): void {
        this.loaderService.show();

        this.endpointService.farEndpoint(connection, this.port?.public_id ?? -1)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe((endpoint) => this.farEndpoint = endpoint);
    }


    /** Both writes report the same way; only the request and the confirmation differ. */
    private write(request: Observable<CmdbPortConnection>, message: string): void {
        this.isWriting = true;
        this.loaderService.show();

        request
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isWriting = false;
                    this.loaderService.hide();
                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: () => {
                    this.toastService.success(message);
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }
}
