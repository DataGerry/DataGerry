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
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, Input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, finalize, of, switchMap } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import {
    RACK_SLOT_AREAS,
    RackArea,
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
export class RackMountModalComponent implements OnInit {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /**
     * Decorator inputs on purpose: NgbModal hands the values over by assigning them on the component
     * instance, and a signal input cannot be written from the outside. They are set once, before the
     * first change detection run, and never change while the modal is open.
     */
    @Input() public rackId: number;
    @Input() public rackHeight = 0;
    /** Set when an existing mount is edited; null when a new object is mounted. */
    @Input() public mount: RackMountRow | null = null;
    @Input() public presetArea: RackArea = RackArea.FRONT;
    @Input() public presetStartSlot: number | null = null;

    public readonly areaOptions = AREA_OPTIONS;
    public readonly isLoading$ = this.loaderService.isLoading$;
    public readonly validationErrors = signal<string[]>([]);

    public readonly form = new FormGroup({
        objectId: new FormControl<number | null>(null, Validators.required),
        area: new FormControl<RackArea>(RackArea.FRONT, Validators.required),
        startSlot: new FormControl<number | null>(null),
        height: new FormControl<number | null>(null),
        position: new FormControl<number | null>(null)
    });

    /** The form values as a signal, so what the template shows is derived once per change, not per cycle. */
    private readonly formValue = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });

    public readonly isSlotArea = computed(() => RACK_SLOT_AREAS.includes(this.formValue().area));

    /** An unplaced mount keeps its height as a hint, so re-placing it can be pre-filled. */
    public readonly showsHeight = computed(() => this.isSlotArea() || this.formValue().area === RackArea.UNASSIGNED);

    public readonly showsPosition = computed(() => !this.isSlotArea());

    /** Spells out the slots the current input would take, since the anchor extends downward. */
    public readonly slotRangeHint = computed<string | null>(() => {
        if (!this.isSlotArea()) {
            return null;
        }

        const { startSlot, height } = this.formValue();
        const anchorSlot = this.toNumber(startSlot);
        const span = this.toNumber(height);

        if (anchorSlot === null || span === null) {
            return null;
        }

        return `Occupies slot ${anchorSlot - span + 1} to ${anchorSlot} of ${this.rackHeight}U.`;
    });

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.seedForm();
        this.applyAreaRules(this.form.controls.area.value);

        this.form.controls.area.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((area) => {
                this.applyAreaRules(area);
                this.validationErrors.set([]);
            });
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onObjectSelected(): void {
        this.validationErrors.set([]);
    }

    /** Pre-validates through the dry-run route and only writes when the placement is accepted. */
    public onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }

        this.validationErrors.set([]);
        this.loaderService.show();

        this.rackOverviewService
            .validateMount(this.rackId, this.buildValidatePayload())
            .pipe(
                switchMap((validation) => this.persistWhenValid(validation)),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (saved) => {
                    if (saved) {
                        this.activeModal.close(true);
                    }
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get isEditMode(): boolean {
        return this.mount !== null;
    }

    public get title(): string {
        return this.isEditMode ? 'Edit mount' : 'Mount object';
    }

    /**
     * The error texts read `touched` and `valid`, which reactive forms do not expose as signals, so
     * they stay getters and are re-read on the change detection the form's own events trigger.
     */
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
            this.validationErrors.set((validation?.errors ?? []).map(error => error.message));
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
