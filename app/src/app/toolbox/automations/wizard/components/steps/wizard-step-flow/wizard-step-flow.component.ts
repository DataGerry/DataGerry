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
    AutomationCallCondition,
    AutomationCallOverride,
    AutomationDefinition,
    AutomationExtraCall,
    AutomationField,
    requiresMatching
} from '../../../models/automation-definition.model';
import {
    OcConnection,
    OcMethod,
    OcOperator,
    ocFieldReference,
    ocIfNodeId,
    ocMethodNodeId,
    ocSystemNodeId,
    OC_FREE_REQUEST,
    OC_LOOP_ITERATOR
} from '../../../models/opencelium-connection.model';
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

/**
 * A value an earlier step has, and the reference that fetches it.
 *
 * Everything a call can be given beyond a typed-in literal: what the steps before it answered, and
 * the DataGerry fields, which are that same answer under the names the user knows them by.
 */
export interface ValueSource {
    group: string;
    label: string;
    reference: string;
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

    /** Which stage of adding a step is open: the kinds, the operations, a condition, or nothing. */
    public adding: '' | 'kind' | 'operation' | 'condition' = '';

    /** The condition being built, and the entry it belongs to while one is being changed. */
    public condition: AutomationCallCondition = { left: '', operator: '=', right: '' };
    public editing = '';

    /**
     * The comparisons offered, in the engine's own vocabulary.
     *
     * A subset of what it knows: the ones whose meaning is the same to a person as to the parser.
     * The operator itself is what the expression carries, so what is chosen here is what runs.
     */
    public readonly operators: ReadonlyArray<{ value: string; label: string; unary?: boolean }> = [
        { value: '=', label: 'is' },
        { value: '!=', label: 'is not' },
        { value: 'Like', label: 'matches (% stands for anything)' },
        { value: 'NotLike', label: 'does not match' },
        { value: '>', label: 'is greater than' },
        { value: '<', label: 'is less than' },
        { value: '>=', label: 'is at least' },
        { value: '<=', label: 'is at most' },
        { value: 'NotNull', label: 'has a value', unary: true },
        { value: 'IsNull', label: 'has no value', unary: true },
        { value: 'NotEmpty', label: 'is a list with entries', unary: true },
        { value: 'IsEmpty', label: 'is an empty list', unary: true }
    ];

    /**
     * What a step can be.
     *
     * A loop is still missing: it would have to name the list it walks and give its iterator a name
     * the steps inside it can use, and nothing in the sequence says which of an answer's lists is
     * the one meant.
     */
    public readonly kinds: ReadonlyArray<{
        key: 'operation' | 'http' | 'if' | 'loop';
        title: string;
        what: string;
        icon: string;
        available: boolean;
        why?: string;
    }> = [
        {
            key: 'operation',
            title: 'Call a system that is described',
            what: 'Pick an operation of the target system. Headers and body are filled in from its '
                + 'interface description, and its answer can be read by later steps.',
            icon: 'fas fa-diagram-project',
            available: true
        },
        {
            key: 'http',
            title: 'Free HTTP request',
            what: 'Give the method, address, headers and body yourself. For an endpoint no interface '
                + 'description covers - it brings no response shape, so nothing can read a value '
                + 'back out of it.',
            icon: 'fas fa-arrow-up-right-from-square',
            available: true
        },
        {
            key: 'if',
            title: 'Condition',
            what: 'Compares a value from a step that has already run. Everything placed after it '
                + 'runs only when it holds.',
            icon: 'fas fa-code-branch',
            available: true
        },
        {
            key: 'loop',
            title: 'Loop',
            what: 'Repeats the steps inside it, once per entry of a list from an earlier answer.',
            icon: 'fas fa-rotate',
            available: false,
            why: 'Needs the same nesting, plus a way to name the list it walks.'
        }
    ];

    /** Filters the operation list, which is long enough on a real invoker to need it. */
    public operationFilter = '';

    /**
     * The DataGerry fields of the chosen object type, in the order the type declares them.
     *
     * That order is the address: DataGerry answers with `fields: [{ name, value }, ...]` in it, so
     * the third field of the type is `fields[2].value` in the answer and nothing in the payload
     * says which field that is. The names come from here so a reference can be offered by label.
     */
    @Input() public dataGerryFields: AutomationField[] = [];

    /** The selected call's request, a row per value, cached against the template asking for it. */
    public headerRows: WirePair[] = [];
    public bodyRows: WirePair[] = [];

