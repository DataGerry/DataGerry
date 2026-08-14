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
import { AbstractControl, FormControl, FormGroup, ValidationErrors, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Observable, finalize, of, switchMap } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

import {
    RACK_EDIT_RIGHT,
    RACK_OCCUPANT_FORBIDDEN_AREAS,
    RACK_OCCUPANT_KINDS,
    RACK_SLOT_AREAS,
    RackArea,
    RackMountKind,
    RackMountPayload,
    RackMountRow,
    RackMountUpdatePayload,
    RackMountValidatePayload,
    RackMountValidationResponse,
    kindOf,
    toDayString
} from '../../models/rack-overview.types';
import { RackOverviewService } from '../../services/rack-overview.service';
import { RACK_KIND_LABELS } from '../../utils/rack-visual.util';
/* ------------------------------------------------------------------------------------------------------------------ */

interface RackAreaOption {
    value: RackArea;
    label: string;
}

interface RackKindOption {
    value: RackMountKind;
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

/** The kind names, each with what choosing it means for the rack. */
const KIND_OPTIONS: RackKindOption[] = [
    { value: RackMountKind.MOUNT, label: RACK_KIND_LABELS[RackMountKind.MOUNT] },
    {
        value: RackMountKind.RESERVATION,
        label: `${RACK_KIND_LABELS[RackMountKind.RESERVATION]} (space booked for later)`
    },
    {
        value: RackMountKind.BLOCKER,
        label: `${RACK_KIND_LABELS[RackMountKind.BLOCKER]} (space taken out of use)`
    }
];

/** The backend accepts a plain six digit hex colour only. */
const HEX_COLOR_PATTERN = /^#[\da-fA-F]{6}$/;

/**
 * The dropdowns render into the modal window rather than in place: the scrolling body and the
 * corner-clipping content box would both cut a panel that opens past their edge. The window is the
 * nearest ancestor that clips nothing, and it is the element `windowClass` puts the class on, so it
 * resolves whether the modal is parked on the body or inside the fullscreen rack view.
 */
const DROPDOWN_HOST = '.dg-modal-window';


/**
 * Both dates are optional, but a range that ends before it starts is never what was meant. The values
 * are ISO day strings, which compare chronologically as they are.
 */
function reservationDateRange(group: AbstractControl): ValidationErrors | null {
    const startDate = group.get('startDate')?.value;
    const endDate = group.get('endDate')?.value;

    if (!startDate || !endDate || endDate >= startDate) {
        return null;
    }

    return { dateRangeReversed: true };
}


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
    private readonly permissionService = inject(PermissionService);
    private readonly destroyRef = inject(DestroyRef);

