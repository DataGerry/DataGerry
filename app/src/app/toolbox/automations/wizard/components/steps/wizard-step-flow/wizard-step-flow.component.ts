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
import { Component, Input } from '@angular/core';

import {
    AutomationDefinition,
    AutomationMatchOutcome,
    outcomeWrites,
    requiresMatching
} from '../../../models/automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One line of the sequence as it is shown. */
export interface FlowStep {
    kind: 'call' | 'branch';
    title: string;

    /** The operation, or the condition for a branch. */
    detail: string;

    /** What the step does with the data, short enough to sit at the end of the line. */
    note: string;

    /** True for the steps that run inside a branch, which are drawn set back. */
    nested: boolean;
}

/**
 * Step group 3 - what happens in the target system.
 *
 * Only the target system's calls appear here. Reading from and writing to DataGerry is built from
 * the object type and its fields, so putting it in the sequence would add a step nobody can change
 * and bury the two or three that matter.
 *
 * Derived rather than stored, and read-only for now: the sequence follows from the action and the
 * matching, both chosen on the previous step. Editing it by hand is what this screen grows next.
 */
@Component({
    selector: 'app-wizard-step-flow',
    templateUrl: './wizard-step-flow.component.html',
    styleUrls: ['./wizard-step-flow.component.scss'],
    standalone: false
})
export class WizardStepFlowComponent {

    @Input() public definition!: AutomationDefinition;

    public get systemName(): string {
        return this.definition.target.connectorTitle || 'the target system';
    }


    /** Mirrors what the compiler builds, so the two can be checked against each other. */
    public get steps(): FlowStep[] {
        if (!this.definition.target.connectorId) {
            return [];
        }

        if (!requiresMatching(this.definition) || !this.definition.matching.identifyBy) {
            return [{
                kind: 'call',
                title: `${this.titleFor(this.definition.target.operation)}`,
                detail: this.definition.target.operation,
                note: 'for every object of the type',
                nested: false
            }];
        }

        const steps: FlowStep[] = [{
            kind: 'call',
            title: `Look the object up in ${this.systemName}`,
            detail: 'read, filtered',
            note: `by ${this.identifyingLabel}`,
            nested: false
        }];

        for (const branch of this.branches) {
            steps.push({ kind: 'branch', title: branch.when, detail: branch.condition, note: '', nested: false });
            steps.push({
                kind: 'call',
                title: branch.title,
                detail: branch.outcome,
                note: branch.note,
                nested: true
            });
        }

        return steps;
    }


    /** The branches that actually write, in the order the compiler lays them out. */
    private get branches(): Array<{
        when: string; condition: string; title: string; outcome: string; note: string;
    }> {
        const { whenMissing, whenPresent } = this.definition.matching;
        const branches: Array<{
            when: string; condition: string; title: string; outcome: string; note: string;
        }> = [];

        if (outcomeWrites(whenMissing)) {
            branches.push({
                when: 'If it is not there',
                condition: 'the lookup found nothing',
                title: this.titleFor(whenMissing),
                outcome: whenMissing,
                note: ''
            });
        }

        if (outcomeWrites(whenPresent)) {
            branches.push({
                when: 'If it is already there',
                condition: 'the lookup found something',
                title: this.titleFor(whenPresent),
                outcome: whenPresent,
                note: 'with the identifier that was found'
            });
        }

        return branches;
    }


    private titleFor(outcome: AutomationMatchOutcome): string {
        return {
            create: `Create it in ${this.systemName}`,
            update: `Update it in ${this.systemName}`,
            delete: `Delete it in ${this.systemName}`,
            skip: 'Leave it alone',
            error: 'Report it as an error'
        }[outcome];
    }


    public get identifyingLabel(): string {
        const field = this.definition.matching.identifyBy;

        return this.definition.fields.find(candidate => candidate.name === field)?.label || field;
    }


    public get needsIdentifier(): boolean {
        return requiresMatching(this.definition) && !this.definition.matching.identifyBy;
    }
}
