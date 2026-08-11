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
import { Component, DoCheck, EventEmitter, Input, Output } from '@angular/core';

import {
    AutomationDefinition,
    AutomationExtraCall,
    requiresMatching
} from '../../../models/automation-definition.model';
import { OcConnection, OcMethod, OcOperator } from '../../../models/opencelium-connection.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One key/value pair of a request, as the table shows it. */
export interface WirePair {
    key: string;
    value: string;

    /** True when the value is read from an earlier call rather than written out. */
    reference: boolean;

    /** True when the field assignment writes this, which is why it cannot be edited here. */
    bound: boolean;

    /** True when this value was entered by hand rather than worked out. */
    changed: boolean;
}

/** One line of the sequence. */
export interface FlowStep {
    id: string;
    index: string;

    /** How deep in the execution tree, which is what the indentation shows. */
    depth: number;
    kind: 'call' | 'loop' | 'if';

    /** What the step is for, in the wizard's words. */
    title: string;

    /** The operation or the condition, in the target system's words. */
    detail: string;
    system: string;
    method?: OcMethod;
    expression?: string;
}

/**
 * Step group 3 - what happens in the target system, as the calls that will actually be made.
 *
 * Built from the compiled connection rather than described alongside it. Anything else would be a
 * second account of the same thing, free to drift from the first - and the whole reason this screen
 * exists is to be able to check what the assistant decided.
 *
 * Reading from and writing to DataGerry is left out: it follows from the object type and its fields,
 * so showing it would add a step nobody can act on and bury the ones that matter.
 */
@Component({
    selector: 'app-wizard-step-flow',
    templateUrl: './wizard-step-flow.component.html',
    styleUrls: ['./wizard-step-flow.component.scss'],
    standalone: false
})
export class WizardStepFlowComponent implements DoCheck {

    @Input() public definition!: AutomationDefinition;

    /** Null while the definition does not compile, which is what the step then says. */
    @Input() public connection: OcConnection | null = null;

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();

    /** Operations the target system offers, for a call the user wants to add. */
    @Input() public targetOperations: string[] = [];

    public steps: FlowStep[] = [];
    public openStep = '';

    /** The step a new call is being placed after, or '' while nobody is adding one. */
    public adding = '';

    private seenConnection: OcConnection | null = null;

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    public ngDoCheck(): void {
        if (this.connection === this.seenConnection) {
            return;
        }

        this.seenConnection = this.connection;
        this.steps = this.buildSteps();

        // A step that no longer exists must not stay open on a row that is now something else.
        if (!this.steps.some(step => step.id === this.openStep)) {
            this.openStep = '';
        }
    }


    /**
     * The compiled calls and operators as one sequence.
     *
     * Order and nesting both come from the execution index - '1_2_0' runs inside '1_2', which runs
     * inside '1' - so the sequence shown is the sequence the engine walks.
     */
    private buildSteps(): FlowStep[] {
        if (!this.connection) {
            return [];
        }

        const source = this.connection.fromConnector.methods[0];
        const entries: FlowStep[] = [];

        for (const method of this.connection.fromConnector.methods) {
            // The read on DataGerry's side is the one call the assistant owns entirely.
            if (method === source && this.definition.direction === 'outgoing') {
                continue;
            }

            entries.push({
                id: method.id,
                index: method.index,
                depth: depthOf(method.index),
                kind: 'call',
                title: this.titleOf(method),
                detail: method.name,
                system: method.connector?.title ?? '',
                method
            });
        }

        for (const operator of this.connection.fromConnector.operators) {
            if (operator.type === 'loop') {
                continue;
            }

            entries.push({
                id: operator.id,
                index: operator.index,
                depth: depthOf(operator.index),
                kind: 'if',
                title: this.titleOfOperator(operator),
                detail: 'branch',
                system: '',
                expression: operator.expression
            });
        }

        return entries.sort((left, right) => compareIndex(left.index, right.index));
    }