    /** The modal is opened from code, so it re-checks the right instead of trusting its caller. */
    public readonly canEdit = this.permissionService.hasRight(RACK_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(RACK_EDIT_RIGHT);

    /**
     * Decorator inputs on purpose: NgbModal hands the values over by assigning them on the component
     * instance, and a signal input cannot be written from the outside. They are set once, before the
     * first change detection run, and never change while the modal is open.
     */
    @Input() public rackId: number;
    @Input() public rackHeight = 0;
    /** Set when an existing row is edited; null when a new one is added. */
    @Input() public mount: RackMountRow | null = null;
    @Input() public presetArea: RackArea = RackArea.FRONT;
    @Input() public presetStartSlot: number | null = null;

    public readonly kindOptions = KIND_OPTIONS;
    public readonly DROPDOWN_HOST = DROPDOWN_HOST;
    public readonly isLoading$ = this.loaderService.isLoading$;
    public readonly validationErrors = signal<string[]>([]);

    public readonly form = new FormGroup({
        kind: new FormControl<RackMountKind>(RackMountKind.MOUNT, Validators.required),
        objectId: new FormControl<number | null>(null, Validators.required),
        label: new FormControl<string | null>(null),
        area: new FormControl<RackArea>(RackArea.FRONT, Validators.required),
        startSlot: new FormControl<number | null>(null),
        height: new FormControl<number | null>(null),
        position: new FormControl<number | null>(null),
        startDate: new FormControl<string | null>(null),
        endDate: new FormControl<string | null>(null),
        color: new FormControl<string | null>(null)
    }, { validators: reservationDateRange });

    /** The form values as a signal, so what the template shows is derived once per change, not per cycle. */
    private readonly formValue = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });

    /** Disabled controls drop out of `value`, so the kind is read from the raw values. */
    private readonly selectedKind = computed(() => this.formValue().kind ?? this.form.getRawValue().kind);

    public readonly isMount = computed(() => this.selectedKind() === RackMountKind.MOUNT);

    public readonly isReservation = computed(() => this.selectedKind() === RackMountKind.RESERVATION);

    /** The side areas hold objects only, so they leave the list as soon as an occupant is being added. */
    public readonly areaOptions = computed(() => {
        if (!RACK_OCCUPANT_KINDS.includes(this.selectedKind())) {
            return AREA_OPTIONS;
        }

        return AREA_OPTIONS.filter(option => !RACK_OCCUPANT_FORBIDDEN_AREAS.includes(option.value));
    });

    public readonly isSlotArea = computed(() => RACK_SLOT_AREAS.includes(this.formValue().area));

    /** An unplaced row keeps its height as a hint, so re-placing it can be pre-filled. */
    public readonly showsHeight = computed(() => this.isSlotArea() || this.formValue().area === RackArea.UNASSIGNED);

    public readonly showsPosition = computed(() => !this.isSlotArea());

    public readonly kindLabel = computed(() => RACK_KIND_LABELS[this.selectedKind()]);

    public readonly title = computed(() => `${this.isEditMode ? 'Edit' : 'Add'} ${this.kindLabel().toLowerCase()}`);

    public readonly subtitle = computed(() => (this.rackHeight ? `${this.rackHeight}U rack` : ''));

    /**
     * Spells out the slots the current input would take, since the anchor extends downward. Until both
     * values are in it explains the counting direction, and it warns as soon as the span would run off
     * the bottom, which the height-first order makes easy to walk into.
     */
    public readonly slotRange = computed<{ text: string; warn: boolean }>(() => {
        const { startSlot, height } = this.formValue();
        const anchorSlot = this.toNumber(startSlot);
        const span = this.toNumber(height);

        if (anchorSlot === null || span === null) {
            return { text: `Slot 1 is the bottom of the rack, slot ${this.rackHeight} the top.`, warn: false };
        }

        const bottomSlot = anchorSlot - span + 1;

        if (bottomSlot < 1) {
            return { text: `${span}U does not fit below slot ${anchorSlot}.`, warn: true };
        }

        return { text: `Occupies slot ${bottomSlot} to ${anchorSlot} of ${this.rackHeight}U.`, warn: false };
    });

    /** Only a complete hex is previewed, so a half typed value does not flash a colour. */
    public readonly previewColor = computed(() => {
        const color = this.formValue().color ?? '';

        return HEX_COLOR_PATTERN.test(color) ? color : null;
    });

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.seedForm();
        this.applyKindRules(this.form.getRawValue().kind);
        this.applyAreaRules(this.form.controls.area.value);

        this.form.controls.kind.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((kind) => {
                this.applyKindRules(kind);
                this.validationErrors.set([]);
            });

        this.form.controls.area.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((area) => {
                this.applyAreaRules(area);
                this.validationErrors.set([]);
            });

        // Read-only without the right; silent, so the derived fields keep the values they show.
        if (!this.canEdit) {
            this.form.disable({ emitEvent: false });
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onObjectSelected(): void {
        this.validationErrors.set([]);
    }

    /** Pre-validates through the dry-run route and only writes when the placement is accepted. */
    public onSubmit(): void {
        if (!this.canEdit) {
            return;
        }

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

    public get colorError(): string {
        const control = this.form.controls.color;

        return control.valid || !control.touched ? '' : 'Use a six digit hex colour, for example #4CAF50.';
    }

    public get dateRangeError(): string {
        return this.form.hasError('dateRangeReversed') ? 'The end date cannot be earlier than the start date.' : '';
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private seedForm(): void {
        if (this.mount) {
            this.form.patchValue({
                kind: kindOf(this.mount),
                objectId: this.mount.object_id,
                label: this.mount.label,
                area: this.mount.area,
                startSlot: this.mount.start_slot,
                height: this.mount.height,
                position: this.mount.position,
                startDate: toDayString(this.mount.start_date),
                endDate: toDayString(this.mount.end_date),
                color: this.mount.color
            });
            // The kind cannot be changed after the row exists.
            this.form.controls.kind.disable();
            return;
        }

        this.form.patchValue({
            area: this.presetArea,
            startSlot: this.presetStartSlot,
            height: RACK_SLOT_AREAS.includes(this.presetArea) ? 1 : null
        });
    }

    /**
     * Each kind owns a different set of fields and the backend rejects the ones it does not own, so
     * only those stay enabled: an object for a mount, dates and a colour for a reservation, and for a
     * blocker neither. A label belongs to all three.
     */
    private applyKindRules(kind: RackMountKind): void {
        const { objectId, startDate, endDate, color, area } = this.form.controls;

        if (kind === RackMountKind.MOUNT && !this.isEditMode) {
            objectId.setValidators(Validators.required);
            objectId.enable();
        } else {
            objectId.clearValidators();

            if (!this.isEditMode) {
                objectId.reset(null);
            }

            objectId.disable();
        }

        if (kind === RackMountKind.RESERVATION) {
            color.setValidators(Validators.pattern(HEX_COLOR_PATTERN));
            startDate.enable();
            endDate.enable();
            color.enable();
        } else {
            color.clearValidators();
            startDate.reset(null);
            endDate.reset(null);
            color.reset(null);
            startDate.disable();
            endDate.disable();
            color.disable();
        }

        // An occupant cannot sit in a side area, so a preselected one has to give way.
        if (RACK_OCCUPANT_KINDS.includes(kind) && RACK_OCCUPANT_FORBIDDEN_AREAS.includes(area.value)) {
            area.setValue(RackArea.FRONT);
        }

        objectId.updateValueAndValidity({ emitEvent: false });
        color.updateValueAndValidity({ emitEvent: false });
    }

    /**
     * A main-area row needs a start slot and a height and has no position; a side or unassigned row is
     * the other way round. Only the fields the chosen area actually uses stay enabled, so a leftover
     * value can never travel to the backend.
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
            ...this.buildKindFields()
        };

        if (this.isEditMode) {
            payload.mount_id = this.mount.mount_id;
        }

        return payload;
    }

    private buildInsertPayload(): RackMountPayload {
        return {
            ...this.buildGeometry(),
            ...this.buildKindFields()
        };
    }

    /**
     * The kind is immutable, so a PATCH carries the fields of the existing kind only. A null clears the
     * stored value, which is what an emptied input means.
     */
    private buildUpdatePayload(): RackMountUpdatePayload {
        const { label, startDate, endDate, color } = this.form.getRawValue();

        const payload: RackMountUpdatePayload = {
            ...this.buildGeometry(),
            label: this.toText(label)
        };

        if (kindOf(this.mount) === RackMountKind.RESERVATION) {
            payload.start_date = this.toIsoDate(startDate);
            payload.end_date = this.toIsoDate(endDate);
            payload.color = this.toText(color);
        }

        return payload;
    }

    /** Only the fields the chosen kind owns; the backend refuses the rest rather than ignoring them. */
    private buildKindFields(): RackMountPayload {
        const kind = this.form.getRawValue().kind;
        const { objectId, label, startDate, endDate, color } = this.form.getRawValue();

        const payload: RackMountPayload = { kind, label: this.toText(label) };

        if (kind === RackMountKind.MOUNT) {
            payload.object_id = this.isEditMode ? this.mount.object_id : objectId;
            return payload;
        }

        if (kind === RackMountKind.RESERVATION) {
            payload.start_date = this.toIsoDate(startDate);
            payload.end_date = this.toIsoDate(endDate);
            payload.color = this.toText(color);
        }

        return payload;
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

    /** An emptied text input means "no value", which the backend spells as null. */
    private toText(value: string | null): string | null {
        const text = (value ?? '').trim();

        return text === '' ? null : text;
    }

    /** The date input yields a plain day; the backend stores an instant, so it is sent as midnight UTC. */
    private toIsoDate(value: string | null): string | null {
        return value ? `${value}T00:00:00+00:00` : null;
    }
}
