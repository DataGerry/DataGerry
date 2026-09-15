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
import { AbstractControl, FormControl, FormGroup, ValidationErrors, Validators } from '@angular/forms';

import { PortBulkRequest, PortDeviceKind, PortNamingRequest } from '../../models/port-bulk.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const MAX_TEXT_LENGTH = 255;

/** Which fields each step owns, so a step is validated on its own. */
const STEP_CONTROLS: readonly (readonly PortWizardControl[])[] = [
    ['deviceKind'],
    ['syntax', 'rearSyntax', 'prefix', 'slot'],
    ['count', 'startIndex', 'description'],
    []
];

/** Step 1 names a second face on a patch panel only. */
const PANEL_ONLY_CONTROLS: readonly PortWizardControl[] = ['rearSyntax'];

/** Every control of the wizard form. */
export type PortWizardControl =
    'deviceKind' | 'syntax' | 'rearSyntax' | 'prefix' | 'slot'
    | 'count' | 'startIndex' | 'status' | 'portType' | 'speed' | 'description';

/** The controls a message can be asked for. */
export type PortWizardTextControl = 'syntax' | 'rearSyntax' | 'count' | 'startIndex' | 'description';

/** The form group itself, for the template that binds it. */
export type PortWizardFormGroup = PortCreateWizardForm['group'];


/** A syntax of spaces alone is refused by the backend, so it does not count as one here either. */
function nonBlank(control: AbstractControl): ValidationErrors | null {
    return (control.value ?? '').trim() ? null : { required: true };
}


/** The same syntax on both faces would put identical names on the front and the rear. */
function differentFromFrontSyntax(control: AbstractControl): ValidationErrors | null {
    const frontSyntax = (control.parent?.get('syntax')?.value ?? '').trim();
    const rearSyntax = (control.value ?? '').trim();

    return frontSyntax && frontSyntax === rearSyntax ? { sameSyntax: true } : null;
}


/**
 * The wizard's form: its controls, the rules that depend on the device kind, and the request bodies
 * built from it. Holds no server state, so it can be reasoned about on its own.
 */
export class PortCreateWizardForm {

    public readonly group = new FormGroup({
        deviceKind: new FormControl<PortDeviceKind | null>(null, [Validators.required]),
        syntax: new FormControl<string>('', [nonBlank, Validators.maxLength(MAX_TEXT_LENGTH)]),
        rearSyntax: new FormControl<string>('', [Validators.maxLength(MAX_TEXT_LENGTH)]),
        prefix: new FormControl<string>('', [Validators.maxLength(MAX_TEXT_LENGTH)]),
        slot: new FormControl<string>('', [Validators.maxLength(MAX_TEXT_LENGTH)]),
        count: new FormControl<string>('24', [nonBlank, Validators.pattern(/^\d+$/), Validators.min(1)]),
        startIndex: new FormControl<string>('1', [nonBlank, Validators.pattern(/^\d+$/)]),
        status: new FormControl<string | null>(null),
        portType: new FormControl<string | null>(null),
        speed: new FormControl<string | null>(null),
        description: new FormControl<string>('', [Validators.maxLength(MAX_TEXT_LENGTH)])
    });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get deviceKind(): PortDeviceKind | null {
        return this.group.controls.deviceKind.value;
    }


    public get isPatchPanel(): boolean {
        return this.deviceKind === PortDeviceKind.PATCH_PANEL;
    }


    /** Picks the device kind and re-applies the rules that depend on it. */
    public selectDeviceKind(kind: PortDeviceKind): void {
        this.group.controls.deviceKind.setValue(kind);

        const rearSyntax = this.group.controls.rearSyntax;

        if (kind === PortDeviceKind.PATCH_PANEL) {
            rearSyntax.setValidators([nonBlank, differentFromFrontSyntax, Validators.maxLength(MAX_TEXT_LENGTH)]);
        } else {
            rearSyntax.setValidators([Validators.maxLength(MAX_TEXT_LENGTH)]);
            rearSyntax.setValue('');
        }

        rearSyntax.updateValueAndValidity();
    }


    /** The rear name is judged against the front one, so it is re-checked when that changes. */
    public revalidateRearSyntax(): void {
        this.group.controls.rearSyntax.updateValueAndValidity({ emitEvent: false });
    }


    public isStepValid(stepIndex: number): boolean {
        return this.controlsOfStep(stepIndex).every((control) => control.valid);
    }


    public markStepTouched(stepIndex: number): void {
        this.controlsOfStep(stepIndex).forEach((control) => control.markAsTouched());
    }


    /** A message is only worth showing once the user has left the field. */
    public errorOf(controlName: PortWizardTextControl): string {
        const control = this.group.controls[controlName];

        if (!control.touched || control.valid) {
            return '';
        }

        if (control.hasError('required')) {
            return controlName === 'rearSyntax'
                ? 'A patch panel needs a name for its rear side as well.'
                : 'Please fill this in.';
        }

        if (control.hasError('sameSyntax')) {
            return 'The rear side needs a different name from the front, e.g. -R instead of -F.';
        }

        if (control.hasError('pattern') || control.hasError('min')) {
            return controlName === 'count'
                ? 'Please enter a whole number of at least 1.'
                : 'Please enter a whole number, 0 or higher.';
        }

        return 'This value is too long.';
    }


    /** The naming half of the body, which the preview and the creation share. */
    public toNamingRequest(kind: PortDeviceKind): PortNamingRequest {
        const request: PortNamingRequest = {
            device_kind: kind,
            syntax: this.trimmed('syntax'),
            count: Number(this.trimmed('count')),
            start_index: Number(this.trimmed('startIndex'))
        };

        if (kind === PortDeviceKind.PATCH_PANEL) {
            request.rear_syntax = this.trimmed('rearSyntax');
        }

        // Both are optional token values; an empty one is left out instead of sent as ''.
        const prefix = this.trimmed('prefix');
        const slot = this.trimmed('slot');

        if (prefix) {
            request.prefix = prefix;
        }

        if (slot) {
            request.slot = slot;
        }

        return request;
    }


    /** The creation additionally carries the values every generated port is given. */
    public toBulkRequest(kind: PortDeviceKind): PortBulkRequest {
        return {
            ...this.toNamingRequest(kind),
            status: this.asNumber(this.group.controls.status.value),
            port_type: this.asNumber(this.group.controls.portType.value),
            speed: this.asNumber(this.group.controls.speed.value),
            description: this.trimmed('description') || null
        };
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A panel-only field is not part of a standard device's step. */
    private controlsOfStep(stepIndex: number): AbstractControl[] {
        return (STEP_CONTROLS[stepIndex] ?? [])
            .filter((name) => this.isPatchPanel || !PANEL_ONLY_CONTROLS.includes(name))
            .map((name) => this.group.controls[name]);
    }


    private trimmed(controlName: PortWizardControl): string {
        return (this.group.controls[controlName].value ?? '').toString().trim();
    }


    private asNumber(value: string | null): number | null {
        return value === null || value === '' ? null : Number(value);
    }
}
