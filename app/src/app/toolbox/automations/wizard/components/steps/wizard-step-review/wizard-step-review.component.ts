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
import { Component, EventEmitter, Input, Output } from '@angular/core';

import {
    AutomationDefinition,
    AutomationErrorHandling,
    AutomationField,
    findSystemField,
    hasActiveTransform,
    systemFieldValue
} from '../../../models/automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Step group 5 - the dry run and the activation decision.
 *
 * Covers the concept's "test" and "summary" steps. The test is a preview rather than an execution:
 * it shows what the automation would read and where each value would land, using values from a real
 * object of the chosen type. Actually executing a trial run against the target system would need a
 * backend endpoint and is deliberately out of scope here.
 */
@Component({
    selector: 'app-wizard-step-review',
    templateUrl: './wizard-step-review.component.html',
    styleUrls: ['./wizard-step-review.component.scss'],
    standalone: false
})
export class WizardStepReviewComponent {

    @Input() public definition!: AutomationDefinition;
    @Input() public sourceFields: AutomationField[] = [];
    @Input() public readableDescription = '';
    @Input() public validationErrors: string[] = [];
    @Input() public compileWarnings: string[] = [];

    /** Field values of a real object, keyed by field name. Empty until a sample is loaded. */
    @Input() public sampleValues: Record<string, string> = {};
    @Input() public sampleLoading = false;
    @Input() public sampleObjectId: number | null = null;

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();
    @Output() public loadSample = new EventEmitter<void>();

    public showAdvanced = false;

    public readonly errorHandlingChoices: ReadonlyArray<{ value: AutomationErrorHandling; label: string }> = [
        { value: 'abort', label: 'Stop the run' },
        { value: 'continue', label: 'Skip the item and continue' },
        { value: 'notify', label: 'Continue and send a notification' }
    ];

    /* ---------------------------------------------------- EVENTS ---------------------------------------------------- */

    public onActiveChanged(active: boolean): void {
        this.definition.active = active;
        this.emit();
    }


    public onAdvancedChanged<K extends keyof AutomationDefinition['advanced']>(
        key: K,
        value: AutomationDefinition['advanced'][K]
    ): void {
        this.definition.advanced = { ...this.definition.advanced, [key]: value };
        this.emit();
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    /**
     * The mapped pairs, with a sample value where one is known.
     *
     * A fixed value needs no sample - it is already the value that will be sent, so it is shown
     * directly. Pairs carrying a value adjustment are marked, because their sample is what is read,
     * not what arrives.
     */
    public get preview(): Array<{ source: string; target: string; value: string; adjusted: boolean }> {
        return this.definition.mapping
            .filter(entry => !!entry.target)
            .map(entry => {
                const systemField = findSystemField(entry.source);
                const value = systemField?.kind === 'constant'
                    ? systemFieldValue(systemField, this.definition)
                    : this.sampleValues[entry.source] ?? '';

                return {
                    source: this.sourceFields.find(field => field.name === entry.source)?.label ?? entry.source,
                    target: entry.target,
                    value,
                    adjusted: hasActiveTransform(entry)
                };
            });
    }


    public get hasSample(): boolean {
        return Object.keys(this.sampleValues).length > 0;
    }


    public get canActivate(): boolean {
        return this.validationErrors.length === 0;
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