    /** What the selected step could read, grouped by the step that answers it. */
    public valueSources: ValueSource[] = [];

    /** Which value the picker is currently filling in, and what it is being filtered by. */
    public picking: { part: 'headers' | 'body' | 'endpoint'; key: string } | null = null;
    public pickFilter = '';

    /** The pair being added, kept apart from the saved ones until it has a name. */
    public draft: Record<'headers' | 'body', { key: string; value: string }> = {
        headers: { key: '', value: '' },
        body: { key: '', value: '' }
    };

    private seenConnection: OcConnection | null = null;
    private seenStep = '';

    /** Which node a just-added step becomes, so the detail pane opens on it rather than on nothing. */
    private awaiting = '';

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    public ngDoCheck(): void {
        if (this.connection !== this.seenConnection) {
            this.seenConnection = this.connection;
            this.steps = this.buildSteps();

            // A call just added is what the user wants to see; a row that no longer exists must not
            // stay selected on one that is now something else.
            const added = this.awaiting && this.steps.find(step => step.id === this.awaiting);

            if (added) {
                this.openStep = added.id;
                this.awaiting = '';
            } else if (!this.steps.some(step => step.id === this.openStep)) {
                this.openStep = this.steps[0]?.id ?? '';
            }

            this.seenStep = '';
        }

        if (this.openStep === this.seenStep) {
            return;
        }

        // Rebuilt here rather than read out of the template: every one of these walks the whole
        // connection and hands back a new array, and a template that asks on each pass would keep
        // finding a different one and never settle.
        this.seenStep = this.openStep;

        const step = this.selected;

        this.draft = { headers: { key: '', value: '' }, body: { key: '', value: '' } };
        this.picking = null;
        this.headerRows = step ? this.headersOf(step) : [];
        this.bodyRows = step ? this.bodyOf(step) : [];
        this.valueSources = this.buildValueSources(step);
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
                detail: summarize(operator.expression),
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
        if (operator.id.startsWith('if-extra-')) {
            return 'Only when it holds';
        }

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

    public select(step: FlowStep): void {
        this.openStep = step.id;
        this.adding = '';
    }


    public isSelected(step: FlowStep): boolean {
        return this.selected?.id === step.id;
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
        return { ...pair, changed: this.valuesOf(step)[part]?.[pair.key] !== undefined };
    }

    /* ----------------------------------------------------- EDITING -------------------------------------------------- */

    /**
     * Records a value entered by hand.
     *
     * Kept beside the call rather than written into it, because the call itself is rebuilt from the
     * definition on every change - anything written into it directly would vanish on the next
     * keystroke elsewhere. Where "beside" is depends on the call: one the user added is defined by
     * its entry in the sequence, one the assistant built is corrected by its position.
     */
    public onEdit(step: FlowStep, part: 'headers' | 'body', key: string, value: string): void {
        const current = this.valuesOf(step);

        this.writeValues(step, { ...current, [part]: { ...(current[part] ?? {}), [key]: value } });
    }


    /** Adds a value the call did not have: a header of its own, or a field in its body. */
    public onAddPair(step: FlowStep, part: 'headers' | 'body'): void {
        const { key, value } = this.draft[part];

        if (!key.trim()) {
            return;
        }

        this.draft[part] = { key: '', value: '' };
        this.onEdit(step, part, key.trim(), value);
    }


    /**
     * Drops a value entered by hand.
     *
     * On a call the user added that removes the value outright; on one the assistant built it puts
     * the value back to what the interface description says, which is the only thing "remove" can
     * mean there - the call would send the field either way.
     */
    public onRemovePair(step: FlowStep, part: 'headers' | 'body', key: string): void {
        const current = this.valuesOf(step);
        const { [key]: _dropped, ...rest } = current[part] ?? {};

        this.writeValues(step, { ...current, [part]: rest });
    }


    /** Whether the value came from the user, which is what there is to take back. */
    public isOwn(step: FlowStep, part: 'headers' | 'body', key: string): boolean {
        return this.valuesOf(step)[part]?.[key] !== undefined;
    }


    public onEditEndpoint(step: FlowStep, endpoint: string): void {
        this.writeValues(step, { ...this.valuesOf(step), endpoint });
    }


    /** Where the values a user typed for this call are kept. */
    private valuesOf(step: FlowStep): AutomationCallOverride {
        const extra = this.extraFor(step);

        return extra
            ? { endpoint: extra.endpoint, headers: extra.headers, body: extra.body }
            : (this.definition.overrides[step.index] ?? {});
    }


    private writeValues(step: FlowStep, values: AutomationCallOverride): void {
        const extra = this.extraFor(step);

        if (extra) {
            this.definition.extras = this.definition.extras.map(candidate =>
                candidate.id === extra.id ? { ...candidate, ...values } : candidate
            );
        } else {
            this.definition.overrides = { ...this.definition.overrides, [step.index]: values };
        }

        this.definitionChange.emit(this.definition);
    }

    /* ------------------------------------------------- VALUE PICKER ------------------------------------------------- */

    public openPicker(part: 'headers' | 'body' | 'endpoint', key: string): void {
        this.picking = { part, key };
        this.pickFilter = '';
    }


    /**
     * Puts a reference into the value being edited.
     *
     * Appended rather than substituted, because a value is often part text and part reference - an
     * Authorization header is `Bearer` and then the token - and the engine replaces a reference
     * wherever in the value it finds one.
     */
    public onPick(source: ValueSource): void {
        const step = this.selected;
        const target = this.picking;

        if (!step || !target) {
            return;
        }

        this.picking = null;

        if (target.part === 'endpoint') {
            const address = this.endpointOf(step);

            this.onEditEndpoint(step, address ? `${address}${source.reference}` : source.reference);

            return;
        }

        const rows = target.part === 'headers' ? this.headerRows : this.bodyRows;
        const current = rows.find(pair => pair.key === target.key)?.value ?? '';

        this.onEdit(step, target.part, target.key, current ? `${current} ${source.reference}` : source.reference);
    }


    /** The same, for a pair that is still being written and has nowhere to be saved yet. */
    public onPickIntoDraft(source: ValueSource): void {
        const target = this.picking;

        if (!target || target.part === 'endpoint') {
            return;
        }

        const draft = this.draft[target.part];

        this.draft[target.part] = {
            ...draft,
            value: draft.value ? `${draft.value} ${source.reference}` : source.reference
        };
        this.picking = null;
    }


    public get filteredSources(): ValueSource[] {
        const needle = this.pickFilter.trim().toLowerCase();

        return needle
            ? this.valueSources.filter(source =>
                `${source.group} ${source.label}`.toLowerCase().includes(needle))
            : this.valueSources;
    }


    /** The same values, grouped - a select needs them nested where a list does not. */
    public get sourceGroups(): Array<{ name: string; items: ValueSource[] }> {
        const groups: Array<{ name: string; items: ValueSource[] }> = [];

        for (const source of this.valueSources) {
            const group = groups.find(candidate => candidate.name === source.group);

            if (group) {
                group.items.push(source);
            } else {
                groups.push({ name: source.group, items: [source] });
            }
        }

        return groups;
    }


    /** Whether the chosen comparison has a right-hand side at all. */
    public get conditionNeedsValue(): boolean {
        return !this.operators.find(entry => entry.value === this.condition.operator)?.unary;
    }


    /** Group heading, printed once above the first entry that belongs to it. */
    public startsGroup(source: ValueSource, position: number): boolean {
        return this.filteredSources[position - 1]?.group !== source.group;
    }


    /**
     * Everything the selected step could read.
     *
     * Only steps that have already run: a call cannot use an answer that has not been given yet, and
     * offering one would produce a reference the engine resolves to nothing. The element a reference
     * points at follows from the same rule the compiler uses - the list the loop walks is addressed
     * by its iterator, so every pass reads its own object, and anything else by position.
     */
    private buildValueSources(step: FlowStep | undefined): ValueSource[] {
        if (!this.connection || !step) {
            return [];
        }

        const methods = this.connection.fromConnector.methods;
        const iterated = this.loopArrayPath();
        const sources: ValueSource[] = [];

        for (const method of methods) {
            if (compareIndex(method.index, step.index) >= 0 || method.methodType === OC_FREE_REQUEST) {
                continue;
            }

            const group = method.connector?.title
                ? `${method.connector.title} · ${method.name}`
                : method.name;

            for (const path of leafPaths(method.response?.success?.body?.fields, iterated)) {
                sources.push({
                    group,
                    label: path,
                    reference: ocFieldReference(method.color, 'response', path)
                });
            }
        }

        return [...this.dataGerryFieldSources(methods[0], iterated), ...sources];
    }


    /**
     * The DataGerry fields, by the names the user knows them by.
     *
     * Only when DataGerry is the side being read - when it is being written, its fields are where
     * values go, not somewhere they come from, and the mapping step is what fills them.
     */
    private dataGerryFieldSources(source: OcMethod | undefined, iterated: string): ValueSource[] {
        if (!source || this.definition.direction !== 'outgoing') {
            return [];
        }

        return this.dataGerryFields.map((field, position) => ({
            group: 'DataGerry fields',
            label: field.label || field.name,
            reference: ocFieldReference(
                source.color,
                'response',
                `${iterated}[${OC_LOOP_ITERATOR}].fields[${position}].value`
            )
        }));
    }


    /** Which list the loop walks, read back out of its own expression. */
    private loopArrayPath(): string {
        const loop = this.connection?.fromConnector.operators.find(operator => operator.type === 'loop');

        return /body\.\$\.(.+?)\[\*\]/.exec(loop?.expression ?? '')?.[1] ?? '';
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

    public startAdding(): void {
        this.adding = this.adding ? '' : 'kind';
        this.operationFilter = '';
    }


    public onChooseKind(key: 'operation' | 'http' | 'if' | 'loop'): void {
        if (key === 'operation') {
            this.adding = 'operation';

            return;
        }

        if (key === 'if') {
            this.condition = { left: this.valueSources[0]?.reference ?? '', operator: '=', right: '' };
            this.editing = '';
            this.adding = 'condition';

            return;
        }

        if (key === 'http') {
            this.addExtra({ kind: 'http', operation: '', verb: 'POST', endpoint: '' });
        }
    }


    /**
     * Puts the condition being built into the sequence, or back into the step it came from.
     *
     * A condition with nothing to test would compile to an operator without an expression, which
     * OpenCelium rejects outright - so the sheet cannot be finished until it has a left-hand side.
     */
    public onSaveCondition(): void {
        if (!this.condition.left) {
            return;
        }

        const condition = { ...this.condition };

        if (this.editing) {
            const id = this.editing;

            this.definition.extras = this.definition.extras.map(candidate =>
                candidate.id === id ? { ...candidate, condition } : candidate
            );
            this.adding = '';
            this.editing = '';
            this.definitionChange.emit(this.definition);

            return;
        }

        this.addExtra({ kind: 'if', operation: '', condition });
    }


    /** Opens the condition of an added `if` for a second look. */
    public onEditCondition(step: FlowStep): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        this.condition = { left: '', operator: '=', right: '', ...(extra.condition ?? {}) };
        this.editing = extra.id;
        this.adding = 'condition';
    }


    public get filteredOperations(): string[] {
        const needle = this.operationFilter.trim().toLowerCase();

        return needle
            ? this.targetOperations.filter(name => name.toLowerCase().includes(needle))
            : this.targetOperations;
    }


    /** The row the detail pane shows, and the one a new call is placed after. */
    public get selected(): FlowStep | undefined {
        return this.steps.find(step => step.id === this.openStep) ?? this.steps[0];
    }


    /**
     * Puts a call of the user's own after a step.
     *
     * Placed by the step it follows rather than by an index, so a branch inserted above it later
     * does not move it somewhere it was never meant to run.
     */
    public onAddCall(operation: string): void {
        if (operation) {
            this.addExtra({ kind: 'operation', operation });
        }
    }


    private addExtra(partial: Omit<AutomationExtraCall, 'id' | 'after'>): void {
        const after = this.selected;

        if (!after) {
            return;
        }

        const extra: AutomationExtraCall = {
            ...partial,
            id: `extra-${this.definition.extras.length + 1}-${Date.now()}`,
            // A step the user added is named by its own id; one from the skeleton by its position,
            // which is stable because the skeleton is rebuilt the same way every time.
            after: this.extraFor(after)?.id ?? after.index
        };

        this.definition.extras = [...this.definition.extras, extra];
        this.awaiting = nodeIdOf(extra);
        this.adding = '';
        this.definitionChange.emit(this.definition);
    }


    /** The verb of a free request, which an operation brings with it instead. */
    public onEditVerb(step: FlowStep, verb: string): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        this.definition.extras = this.definition.extras.map(candidate =>
            candidate.id === extra.id ? { ...candidate, verb } : candidate
        );
        this.definitionChange.emit(this.definition);
    }


