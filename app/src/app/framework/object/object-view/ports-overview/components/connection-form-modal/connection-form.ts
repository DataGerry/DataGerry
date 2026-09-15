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
import { AbstractControl, FormControl, FormGroup, Validators } from '@angular/forms';

import {
    CABLE_TEXT_MAX_LENGTH,
    CableInfoPayload,
    CableManagementMode,
    CableMetadataPayload,
    CableSource,
    CmdbPortConnection,
    ConnectionType,
    PortConnectionPayload
} from '../../models/port-connection.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The controls a validation message can be asked for. */
export type CableTextControl = 'cableName' | 'cableLength' | 'cableColor' | 'cableDescription';

/** Every control of the form. */
export type ConnectionFormControl = CableTextControl | 'farEndPortId' | 'cableType' | 'managementMode' | 'cableCiId';

/** The form group itself, for the template that binds it. */
export type ConnectionFormGroup = ConnectionForm['group'];

/**
 * The questions the wizard asks, in the order it asks them.
 *
 * CABLE is conditional: how the cable is managed decides whether it is asked at all, which is why
 * the steps are named rather than numbered - a position would move as the step appears and goes.
 */
export enum ConnectionStep {
    ENDPOINTS = 'ENDPOINTS',
    MANAGEMENT = 'MANAGEMENT',
    CABLE = 'CABLE',
    REVIEW = 'REVIEW'
}

/** Which fields each step owns, so a step is validated on its own. */
const STEP_CONTROLS: Record<ConnectionStep, readonly ConnectionFormControl[]> = {
    [ConnectionStep.ENDPOINTS]: ['farEndPortId'],
    [ConnectionStep.MANAGEMENT]: ['managementMode', 'cableCiId'],
    [ConnectionStep.CABLE]: ['cableName', 'cableType', 'cableLength', 'cableColor', 'cableDescription'],
    [ConnectionStep.REVIEW]: []
};


/**
 * The connection form: its controls, the rule that depends on how the cable is managed, and the
 * request bodies built from it. Holds no server state, so it can be reasoned about on its own.
 */
export class ConnectionForm {

    public readonly group = new FormGroup({
        farEndPortId: new FormControl<number | null>(null, [Validators.required]),
        cableName: new FormControl<string>('', [Validators.maxLength(CABLE_TEXT_MAX_LENGTH)]),
        cableType: new FormControl<string | null>(null),
        cableLength: new FormControl<string>('', [Validators.maxLength(CABLE_TEXT_MAX_LENGTH)]),
        cableColor: new FormControl<string>('', [Validators.maxLength(CABLE_TEXT_MAX_LENGTH)]),
        cableDescription: new FormControl<string>('', [Validators.maxLength(CABLE_TEXT_MAX_LENGTH)]),
        managementMode: new FormControl<CableManagementMode>(CableManagementMode.METADATA),
        cableCiId: new FormControl<number | null>(null)
    });

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get managementMode(): CableManagementMode {
        return this.group.controls.managementMode.value ?? CableManagementMode.METADATA;
    }


    public get linksCableCi(): boolean {
        return this.managementMode === CableManagementMode.CABLE_CI;
    }


    /**
     * Puts the form into edit mode.
     *
     * What a connection joins is immutable - a re-cable is a delete plus a create - so the far end is
     * taken out of the form rather than shown as a field the user cannot change anything with.
     */
    public lockEndpoints(): void {
        const farEndPortId = this.group.controls.farEndPortId;

        farEndPortId.clearValidators();
        farEndPortId.updateValueAndValidity({ emitEvent: false });
    }


    /** Picks how the cable is managed and re-applies the rule that depends on it. */
    public selectManagementMode(mode: CableManagementMode): void {
        const cableCiId = this.group.controls.cableCiId;

        this.group.controls.managementMode.setValue(mode);

        if (mode === CableManagementMode.CABLE_CI) {
            cableCiId.setValidators([Validators.required]);
            // The metadata is not sent in this mode, so a leftover answer would only mislead the review.
            this.clearCableMetadata();
        } else {
            // Metadata mode must not keep a stale reference: an omitted key unsets the stored one.
            cableCiId.clearValidators();
            cableCiId.setValue(null);
        }

        cableCiId.updateValueAndValidity();
    }


