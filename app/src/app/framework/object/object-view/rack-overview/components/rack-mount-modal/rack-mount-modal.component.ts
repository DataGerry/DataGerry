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
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, Input, OnInit, OnDestroy } from '@angular/core';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, Subject, finalize, of, switchMap, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

import {
    RACK_SLOT_AREAS,
    RackArea,
    RackAssignableObject,
    RackMountPayload,
    RackMountRow,
    RackMountUpdatePayload,
    RackMountValidatePayload,
    RackMountValidationResponse
} from '../../models/rack-overview.types';
import { RackOverviewService } from '../../services/rack-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

interface RackAreaOption {
    value: RackArea;
    label: string;
}

/** Assignable objects are pulled in pages as the dropdown is scrolled. */
const ASSIGNABLE_PAGE_SIZE = 25;

const AREA_OPTIONS: RackAreaOption[] = [
    { value: RackArea.FRONT, label: 'Front' },
    { value: RackArea.BACK, label: 'Rear' },
    { value: RackArea.FULL_DEPTH, label: 'Full depth (front and rear)' },
    { value: RackArea.LEFT, label: 'Left side' },
    { value: RackArea.RIGHT, label: 'Right side' },
    { value: RackArea.UNASSIGNED, label: 'Not placed yet' }
];


@Component({
    selector: 'cmdb-rack-mount-modal',
    templateUrl: './rack-mount-modal.component.html',
    styleUrls: ['./rack-mount-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RackMountModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public rackId: number;
    @Input() public rackHeight = 0;
    /** Set when an existing mount is edited; null when a new object is mounted. */
    @Input() public mount: RackMountRow | null = null;
    @Input() public presetArea: RackArea = RackArea.FRONT;
    @Input() public presetStartSlot: number | null = null;

    public readonly areaOptions = AREA_OPTIONS;
    public readonly isLoading$ = this.loaderService.isLoading$;
    public validationErrors: string[] = [];
    public assignableObjects: RackAssignableObject[] = [];
    /** Drives the dropdown spinner while a page is in flight. */
    public isFetchingPage = false;
    public assignableTotal = 0;

    private nextPage = 1;
    private hasMoreAssignableObjects = true;

    public readonly form = new FormGroup({
        objectId: new FormControl<number | null>(null, Validators.required),
        area: new FormControl<RackArea>(RackArea.FRONT, Validators.required),
        startSlot: new FormControl<number | null>(null),
        height: new FormControl<number | null>(null),
        position: new FormControl<number | null>(null)
    });

    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.seedForm();
        this.applyAreaRules(this.form.controls.area.value);

        if (!this.isEditMode) {
            this.loadAssignableObjects();
        }

        this.form.controls.area.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe((area) => {
                this.applyAreaRules(area);
                this.validationErrors = [];
                this.changesRef.markForCheck();
            });
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onObjectSelected(): void {
        this.validationErrors = [];
        this.changesRef.markForCheck();
    }

    /** Reaching the end of the option list pulls the next page in. */
    public onAssignableScrollEnd(): void {
        this.loadAssignableObjects();
    }

    /** Pre-validates through the dry-run route and only writes when the placement is accepted. */
    public onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }

        this.validationErrors = [];
        this.loaderService.show();

        this.rackOverviewService
            .validateMount(this.rackId, this.buildValidatePayload())
            .pipe(
                switchMap((validation) => this.persistWhenValid(validation)),
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (saved) => {
                    if (saved) {
                        this.activeModal.close(true);
                        return;
                    }
                    this.changesRef.markForCheck();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get isEditMode(): boolean {
        return this.mount !== null;
    }

    public get isSlotArea(): boolean {
        return RACK_SLOT_AREAS.includes(this.form.controls.area.value);
    }

    /** An unplaced mount keeps its height as a hint, so re-placing it can be pre-filled. */
    public get showsHeight(): boolean {
        return this.isSlotArea || this.form.controls.area.value === RackArea.UNASSIGNED;
    }

    public get showsPosition(): boolean {
        return !this.isSlotArea;
    }

    public get title(): string {
        return this.isEditMode ? 'Edit mount' : 'Mount object';
    }

    /** Spells out the slots the current input would take, since the anchor extends downward. */
    public get slotRangeHint(): string | null {
        if (!this.isSlotArea) {
            return null;
        }

        const startSlot = this.toNumber(this.form.controls.startSlot.value);
        const height = this.toNumber(this.form.controls.height.value);

        if (startSlot === null || height === null) {
            return null;
        }

        return `Occupies slot ${startSlot - height + 1} to ${startSlot} of ${this.rackHeight}U.`;
    }

    public get startSlotError(): string {
        const control = this.form.controls.startSlot;

        if (control.valid || !control.touched) {
            return '';
        }

        return control.hasError('required')
            ? 'A start slot is required in this area.'
            : `Enter a slot between 1 and ${this.rackHeight}.`;
    }

    public get heightError(): string {
        const control = this.form.controls.height;

        if (control.valid || !control.touched) {
            return '';
        }

        return control.hasError('required')
            ? 'A height is required in this area.'
            : `Enter a height between 1 and ${this.rackHeight}U.`;
    }

    public get positionError(): string {
        const control = this.form.controls.position;

        return control.valid || !control.touched ? '' : 'The position must be 0 or higher.';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Loads the next page of assignable objects and appends it. The first page runs behind the modal
     * loader; later pages report through the dropdown's own spinner, since the user is still in it.
     */
    private loadAssignableObjects(): void {
        if (this.isFetchingPage || !this.hasMoreAssignableObjects) {
            return;
        }

        const isFirstPage = this.nextPage === 1;
        this.isFetchingPage = true;

        if (isFirstPage) {
            this.loaderService.show();
        }

        this.rackOverviewService
            .getAssignableObjects(this.rackId, {
                filter: undefined,
                limit: ASSIGNABLE_PAGE_SIZE,
                sort: 'public_id',
                order: 1,
                page: this.nextPage
            })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isFetchingPage = false;

                    if (isFirstPage) {
                        this.loaderService.hide();
                    }

                    this.changesRef.markForCheck();
                })
            )
            .subscribe({
                next: (response) => this.appendAssignablePage(response),
                error: (err) => {
                    // Stop paging on a failed page rather than retrying the same one on every scroll.
                    this.hasMoreAssignableObjects = false;
                    this.toastService.error(err?.error?.message);
                }
            });
    }

    private appendAssignablePage(response: APIGetMultiResponse<RackAssignableObject>): void {
        const page = response?.results ?? [];

        // A fresh array so OnPush picks the new options up.
        this.assignableObjects = [...this.assignableObjects, ...page];
        this.assignableTotal = response?.total ?? this.assignableObjects.length;
        this.hasMoreAssignableObjects = page.length > 0 && this.assignableObjects.length < this.assignableTotal;
        this.nextPage = this.nextPage + 1;
    }

    private seedForm(): void {
        if (this.mount) {
            this.form.patchValue({
                objectId: this.mount.object_id,
                area: this.mount.area,
                startSlot: this.mount.start_slot,
                height: this.mount.height,
                position: this.mount.position
            });
            this.form.controls.objectId.disable();
            return;
        }

        this.form.patchValue({
            area: this.presetArea,
            startSlot: this.presetStartSlot,
            height: RACK_SLOT_AREAS.includes(this.presetArea) ? 1 : null
        });
    }

    /**
     * A main-area mount needs a start slot and a height and has no position; a side or unassigned
     * mount is the other way round. Only the fields the chosen area actually uses stay enabled, so a
     * leftover value can never travel to the backend.
     */
    private applyAreaRules(area: RackArea): void {
        const { startSlot, height, position } = this.form.controls;

        if (RACK_SLOT_AREAS.includes(area)) {
            startSlot.setValidators([Validators.required, Validators.min(1), Validators.max(this.rackHeight)]);
            height.setValidators([Validators.required, Validators.min(1), Validators.max(this.rackHeight)]);
            startSlot.enable();
            height.enable();
            position.reset(null);
            position.disable();
        } else {
            startSlot.clearValidators();
            startSlot.reset(null);
            startSlot.disable();

            if (area === RackArea.UNASSIGNED) {
                height.setValidators([Validators.min(1), Validators.max(this.rackHeight)]);
                height.enable();
            } else {
                height.clearValidators();
                height.reset(null);
                height.disable();
            }

            position.setValidators([Validators.min(0)]);
            position.enable();
        }

        startSlot.updateValueAndValidity({ emitEvent: false });
        height.updateValueAndValidity({ emitEvent: false });
        position.updateValueAndValidity({ emitEvent: false });
    }

    private persistWhenValid(validation: RackMountValidationResponse): Observable<unknown | null> {
        if (!validation?.valid) {
            this.validationErrors = (validation?.errors ?? []).map(error => error.message);
            return of(null);
        }

        if (this.isEditMode) {
            return this.rackOverviewService.updateMount(this.rackId, this.mount.mount_id, this.buildUpdatePayload());
        }

        return this.rackOverviewService.mountObject(this.rackId, this.buildInsertPayload());
    }

    private buildValidatePayload(): RackMountValidatePayload {
        const payload: RackMountValidatePayload = {
            ...this.buildGeometry(),
            object_id: this.isEditMode ? this.mount.object_id : this.form.controls.objectId.value
        };

        if (this.isEditMode) {
            payload.mount_id = this.mount.mount_id;
        }

        return payload;
    }

    private buildInsertPayload(): RackMountPayload {
        return {
            ...this.buildGeometry(),
            object_id: this.form.controls.objectId.value
        };
    }

    private buildUpdatePayload(): RackMountUpdatePayload {
        return this.buildGeometry();
    }

    /**
     * Geometry of the candidate placement. The unused axis is sent as null so a move away from it
     * clears the stale value, and an omitted position lets the backend append to the area.
     */
    private buildGeometry(): RackMountUpdatePayload {
        const { area, startSlot, height, position } = this.form.getRawValue();

        if (RACK_SLOT_AREAS.includes(area)) {
            return {
                area,
                start_slot: this.toNumber(startSlot),
                height: this.toNumber(height),
                position: null
            };
        }

        const geometry: RackMountUpdatePayload = {
            area,
            start_slot: null,
            height: area === RackArea.UNASSIGNED ? this.toNumber(height) : null
        };

        if (position != null && `${position}` !== '') {
            geometry.position = this.toNumber(position);
        }

        return geometry;
    }

    /** Number inputs hand back strings, and the backend range-checks whatever it receives. */
    private toNumber(value: number | string | null): number | null {
        if (value == null || `${value}`.trim() === '') {
            return null;
        }

        return Number(value);
    }
}