    /** What a call is for, said in the terms the wizard uses rather than the operation's name. */
    private titleOf(method: OcMethod): string {
        const system = method.connector?.title ?? 'the target system';
        const name = method.name.toLowerCase();

        if (this.isLookup(method)) {
            return `Look the object up in ${system}`;
        }

        if (name.includes('create') || name.includes('add')) {
            return `Create it in ${system}`;
        }

        if (name.includes('update') || name.includes('save')) {
            return `Update it in ${system}`;
        }

        if (name.includes('delete') || name.includes('remove')) {
            return `Delete it in ${system}`;
        }

        return `Call ${system}`;
    }


    private titleOfOperator(operator: OcOperator): string {
        if (operator.expression.includes('IsEmpty')) {
            return 'If it is not there';
        }

        if (operator.expression.includes('NotEmpty')) {
            return 'If it is already there';
        }

        return 'Only for objects that match';
    }


    /** The lookup is the read that runs inside the loop before anything is written. */
    private isLookup(method: OcMethod): boolean {
        return method.index.split('_').length === 2 && method.request?.method !== undefined
            && this.connection?.fromConnector.operators.some(operator => operator.type === 'if') === true
            && method === this.connection?.fromConnector.methods.find(
                candidate => candidate.index.split('_').length === 2
            );
    }

    /* ----------------------------------------------------- DETAIL --------------------------------------------------- */

    public toggle(step: FlowStep): void {
        this.openStep = this.openStep === step.id ? '' : step.id;
    }


    public headersOf(step: FlowStep): WirePair[] {
        return pairsOf(step.method?.request?.header ?? {})
            .map(pair => this.decorate(step, pair, 'headers'));
    }


    /** The request body flattened to one row per value, so a reference is visible at a glance. */
    public bodyOf(step: FlowStep): WirePair[] {
        const bound = new Set(
            (this.connection?.fieldBinding ?? [])
                .filter(binding => binding.to[0].color === step.method?.color)
                .map(binding => binding.to[0].field.replace('body.$.', ''))
        );

        return pairsOf(step.method?.request?.body?.fields ?? {})
            .map(pair => ({ ...this.decorate(step, pair, 'body'), bound: bound.has(pair.key) }));
    }


    /** Marks a value as bound or hand-entered, which is what decides whether it can be edited. */
    private decorate(step: FlowStep, pair: WirePair, part: 'headers' | 'body'): WirePair {
        return {
            ...pair,
            changed: this.definition.overrides[step.index]?.[part]?.[pair.key] !== undefined
        };
    }

    /* ----------------------------------------------------- EDITING -------------------------------------------------- */

    /**
     * Records a value entered by hand.
     *
     * Kept as a correction to the call rather than written into the call, because the call itself is
     * rebuilt from the definition on every change - anything written into it directly would vanish
     * on the next keystroke elsewhere.
     */
    public onEdit(step: FlowStep, part: 'headers' | 'body', key: string, value: string): void {
        const current = this.definition.overrides[step.index] ?? {};
        const section = { ...(current[part] ?? {}), [key]: value };

        this.definition.overrides = {
            ...this.definition.overrides,
            [step.index]: { ...current, [part]: section }
        };
        this.definitionChange.emit(this.definition);
    }


    public onEditEndpoint(step: FlowStep, endpoint: string): void {
        this.definition.overrides = {
            ...this.definition.overrides,
            [step.index]: { ...(this.definition.overrides[step.index] ?? {}), endpoint }
        };
        this.definitionChange.emit(this.definition);
    }


    /** Puts a call back the way the assistant built it. */
    public onResetCall(step: FlowStep): void {
        const { [step.index]: _dropped, ...rest } = this.definition.overrides;

        this.definition.overrides = rest;
        this.definitionChange.emit(this.definition);
    }


    public isChanged(step: FlowStep): boolean {
        return !!this.definition.overrides[step.index];
    }


    /* ------------------------------------------------- ADDED CALLS -------------------------------------------------- */

    public startAdding(step: FlowStep): void {
        this.adding = this.adding === step.index ? '' : step.index;
    }


    /**
     * Puts a call of the user's own after a step.
     *
     * Placed by the step it follows rather than by an index, so a branch inserted above it later
     * does not move it somewhere it was never meant to run.
     */
    public onAddCall(after: string, operation: string): void {
        if (!operation) {
            return;
        }

        const extra: AutomationExtraCall = {
            id: `extra-${after}-${this.definition.extras.length + 1}`,
            after,
            operation
        };

        this.definition.extras = [...this.definition.extras, extra];
        this.adding = '';
        this.definitionChange.emit(this.definition);
    }