    /**
     * Fills the form from a stored connection.
     *
     * The mode comes from the cable's own `source` rather than from the presence of a CI id, and it is
     * applied first: it clears the metadata on the way into CI mode, so the values are prefilled
     * afterwards and are still there should the user switch back to describing the cable here.
     *
     * `type_id` is what the select binds to, and a linked CI has none - it stores the label. Switching
     * such a connection to inline therefore starts with an empty cable type, which is honest: there is
     * no option to preselect.
     */
    public prefill(connection: CmdbPortConnection): void {
        const cable = connection.cable;

        this.selectManagementMode(
            cable?.source === CableSource.CI ? CableManagementMode.CABLE_CI : CableManagementMode.METADATA
        );

        this.group.patchValue({
            cableName: cable?.name ?? '',
            cableType: cable?.type_id == null ? null : String(cable.type_id),
            cableLength: cable?.length ?? '',
            cableColor: cable?.color ?? '',
            cableDescription: cable?.description ?? '',
            cableCiId: cable?.cable_ci_id ?? null
        });
    }


    /** A message is only worth showing once the user has left the field. */
    public errorOf(controlName: CableTextControl): string {
        const control = this.group.controls[controlName];

        return control.touched && control.hasError('maxlength') ? 'This value is too long.' : '';
    }


    /**
     * The two required answers live in child pickers rather than in a plain field, so neither can
     * raise its own message - the form hands them one to render.
     */
    public get farEndError(): string {
        return this.isRefused('farEndPortId') ? 'Choose the port this cable runs to.' : '';
    }


    public get cableCiError(): string {
        return this.isRefused('cableCiId') ? 'Choose the cable to link, or describe it as metadata instead.' : '';
    }


    /**
     * The steps this answer set actually goes through.
     *
     * Linking a CI drops the cable step: the CI carries the same five fields, so asking for them
     * again would only be a second place to keep them.
     */
    public activeSteps(): ConnectionStep[] {
        if (this.linksCableCi) {
            return [ConnectionStep.ENDPOINTS, ConnectionStep.MANAGEMENT, ConnectionStep.REVIEW];
        }

        return [
            ConnectionStep.ENDPOINTS,
            ConnectionStep.MANAGEMENT,
            ConnectionStep.CABLE,
            ConnectionStep.REVIEW
        ];
    }


    public isStepValid(step: ConnectionStep): boolean {
        return this.controlsOfStep(step).every((control) => control.valid);
    }


    public markStepTouched(step: ConnectionStep): void {
        this.controlsOfStep(step).forEach((control) => control.markAsTouched());
    }


    /** Body of the create: what is joined, plus the cable that joins it. */
    public toCreatePayload(nearEndPortId: number): PortConnectionPayload {
        return {
            endpoints: [nearEndPortId, this.group.controls.farEndPortId.value],
            connection_type: ConnectionType.CABLE,
            ...this.toCableInfo()
        };
    }


    /**
     * Body of the update, which replaces the cable information as a whole.
     *
     * Exactly one of the two shapes: a linked CI is sent as the reference alone, because the CI
     * carries the same five fields and the server takes the cable's values from it. Sending both
     * would store the answer twice with no rule for which one wins.
     */
    public toCableInfo(): CableInfoPayload {
        const cableCiId = this.group.controls.cableCiId.value;

        if (this.linksCableCi && cableCiId != null) {
            return { cable_ci_id: cableCiId };
        }

        return this.cableMetadata();
    }


    /** The five values as the user typed them, which the review step lists and the write sends. */
    public cableMetadata(): CableMetadataPayload {
        return {
            cable_name: this.trimmed('cableName') || null,
            cable_type: this.asNumber(this.group.controls.cableType.value),
            cable_length: this.trimmed('cableLength') || null,
            cable_color: this.trimmed('cableColor') || null,
            cable_description: this.trimmed('cableDescription') || null
        };
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private clearCableMetadata(): void {
        this.group.patchValue({
            cableName: '',
            cableType: null,
            cableLength: '',
            cableColor: '',
            cableDescription: ''
        });
    }


    private controlsOfStep(step: ConnectionStep): AbstractControl[] {
        return (STEP_CONTROLS[step] ?? []).map((name) => this.group.controls[name]);
    }


    private isRefused(controlName: 'farEndPortId' | 'cableCiId'): boolean {
        const control = this.group.controls[controlName];

        return control.touched && control.invalid;
    }


    private trimmed(controlName: CableTextControl): string {
        return (this.group.controls[controlName].value ?? '').toString().trim();
    }


    private asNumber(value: string | null): number | null {
        return value === null || value === '' ? null : Number(value);
    }
}