    public isFreeRequest(step: FlowStep): boolean {
        return this.extraFor(step)?.kind === 'http';
    }


    public verbChoices = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];


    /**
     * Moves an added call to the step before or after the one it currently follows.
     *
     * Only added calls can move. The skeleton is rebuilt from the connection and the assignment on
     * every change, so dragging one of its steps would have nowhere to be written down - which is
     * why those rows offer nothing here rather than offering something that quietly does not stick.
     */
    public onMoveCall(step: FlowStep, by: number): void {
        const extra = this.extraFor(step);
        const anchors = this.steps.filter(candidate => candidate.kind === 'call' && !this.isAdded(candidate));
        const at = anchors.findIndex(candidate => candidate.index === extra?.after);
        const target = anchors[at + by];

        if (!extra || at === -1 || !target) {
            return;
        }

        this.definition.extras = this.definition.extras.map(candidate =>
            candidate.id === extra.id ? { ...candidate, after: target.index } : candidate
        );
        this.definitionChange.emit(this.definition);
    }


    /** Whether an added call could move in that direction, so the button can say so. */
    public canMove(step: FlowStep, by: number): boolean {
        const extra = this.extraFor(step);
        const anchors = this.steps.filter(candidate => candidate.kind === 'call' && !this.isAdded(candidate));
        const at = anchors.findIndex(candidate => candidate.index === extra?.after);

        return !!extra && at !== -1 && !!anchors[at + by];
    }


    public onRemoveCall(step: FlowStep): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        const { [step.index]: _dropped, ...overrides } = this.definition.overrides;

        this.definition.extras = this.definition.extras
            .filter(candidate => candidate.id !== extra.id)
            // Steps placed inside or after this one move up to where it stood, rather than being
            // taken out with it or left pointing at something that is gone.
            .map(candidate => candidate.after === extra.id ? { ...candidate, after: extra.after } : candidate);
        this.definition.overrides = overrides;
        this.definitionChange.emit(this.definition);
    }


    /** Whether the step is a condition of the user's own, which is the one that can be changed. */
    public isAddedCondition(step: FlowStep): boolean {
        return step.kind === 'if' && this.extraFor(step)?.kind === 'if';
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
        return this.definition.extras.find(extra => nodeIdOf(extra) === step.id);
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


/**
 * A condition in as few words as the tree row has space for.
 *
 * References are what make an expression unreadable at a glance, and their last segment is the part
 * that carries the meaning: `{%#FFCFB5.(response).body.$.results[i].type_id%} = '12'` is, to
 * someone scanning the sequence, `type_id = '12'`.
 */
function summarize(expression: string): string {
    return expression
        .replace(/\{%(.*?)%\}/g, (_all, reference: string) => reference.split('.').pop() ?? reference)
        .replace(/^\((.*)\)$/, '$1');
}


/**
 * Which node in the compiled connection an added step became.
 *
 * Its own id, not its position: a position moves the moment something is inserted above it, and the
 * whole point of the link is that the row in front of the user can be traced back to the entry that
 * produced it - to be changed, moved or taken out again.
 */
function nodeIdOf(extra: AutomationExtraCall): string {
    if (extra.kind === 'if') {
        return ocIfNodeId(extra.id);
    }

    return extra.kind === 'http' ? ocSystemNodeId(extra.id) : ocMethodNodeId(extra.id);
}


/**
 * Flattens a response schema to the paths a reference can point at.
 *
 * A schema describes a list by one sample element, so a list becomes one set of paths rather than
 * one per entry. Which entry those paths mean is the whole question: the list the loop walks is
 * addressed by the iterator, so a reference into it reads the object of the current pass, and every
 * other list by its first entry - which is what a lookup's answer is.
 */
function leafPaths(node: unknown, iterated: string, prefix = ''): string[] {
    if (node === null || node === undefined || prefix.split('.').length > 6) {
        return [];
    }

    if (Array.isArray(node)) {
        const element = prefix === iterated ? OC_LOOP_ITERATOR : '0';

        return node.length === 0 ? [prefix] : leafPaths(node[0], iterated, `${prefix}[${element}]`);
    }

    if (typeof node !== 'object') {
        return prefix ? [prefix] : [];
    }

    return Object.entries(node as Record<string, unknown>)
        .flatMap(([key, value]) => leafPaths(value, iterated, prefix ? `${prefix}.${key}` : key));
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