    public onRemoveCall(step: FlowStep): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        const { [step.index]: _dropped, ...overrides } = this.definition.overrides;

        this.definition.extras = this.definition.extras.filter(candidate => candidate.id !== extra.id);
        this.definition.overrides = overrides;
        this.definitionChange.emit(this.definition);
    }


    /** Whether the call was added by hand, which is what may be removed and re-pointed. */
    public isAdded(step: FlowStep): boolean {
        return !!this.extraFor(step);
    }


    /**
     * Hands an added call the identifier of the object the step before it touched.
     *
     * The reason such a call exists at all: it belongs to an object that has only just been created
     * or found, so until the call before it ran, that object had no id to name.
     */
    public onUseParentId(step: FlowStep, path: string): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        this.definition.extras = this.definition.extras.map(candidate =>
            candidate.id === extra.id ? { ...candidate, parentIdPath: path || undefined } : candidate
        );
        this.definitionChange.emit(this.definition);
    }


    public parentIdPathOf(step: FlowStep): string {
        return this.extraFor(step)?.parentIdPath ?? '';
    }


    /** Body paths of an added call, offered as the place its parent's identifier can go. */
    public idCandidatesOf(step: FlowStep): string[] {
        return this.bodyOf(step)
            .filter(pair => !pair.reference)
            .map(pair => pair.key);
    }


    private extraFor(step: FlowStep): AutomationExtraCall | undefined {
        // An added call keeps no index of its own, so it is found by where it was placed.
        return this.definition.extras.find(extra => this.indexOfExtra(extra) === step.index);
    }


    /**
     * Where an added call ended up.
     *
     * The compiler numbers them after the skeleton, in the order they were added, beside the step
     * they follow - repeating that here is what lets a row be traced back to its entry.
     */
    private indexOfExtra(extra: AutomationExtraCall): string {
        const siblings = this.definition.extras.filter(candidate => candidate.after === extra.after);
        const position = siblings.indexOf(extra);
        const parts = extra.after.split('_');
        const parent = parts.slice(0, -1).join('_');
        const base = Number(parts[parts.length - 1]) + 1 + position;

        return parent ? `${parent}_${base}` : String(base);
    }


    public endpointOf(step: FlowStep): string {
        return this.definition.overrides[step.index]?.endpoint ?? this.urlOf(step);
    }


    public urlOf(step: FlowStep): string {
        return step.method?.request?.endpoint ?? '';
    }


    public verbOf(step: FlowStep): string {
        return step.method?.request?.method ?? '';
    }


    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public get systemName(): string {
        return this.definition.target.connectorTitle || 'the target system';
    }


    public get needsIdentifier(): boolean {
        return requiresMatching(this.definition) && !this.definition.matching.identifyBy;
    }
}


/** How deep an execution index sits: '1_2_0' is two levels inside '1'. */
function depthOf(index: string): number {
    return Math.max(0, index.split('_').length - 2);
}


/** Orders execution indices the way the engine walks them, segment by segment. */
function compareIndex(left: string, right: string): number {
    const a = left.split('_').map(Number);
    const b = right.split('_').map(Number);

    for (let i = 0; i < Math.max(a.length, b.length); i++) {
        const difference = (a[i] ?? -1) - (b[i] ?? -1);

        if (difference !== 0) {
            return difference;
        }
    }

    return 0;
}


/** Flattens a request tree to dotted paths, which is how the mapping names them too. */
function pairsOf(node: unknown, prefix = ''): WirePair[] {
    if (node === null || node === undefined) {
        return [];
    }

    if (typeof node !== 'object') {
        const value = String(node);

        return [{ key: prefix, value, reference: value.startsWith('#'), bound: false, changed: false }];
    }

    if (Array.isArray(node)) {
        return node.flatMap((item, index) => pairsOf(item, `${prefix}[${index}]`));
    }

    return Object.entries(node as Record<string, unknown>)
        .flatMap(([key, value]) => pairsOf(value, prefix ? `${prefix}.${key}` : key));
}
