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
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    Injector,
    Input,
    OnInit,
    ViewChild,
    afterNextRender,
    computed,
    inject,
    signal
} from '@angular/core';
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
    RackAssignableObject,
    RackMountKind,
    RackMountRow,
    RackMountValidationResponse,
    RackRowView,
    kindOf,
    toDayString
} from '../../models/rack-overview.types';
import { RackOverviewService } from '../../services/rack-overview.service';
import { fitsAt, freeRuns, measureArea, runContaining, slotOptions } from '../../utils/rack-availability.util';
import { slotRangeText } from '../../utils/rack-layout.util';
import {
    buildInsertPayload,
    buildUpdatePayload,
    buildValidatePayload,
    toNumber
} from '../../utils/rack-mount-form.util';
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
    private readonly injector = inject(Injector);

    /** Focused when a save is refused, which both announces the reasons and brings them into view. */
    @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;

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
    /**
     * The rack as it stands, so the form can work out what is still free. A snapshot taken when the
     * modal opened: it drives the slot list only, never what is written, which the backend re-checks.
     */
    @Input() public rows: RackRowView[] = [];

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

    /**
     * Built once in ngOnInit: what each area still has free never changes while the modal is open, and
     * rebuilding the labels on every keystroke would hand ng-select a fresh item list each time.
     */
    private readonly annotatedAreas = signal<RackAreaOption[]>(AREA_OPTIONS);

    /** The side areas hold objects only, so they leave the list as soon as an occupant is being added. */
    public readonly areaOptions = computed(() => {
        if (!RACK_OCCUPANT_KINDS.includes(this.selectedKind())) {
            return this.annotatedAreas();
        }

        return this.annotatedAreas().filter(option => !RACK_OCCUPANT_FORBIDDEN_AREAS.includes(option.value));
    });

    /** Free stretches of the chosen area, top down. Empty for an area that carries no slots. */
    private readonly areaRuns = computed(() =>
        freeRuns(this.rows, this.formValue().area, this.rackHeight, this.editedMountId));

    /** The longest unbroken stretch, which is the tallest row the area can still take. */
    public readonly largestRun = computed(() =>
        this.areaRuns().reduce((largest, run) => Math.max(largest, run.size), 0));

    /**
     * Every U of the area as a placement, top down, each labelled with the range the entered height
     * would take from it. The taken ones are listed disabled, so the dropdown also reads as a map of
     * where the area is already occupied.
     */
    public readonly startSlotOptions = computed(() =>
        slotOptions(this.areaRuns(), this.rackHeight, toNumber(this.formValue().height) ?? 1));

    /**
     * A height the area cannot take anywhere. The validators only know the rack's own height, so
     * without this the refusal would come from the backend after the save was attempted.
     */
    public readonly heightNotice = computed(() => {
        if (!this.isSlotArea()) {
            return '';
        }

        const largest = this.largestRun();

        if (largest === 0) {
            return 'This area has no free slots left.';
        }

        const span = toNumber(this.formValue().height);

        return span !== null && span > largest ? `The longest free stretch here is ${largest}U.` : '';
    });

    public readonly isSlotArea = computed(() => RACK_SLOT_AREAS.includes(this.formValue().area));

    /** An unplaced row keeps its height as a hint, so re-placing it can be pre-filled. */
    public readonly showsHeight = computed(() => this.isSlotArea() || this.formValue().area === RackArea.UNASSIGNED);

    public readonly showsPosition = computed(() => !this.isSlotArea());

    public readonly kindLabel = computed(() => RACK_KIND_LABELS[this.selectedKind()]);

    public readonly title = computed(() => `${this.isEditMode ? 'Edit' : 'Add'} ${this.kindLabel().toLowerCase()}`);

    public readonly subtitle = computed(() => (this.rackHeight ? `${this.rackHeight}U rack` : ''));

    /** The object the picker currently holds, so the submit label can say what the write really does. */
    private readonly pickedObject = signal<RackAssignableObject | null>(null);

    /**
     * An object that already sits in another rack is taken out of it, so the write replaces its
     * placement instead of adding a second one. The picker warns about it; the button agrees.
     */
    public readonly replacesOtherRack = computed(() => {
        const picked = this.pickedObject();

        if (!picked?.assigned_rack_id || picked.assigned_rack_id === this.rackId) {
            return false;
        }

        // A kind switch resets the control without telling the picker, so the form has the last word.
        return this.isMount() && this.formValue().objectId === picked.public_id;
    });

    public readonly submitLabel = computed(() => {
        if (this.isEditMode) {
            return 'Save';
        }

        return this.replacesOtherRack() ? 'Replace' : 'Add';
    });

    /**
     * Spells out the slots the current input would take, since the anchor extends downward. Until both
     * values are in it explains the counting direction, and it warns as soon as the span would run off
     * the bottom, which the height-first order makes easy to walk into.
     */
    public readonly slotRange = computed<{ text: string; warn: boolean }>(() => {
        const { startSlot, height } = this.formValue();
        const anchorSlot = toNumber(startSlot);
        const span = toNumber(height);

        if (anchorSlot === null || span === null) {
            return { text: `Slot 1 is the bottom of the rack, slot ${this.rackHeight} the top.`, warn: false };
        }

        const bottomSlot = anchorSlot - span + 1;

        if (bottomSlot < 1) {
            return { text: `${span}U does not fit below slot ${anchorSlot}.`, warn: true };
        }

        // The run has to swallow the whole range, not just the anchor, or the row runs into what is below it.
        const run = runContaining(this.areaRuns(), anchorSlot);

        if (!run || run.from > bottomSlot) {
            return { text: `${slotRangeText(anchorSlot, span)} is already taken.`, warn: true };
        }

        return { text: `Occupies ${slotRangeText(anchorSlot, span)} of ${this.rackHeight}U.`, warn: false };
    });

    /** Only a complete hex is previewed, so a half typed value does not flash a colour. */
    public readonly previewColor = computed(() => {
        const color = this.formValue().color ?? '';

        return HEX_COLOR_PATTERN.test(color) ? color : null;
    });

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.annotatedAreas.set(AREA_OPTIONS.map(option => ({ ...option, label: this.areaLabelWithSpace(option) })));
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
                this.dropOutgrownStartSlot();
                this.validationErrors.set([]);
            });

        // A taller row, or the other face, can invalidate an anchor that was already picked.
        this.form.controls.height.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.dropOutgrownStartSlot());

        // Read-only without the right; silent, so the derived fields keep the values they show.
        if (!this.canEdit) {
            this.form.disable({ emitEvent: false });
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onObjectSelected(picked: RackAssignableObject | null): void {
        this.pickedObject.set(picked ?? null);
        this.validationErrors.set([]);
    }

    /** A different anchor supersedes whatever the last dry run refused, so its summary goes with it. */
    public onStartSlotPicked(): void {
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
            .validateMount(this.rackId, buildValidatePayload(this.form.getRawValue(), this.mount))
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
            : `Pick a slot between 1 and ${this.rackHeight}.`;
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

    /**
     * The summary sits above the fields rather than below them, so a refusal cannot land off the end
     * of a scrolled body. Focusing it is what carries it into view, and `role="alert"` on the same
     * element is what reads the reasons out.
     */
    private showValidationErrors(messages: string[]): void {
        this.validationErrors.set(messages);

        if (!messages.length) {
            return;
        }

        // The element is created by this very change, so the focus waits for the render that adds it.
        afterNextRender(() => this.errorSummary?.nativeElement.focus(), { injector: this.injector });
    }

    /** The row being edited never competes with itself for the slots it already holds. */
    private get editedMountId(): number | null {
        return this.mount?.mount_id ?? null;
    }

    /** Areas that carry slots say what is left in them, so the choice is made knowing where there is room. */
    private areaLabelWithSpace(option: RackAreaOption): string {
        if (!RACK_SLOT_AREAS.includes(option.value) || this.rackHeight < 1) {
            return option.label;
        }

        const { free } = measureArea(this.rows, option.value, this.rackHeight, this.editedMountId);

        return free > 0 ? `${option.label} · ${free}U free` : `${option.label} · full`;
    }

    /**
     * An anchor the row has outgrown is no longer a placement, and the list offers that U only as part
     * of a blocked stretch - so the field would read back a stretch of taken space instead of where the
     * row goes. Dropping it asks for the anchor again rather than holding a value that cannot be saved.
     */
    private dropOutgrownStartSlot(): void {
        const startSlot = this.form.controls.startSlot;
        const picked = toNumber(startSlot.value);

        if (picked === null || startSlot.disabled) {
            return;
        }

        // Read off the controls: a control emits before the form-wide value the derived signals watch.
        const { area, height } = this.form.controls;
        const runs = freeRuns(this.rows, area.value, this.rackHeight, this.editedMountId);

        if (!fitsAt(runs, picked, toNumber(height.value) ?? 1)) {
            startSlot.reset(null);
        }
    }

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
            this.showValidationErrors((validation?.errors ?? []).map(error => error.message));
            return of(null);
        }

        const value = this.form.getRawValue();

        if (this.isEditMode) {
            return this.rackOverviewService.updateMount(
                this.rackId,
                this.mount.mount_id,
                buildUpdatePayload(value, this.mount)
            );
        }

        return this.rackOverviewService.mountObject(this.rackId, buildInsertPayload(value));
    }
}
