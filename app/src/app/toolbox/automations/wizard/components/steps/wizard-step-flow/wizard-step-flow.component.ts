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
    ocParseReference,
    ocIfNodeId,
    ocLoopNodeId,
    ocMethodNodeId,
    ocSystemNodeId,
    OC_FREE_REQUEST,
    OC_LOOP_ITERATOR
} from '../../../models/opencelium-connection.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * A stored value cut into the parts a reader can take in.
 *
 * A reference carries its whole route to the value - `#FFCFB5.(response).body.$.results[i].
 * fields[0].value` - and the only part of that a person recognises is the last segment. So the
 * route is kept and the name is shown, with the route one hover away.
 */
export interface ValueToken {
    /** What is written into the request: the literal text, or the whole reference. */
    text: string;

    /** True when `text` is a reference rather than something typed. */
    reference: boolean;

    /** What the reader sees: the literal for text, the field's name for a reference. */
    label: string;
}


/** One key/value pair of a request, as the table shows it. */
export interface WirePair {
    key: string;
    value: string;

    /** The value cut up for display; see ValueToken. */
    tokens: ValueToken[];

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

    /** True for a collection - what a loop walks, rather than what a request is given. */
    isList?: boolean;
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

    /** `detail` cut up, so a reference inside a condition reads as a name. See ValueToken. */
    detailTokens?: ValueToken[];
    system: string;
    method?: OcMethod;
    expression?: string;

    /** `expression` cut up the same way, for the block that shows it in full. */
    expressionTokens?: ValueToken[];
}

/**
 * What a reference would stand for, as far as that can be said before the automation ever runs.
 *
 * The distinction is the whole point: a value out of DataGerry is there to be looked at now, and a
 * value out of the target system is an answer nobody has been given yet. A stand-in for the second
 * would read as data, so there is none - the row says so instead.
 */
export interface ValuePreview {
    /** True when the value can be worked out now. */
    known: boolean;

    /** The sample value, empty when there is one to have and none was handed over. */
    value: string;

    /** Where the value comes from, which is what a row with nothing to show says instead. */
    source: string;
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

    /** Which stage of adding a step is open: the kinds, the operations, a container, or nothing. */
    public adding: '' | 'kind' | 'operation' | 'condition' | 'loop' = '';

    /** The list a loop being added should walk. */
    public loopList = '';

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
     * What a step can be: a call of either sort, or one of the two containers that govern what runs
     * after them.
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
            what: 'Walks a list from an earlier answer. Everything placed after it runs once per '
                + 'entry, and can read the entry the loop is on.',
            icon: 'fas fa-rotate',
            available: true
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

    /**
     * What one object's fields actually hold, by DataGerry field name.
     *
     * Debug mode shows a value as what it would be, and for the DataGerry side that can be said
     * before a run - but only against a real object. Empty until the shell hands one over, which
     * is what the rows then say rather than inventing something that looks like data.
     */
    @Input() public sampleValues: Record<string, string> = {};

    /** Whether every substituted value is shown as what it would be. */
    public debug = false;

    /** The selected call's request, a row per value, cached against the template asking for it. */
    public headerRows: WirePair[] = [];
    public bodyRows: WirePair[] = [];

    /** What the selected step could read, grouped by the step that answers it. */
    public valueSources: ValueSource[] = [];

    /** The same for a step added at the selected one - see buildValueSources. */
    public addSources: ValueSource[] = [];

    /** The address of the selected call, cut up the same way as the pairs. */
    public endpointTokens: ValueToken[] = [];

    /**
     * Which value is open for typing, as `part:key`.
     *
     * A value is shown by its field names and only turns into an editable box when it is clicked,
     * because the box has to hold the whole reference for editing to be honest about what is sent.
     */
    private editingField = '';

    /** A path into an answer, written out rather than picked - see onUseWrittenPath. */
    public writtenCall = '';
    public writtenPath = '';

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

    /**
     * What each reference resolves to, kept between passes.
     *
     * Worked out once per reference rather than on every template pass: a reference is looked up
     * wherever it appears, and the answer only changes when the connection or the sample does.
     */
    private previews = new Map<string, ValuePreview>();
    private seenSamples: Record<string, string> = {};

    /** Which node a just-added step becomes, so the detail pane opens on it rather than on nothing. */
    private awaiting = '';

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    public ngDoCheck(): void {
        const recompiled = this.connection !== this.seenConnection;

        // A sample can arrive long after the sequence does, and every resolved value is drawn from
        // it, so what was worked out against the old one no longer holds.
        if (recompiled || this.sampleValues !== this.seenSamples) {
            this.seenSamples = this.sampleValues;
            this.previews.clear();
        }

        if (recompiled) {
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
        }

        const moved = this.openStep !== this.seenStep;

        if (!recompiled && !moved) {
            return;
        }

        // Only when the user actually goes somewhere else. Every edit recompiles the connection,
        // and clearing the pair being typed on each of those would take a half-written header away
        // from under whoever is writing it.
        if (moved) {
            this.seenStep = this.openStep;
            this.draft = { headers: { key: '', value: '' }, body: { key: '', value: '' } };
            this.picking = null;
        }

        // Rebuilt here rather than read out of the template: every one of these walks the whole
        // connection and hands back a new array, and a template that asks on each pass would keep
        // finding a different one and never settle.
        const step = this.selected;

        this.headerRows = step ? this.headersOf(step) : [];
        this.bodyRows = step ? this.bodyOf(step) : [];
        this.endpointTokens = step ? tokensOf(this.endpointOf(step)) : [];
        this.valueSources = this.buildValueSources(step);
        this.addSources = this.buildValueSources(step, true);

        if (moved) {
            this.editingField = '';
        }
    }


    /* --------------------------------------------------- SHOWN VALUES ----------------------------------------------- */

    public isEditing(part: 'headers' | 'body' | 'endpoint', key: string): boolean {
        return this.editingField === `${part}:${key}`;
    }


    public startEditing(part: 'headers' | 'body' | 'endpoint', key: string): void {
        this.editingField = `${part}:${key}`;
    }


    public stopEditing(): void {
        this.editingField = '';
    }

    /* ---------------------------------------------------- DEBUG MODE ------------------------------------------------ */

    /** What a reference would stand for. See ValuePreview. */
    public previewOf(reference: string): ValuePreview {
        const worked = this.previews.get(reference);

        if (worked) {
            return worked;
        }

        const preview = this.resolvePreview(reference);

        this.previews.set(reference, preview);

        return preview;
    }


    /**
     * Which side of the automation answers a reference, and with what.
     *
     * The colour is what says: every reference names the call it reads, and only one call in the
     * sequence is DataGerry's own read. Everything else is the target system, whose answer does not
     * exist until the automation actually runs.
     */
    private resolvePreview(reference: string): ValuePreview {
        const path = reference.replace(/^\{%/, '').replace(/%\}$/, '');
        const parts = /^#([0-9A-Fa-f]{6})\.\(\w+\)\.(.*)$/.exec(path);
        const method = parts && (this.connection?.fromConnector.methods ?? []).find(
            candidate => (candidate.color ?? '').toUpperCase() === `#${parts[1].toUpperCase()}`
        );

        if (!parts || !method) {
            return { known: false, value: '', source: 'a step this sequence no longer holds' };
        }

        if (method !== this.connection?.fromConnector.methods[0] || this.definition.direction !== 'outgoing') {
            return {
                known: false,
                value: '',
                source: method.connector?.title ? `${method.connector.title} · ${method.name}` : method.name
            };
        }

        // DataGerry answers with the fields in the order the type declares them, so the position in
        // that answer is what names the field - and the field's name is what a sample is keyed by.
        const field = this.dataGerryFields[Number(/fields\[(\d+)\]\.value$/.exec(parts[2])?.[1] ?? -1)];

        return {
            known: true,
            value: field ? this.sampleValues[field.name] ?? '' : '',
            source: field ? field.label || field.name : 'DataGerry'
        };
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
            // The read that fetches the objects is the automation itself, whichever system answers
            // it: it follows from the object type and there is nothing to decide about it. Listing
            // it made the sequence of an incoming automation start with a call nobody had chosen.
            if (method === source) {
                continue;
            }

            entries.push({
                id: method.id,
                index: method.index,
                depth: depthOf(method.index),
                kind: 'call',
                title: this.titleOf(method),
                detail: method.name,
                detailTokens: [{ text: method.name, reference: false, label: method.name }],
                system: method.connector?.title ?? '',
                method
            });
        }

        for (const operator of this.connection.fromConnector.operators) {
            // The loop over the objects being synchronised is the automation itself, not a step in
            // it: it follows from the object type, there is nothing to decide about it, and showing
            // it would bury the steps that can be acted on.
            if (operator.type === 'loop' && !operator.id.startsWith('loop-extra-')) {
                continue;
            }

            entries.push({
                id: operator.id,
                index: operator.index,
                depth: depthOf(operator.index),
                kind: operator.type,
                title: this.titleOfOperator(operator),
                detail: summarize(operator.expression),
                detailTokens: tokensOf(unwrap(operator.expression)),
                system: '',
                expression: operator.expression,
                expressionTokens: tokensOf(operator.expression)
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
        if (operator.type === 'loop') {
            return 'For every entry';
        }

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
    /**
     * Takes a value out of the request, or takes back a change made to one.
     *
     * Two different things behind one button, and which it is follows from where the value came
     * from. A value the user set is dropped, so the operation's own comes back. One the operation
     * offers is marked as removed, because an empty key is not the same as an absent one to every
     * API - and it is put back by adding it again under its own name.
     */
    public onRemovePair(step: FlowStep, part: 'headers' | 'body', key: string): void {
        const current = this.valuesOf(step);

        if (this.isOwn(step, part, key)) {
            const { [key]: _dropped, ...rest } = current[part] ?? {};

            this.writeValues(step, { ...current, [part]: rest });

            return;
        }

        this.writeValues(step, { ...current, [part]: { ...(current[part] ?? {}), [key]: null } });
    }


    /** True when the value is one the operation offers and the automation does not send. */
    public isRemoved(step: FlowStep, part: 'headers' | 'body', key: string): boolean {
        return this.valuesOf(step)[part]?.[key] === null;
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


    /**
     * Puts a path somebody wrote out into the value being filled in.
     *
     * The list is what the invokers of the chosen calls describe, and an API answers with more than
     * its description covers often enough that stopping there would be a dead end. Whether the
     * field arrives is the installation's business - OpenCelium reports a reference it cannot
     * resolve rather than failing the run.
     */
    public onUseWrittenPath(): void {
        const path = this.writtenPath.trim();
        const color = this.writtenCall || this.answeringCalls[0]?.color;

        if (!path || !color) {
            return;
        }

        const source: ValueSource = {
            group: 'Written out',
            label: path,
            reference: ocFieldReference(color, 'response', path)
        };

        if (this.picking?.key || this.picking?.part === 'endpoint') {
            this.onPick(source);
        } else {
            this.onPickIntoDraft(source);
        }

        this.writtenPath = '';
    }


    /** The calls a written-out path can read, which is every one that answers before this point. */
    public get answeringCalls(): SequenceCall[] {
        const seen = new Map<string, SequenceCall>();

        for (const source of this.addSources) {
            const color = ocParseReference(source.reference)?.color;

            if (color && !seen.has(color)) {
                seen.set(color, { label: source.group, color });
            }
        }

        return [...seen.values()];
    }


    public get filteredSources(): ValueSource[] {
        const needle = this.pickFilter.trim().toLowerCase();

        return needle
            ? this.plainSources.filter(source =>
                `${source.group} ${source.label}`.toLowerCase().includes(needle))
            : this.plainSources;
    }


    /** The same values, grouped - a select needs them nested where a list does not. */
    public get sourceGroups(): Array<{ name: string; items: ValueSource[] }> {
        const groups: Array<{ name: string; items: ValueSource[] }> = [];

        for (const source of this.addableSources) {
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
    /**
     * What is readable at a point in the sequence.
     *
     * `forNewStep` moves that point one along: a step being added runs after the selected one, so
     * it can read the selected one's answer - which is the whole reason for adding it there. Built
     * as a second list rather than by moving the first, because the request of the selected step
     * cannot read its own answer and its picker must not offer it.
     */
    private buildValueSources(step: FlowStep | undefined, forNewStep = false): ValueSource[] {
        if (!this.connection || !step) {
            return [];
        }

        const methods = this.connection.fromConnector.methods;
        const loops = this.enclosingLoops(step.index);
        const sources: ValueSource[] = [];

        for (const method of methods) {
            if (compareIndex(method.index, step.index) >= (forNewStep ? 1 : 0)
                || method.methodType === OC_FREE_REQUEST) {
                continue;
            }

            const group = method.connector?.title
                ? `${method.connector.title} · ${method.name}`
                : method.name;

            for (const entry of schemaPaths(method.response?.success?.body?.fields, loops)) {
                sources.push({
                    group,
                    label: entry.path,
                    reference: ocFieldReference(method.color, 'response', entry.path),
                    isList: entry.isList
                });
            }
        }

        return [...this.dataGerryFieldSources(methods[0], loops), ...sources];
    }


    /**
     * The DataGerry fields, by the names the user knows them by.
     *
     * Only when DataGerry is the side being read - when it is being written, its fields are where
     * values go, not somewhere they come from, and the mapping step is what fills them.
     */
    private dataGerryFieldSources(
        source: OcMethod | undefined,
        loops: ReadonlyArray<{ path: string; iterator: string }>
    ): ValueSource[] {
        const objects = loops[0];

        if (!source || !objects || this.definition.direction !== 'outgoing') {
            return [];
        }

        return this.dataGerryFields.map((field, position) => ({
            group: 'DataGerry fields',
            label: field.label || field.name,
            reference: ocFieldReference(
                source.color,
                'response',
                `${objects.path}[${objects.iterator}].fields[${position}].value`
            )
        }));
    }


    /**
     * The loops a step runs inside, outermost first.
     *
     * Read back out of the operators rather than tracked alongside them: an execution index says
     * which loops wrap a step - everything under '1' runs inside the loop at '1' - and each loop's
     * own expression says which list it walks and what it calls an entry.
     */
    private enclosingLoops(index: string): Array<{ path: string; iterator: string }> {
        return (this.connection?.fromConnector.operators ?? [])
            .filter(operator => operator.type === 'loop' && index.startsWith(`${operator.index}_`))
            .sort((left, right) => compareIndex(left.index, right.index))
            .map(operator => ({
                path: /body\.\$\.(.+?)\[\*\]/.exec(operator.expression)?.[1] ?? '',
                iterator: operator.iterator || OC_LOOP_ITERATOR
            }))
            .filter(loop => !!loop.path);
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
            this.condition = { left: this.firstValue?.reference ?? '', operator: '=', right: '' };
            this.editing = '';
            this.adding = 'condition';

            return;
        }

        if (key === 'loop') {
            this.loopList = this.listSources[0]?.reference ?? '';
            this.editing = '';
            this.adding = 'loop';

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


    /**
     * Puts the loop being built into the sequence, or back into the step it came from.
     *
     * The name for an entry is handed out rather than asked for: every reference into a list carries
     * the name of the loop walking it, so two loops sharing one would read each other's entry.
     */
    public onSaveLoop(): void {
        if (!this.loopList) {
            return;
        }

        if (this.editing) {
            const id = this.editing;

            this.definition.extras = this.definition.extras.map(candidate =>
                candidate.id === id
                    ? { ...candidate, loop: { list: this.loopList, iterator: candidate.loop?.iterator ?? 'j' } }
                    : candidate
            );
            this.adding = '';
            this.editing = '';
            this.definitionChange.emit(this.definition);

            return;
        }

        this.addExtra({
            kind: 'loop',
            operation: '',
            loop: { list: this.loopList, iterator: this.freeIterator() }
        });
    }


    /** Opens the list of an added loop for a second look. */
    public onEditLoop(step: FlowStep): void {
        const extra = this.extraFor(step);

        if (!extra) {
            return;
        }

        this.loopList = extra.loop?.list ?? '';
        this.editing = extra.id;
        this.adding = 'loop';
    }


    /**
     * A name for the loop's entry that no other loop is using.
     *
     * 'i' belongs to the loop over the objects being synchronised, which every automation has, so
     * the ones the user adds start after it.
     */
    private freeIterator(): string {
        const taken = new Set([
            OC_LOOP_ITERATOR,
            ...(this.connection?.fromConnector.operators ?? [])
                .filter(operator => operator.type === 'loop')
                .map(operator => operator.iterator ?? ''),
            ...this.definition.extras.map(extra => extra.loop?.iterator ?? '')
        ]);

        return 'jklmnopqrstuvwxyz'.split('').find(name => !taken.has(name)) ?? 'z';
    }


    /** The collections on offer, which is what a loop can be pointed at. */
    public get listSources(): ValueSource[] {
        return this.addSources.filter(source => source.isList);
    }


    /** The values on offer - everything that is not a collection. */
    /**
     * Everything readable, lists included.
     *
     * A list used to be held back here because only a loop walks one - but a condition asks whether
     * one is empty, and a request value sometimes carries the list itself. Whether a list makes
     * sense in a place is a question for that place, not for the list.
     */
    public get plainSources(): ValueSource[] {
        return this.valueSources;
    }


    /** The same, for the step about to be added. */
    public get addableSources(): ValueSource[] {
        return this.addSources;
    }


    private get firstValue(): ValueSource | undefined {
        return this.addableSources[0];
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
        // A step the user added is named by its own id; one from the skeleton by its position,
        // which is stable because the skeleton is rebuilt the same way every time. With nothing in
        // the sequence yet there is no step to name, so the first one hangs off the container the
        // automation always has - which is also what makes it run once per object.
        const anchor = after ? (this.extraFor(after)?.id ?? after.index) : this.perObjectContainer;

        if (!anchor) {
            return;
        }

        const extra: AutomationExtraCall = {
            ...partial,
            id: `extra-${this.definition.extras.length + 1}-${Date.now()}`,
            after: anchor
        };

        this.definition.extras = [...this.definition.extras, extra];
        this.awaiting = nodeIdOf(extra);
        this.adding = '';
        this.definitionChange.emit(this.definition);
    }


    /**
     * The container whose body runs once per object read.
     *
     * The restriction gate when the automation has one, because everything the loop does moves
     * inside it, and the loop itself otherwise. Empty only while nothing compiles, which is when
     * there is nothing to add a step to anyway.
     */
    private get perObjectContainer(): string {
        const operators = this.connection?.fromConnector?.operators ?? [];
        const gate = operators.find(operator => operator.id === 'if-gate');

        return (gate ?? operators.find(operator => operator.type === 'loop'))?.index ?? '';
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


    /* -------------------------------------------------- REORDERING -------------------------------------------------- */

    /**
     * Moves an added step past the added step before or after it.
     *
     * Only added steps move, and only among each other. The skeleton is rebuilt from the definition
     * on every change, so a step of it has nowhere to record that it was moved - and an added step
     * cannot rise above the skeleton steps it shares a container with, because the compiler hangs
     * added steps behind them. Those rows offer nothing here rather than offering a move that
     * quietly does not stick.
     *
     * What decides the order is the order of the entries themselves, so that is what is rewritten;
     * the step each one is placed after only says which container it runs in.
     */
    public onMove(step: FlowStep, by: number): void {
        const target = this.neighbourOf(step, by);

        if (!this.isAdded(step) || !target) {
            return;
        }

        const block = this.subtreeOf(step);
        const rest = this.definition.extras.filter(extra => !block.includes(extra));
        const passed = this.subtreeOf(target).filter(extra => rest.includes(extra));
        // Down passes the neighbour whole: everything running inside it goes with it, or the step
        // would land in the middle of a branch nobody put it in.
        const at = by < 0
            ? rest.indexOf(passed[0])
            : rest.indexOf(passed[passed.length - 1]) + 1;

        this.writeExtras([...rest.slice(0, at), ...block, ...rest.slice(at)]);
    }


    /** Whether an added step could move that way, so the button can say so. */
    public canMove(step: FlowStep, by: number): boolean {
        return this.isAdded(step) && !!this.neighbourOf(step, by);
    }


    /**
     * Takes an added step into the step above it, or out of the one it runs inside.
     *
     * Being inside a container is what "only when it holds" and "once per entry" mean, and it is
     * decided when the step is added. This is the way back - and the way in for a step that was
     * added before the container it belongs in.
     */
    public onNest(step: FlowStep, inside: boolean): void {
        const extra = this.extraFor(step);
        const target = this.nestTarget(step, inside);

        if (!extra || !target) {
            return;
        }

        const block = this.subtreeOf(step);
        const rest = this.definition.extras.filter(candidate => !block.includes(candidate));
        const around = this.subtreeOf(target.container).filter(candidate => rest.includes(candidate));
        const at = around.length ? rest.indexOf(around[around.length - 1]) + 1 : rest.length;
        const moved = block.map(candidate =>
            candidate.id === extra.id ? { ...candidate, after: target.anchor } : candidate);

        this.writeExtras([...rest.slice(0, at), ...moved, ...rest.slice(at)]);
    }


    public canNest(step: FlowStep, inside: boolean): boolean {
        return !!this.extraFor(step) && !!this.nestTarget(step, inside);
    }


    /**
     * Reordering from the keyboard, on the row itself.
     *
     * Alt is what leaves the plain arrows doing what they do in every other list - moving between
     * rows - while still putting each move within reach of someone who never touches a mouse.
     */
    public onRowKeys(step: FlowStep, event: KeyboardEvent): void {
        if (!event.altKey) {
            return;
        }

        const moves: Record<string, () => void> = {
            ArrowUp: () => this.onMove(step, -1),
            ArrowDown: () => this.onMove(step, 1),
            ArrowLeft: () => this.onNest(step, false),
            ArrowRight: () => this.onNest(step, true)
        };

        const move = moves[event.key];

        if (!move) {
            return;
        }

        event.preventDefault();
        this.select(step);
        move();
    }


    /** The added step this one would trade places with: its neighbour inside the same container. */
    private neighbourOf(step: FlowStep, by: number): FlowStep | undefined {
        const row = this.steps.filter(candidate =>
            this.isAdded(candidate) && parentOf(candidate.index) === parentOf(step.index));
        const at = row.findIndex(candidate => candidate.id === step.id);

        return at === -1 ? undefined : row[at + by];
    }


    /**
     * An added step and everything that runs inside it, in the order the entries are read.
     *
     * Taken from the compiled indices rather than from the entries: an entry says which step it
     * follows, and following a call means running beside it while following a container means
     * running inside it. The index is where that distinction has already been made.
     */
    private subtreeOf(step: FlowStep): AutomationExtraCall[] {
        const inside = this.steps.filter(candidate =>
            candidate.id === step.id || candidate.index.startsWith(`${step.index}_`));

        return this.definition.extras.filter(extra =>
            inside.some(candidate => candidate.id === nodeIdOf(extra)));
    }


    /** Which container a step would move into or out of, and what it would then be placed after. */
    private nestTarget(step: FlowStep, inside: boolean): { anchor: string; container: FlowStep } | undefined {
        const container = inside ? this.containerAbove(step) : this.containerOf(step);

        if (!container) {
            return undefined;
        }

        if (inside) {
            return { anchor: this.keyOf(container), container };
        }

        const owner = this.extraFor(container);

        if (owner) {
            return { anchor: owner.after, container };
        }

        // Out of a container the skeleton owns there is no entry to borrow a place from, so the
        // only anchor left is a call standing beside it - and where there is none, nowhere to go.
        const beside = this.steps.find(candidate => candidate.kind === 'call'
            && parentOf(candidate.index) === parentOf(container.index));

        return beside ? { anchor: this.keyOf(beside), container } : undefined;
    }


    /** The container a step runs inside, if the sequence shows one. */
    private containerOf(step: FlowStep): FlowStep | undefined {
        return this.steps.find(candidate => candidate.index === parentOf(step.index)
            && candidate.kind !== 'call');
    }


    /** The step directly above it in the same container, if that step is one to run inside. */
    private containerAbove(step: FlowStep): FlowStep | undefined {
        const row = this.steps.filter(candidate => parentOf(candidate.index) === parentOf(step.index));
        const at = row.findIndex(candidate => candidate.id === step.id);
        const above = at > 0 ? row[at - 1] : undefined;

        return above && above.kind !== 'call' ? above : undefined;
    }


    /** How an entry names the step it follows: its own id, or the position of a skeleton step. */
    private keyOf(step: FlowStep): string {
        return this.extraFor(step)?.id ?? step.index;
    }


    private writeExtras(extras: AutomationExtraCall[]): void {
        this.definition.extras = normalizeAnchors(extras);
        this.definitionChange.emit(this.definition);
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


    /** Whether the step is a container of the user's own, which is the one that can be changed. */
    public isAddedCondition(step: FlowStep): boolean {
        return step.kind === 'if' && this.extraFor(step)?.kind === 'if';
    }


    public isAddedLoop(step: FlowStep): boolean {
        return step.kind === 'loop' && this.extraFor(step)?.kind === 'loop';
    }


    /** What the loop calls the entry it is on, which is what the steps inside it read. */
    public iteratorOf(step: FlowStep): string {
        return this.extraFor(step)?.loop?.iterator ?? '';
    }


    /** Whether the call was added by hand, which is what may be removed and re-pointed. */
    public isAdded(step: FlowStep): boolean {
        return !!this.extraFor(step);
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


/** The container an execution index sits in: '1_2_0' runs inside '1_2'. */
function parentOf(index: string): string {
    return index.split('_').slice(0, -1).join('_');
}


/**
 * Re-points whatever is left naming a step that now runs after it.
 *
 * A step is placed by the one it follows, and the entries are read in order - so moving one past
 * another leaves the second naming a step it now comes before, which the compiler cannot place and
 * drops with a warning. It belongs where the step it named belonged, which is that step's own
 * place, and the chain is walked because the same may have happened to that one.
 */
function normalizeAnchors(extras: AutomationExtraCall[]): AutomationExtraCall[] {
    const byId = new Map(extras.map(extra => [extra.id, extra]));
    const behind = new Set<string>();

    return extras.map(extra => {
        let anchor = extra.after;

        for (let hop = 0; hop <= extras.length && byId.has(anchor) && !behind.has(anchor); hop++) {
            anchor = byId.get(anchor)!.after;
        }

        behind.add(extra.id);

        return anchor === extra.after ? extra : { ...extra, after: anchor };
    });
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
/**
 * Matches a field reference in a stored value.
 *
 * Two spellings are in use: a request value holds the reference bare, an operator expression wraps
 * it in `{%…%}`. Both are recognised so the same display works either side.
 */
const REFERENCE_PATTERN = /\{%[^%]*%\}|#[0-9A-Fa-f]{6}\.\([a-z]+\)[^\s,;)"']*/g;


/** The part of a reference that carries meaning: its last segment, without any array index. */
export function referenceLabel(reference: string): string {
    const path = reference.replace(/^\{%/, '').replace(/%\}$/, '');
    const last = path.split('.').filter(Boolean).pop() ?? path;

    return last.replace(/\[[^\]]*\]$/, '') || last;
}


/**
 * Cuts a stored value into literal text and references.
 *
 * A value is often part of each - an Authorization header is the word `Bearer` and then a token -
 * so this returns a sequence rather than deciding the value is one thing or the other.
 */
export function tokensOf(value: string): ValueToken[] {
    const tokens: ValueToken[] = [];
    let at = 0;

    for (const hit of value.matchAll(REFERENCE_PATTERN)) {
        const start = hit.index ?? 0;

        if (start > at) {
            const text = value.slice(at, start);
            tokens.push({ text, reference: false, label: text });
        }

        tokens.push({ text: hit[0], reference: true, label: referenceLabel(hit[0]) });
        at = start + hit[0].length;
    }

    if (at < value.length) {
        const text = value.slice(at);
        tokens.push({ text, reference: false, label: text });
    }

    return tokens;
}


/** Drops the parentheses an operator expression is wrapped in, which say nothing on their own. */
function unwrap(expression: string): string {
    return expression.replace(/^\((.*)\)$/, '$1');
}


function summarize(expression: string): string {
    // Same cut as the request rows use, so a field is called the same thing wherever it appears.
    return unwrap(expression.replace(/\{%.*?%\}/g, reference => referenceLabel(reference)));
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

    if (extra.kind === 'loop') {
        return ocLoopNodeId(extra.id);
    }

    return extra.kind === 'http' ? ocSystemNodeId(extra.id) : ocMethodNodeId(extra.id);
}


/**
 * Flattens a response schema to the paths a reference can point at.
 *
 * A schema describes a list by one sample element, so a list becomes one set of paths rather than
 * one per entry. Which entry those paths mean is the whole question. A list some loop walks is
 * addressed by that loop's iterator, so a reference into it reads the entry of the current pass;
 * every other list is addressed by its first entry, which is what a lookup's answer is. The list
 * itself is offered too, as `[*]` - that is the one thing a new loop can be pointed at.
 */
/** One call of the sequence, as something that answers - which is all a reference needs of it. */
export interface SequenceCall {
    label: string;
    color: string;
}


/** The calls of a connection, for a reference that names its own path instead of picking one. */
export function sequenceCallsOf(connection: OcConnection | null): SequenceCall[] {
    return (connection?.fromConnector.methods ?? [])
        .filter(method => method.methodType !== OC_FREE_REQUEST)
        .map(method => ({
            label: method.connector?.title ? `${method.connector.title} · ${method.name}` : method.name,
            color: method.color
        }));
}


/**
 * Everything the sequence answered, for the call that runs after all of it.
 *
 * The fields step offers the same list as the sequence does, but for no particular step - the call
 * it configures is the last thing inside the container. Built here rather than a second time, so a
 * value carries the same name on both screens and a reference picked on one resolves on the other.
 */
export function valueSourcesAfterSequence(connection: OcConnection | null): ValueSource[] {
    if (!connection) {
        return [];
    }

    const operators = connection.fromConnector.operators ?? [];
    const container = operators.find(operator => operator.id === 'if-gate')
        ?? operators.find(operator => operator.type === 'loop');

    if (!container) {
        return [];
    }

    // A position inside the container, which is where the call sits - it decides which loops the
    // references have to walk with an iterator.
    const at = `${container.index}_0`;
    const loops = operators
        .filter(operator => operator.type === 'loop' && at.startsWith(`${operator.index}_`))
        .sort((left, right) => compareIndex(left.index, right.index))
        .map(operator => ({
            path: /body\.\$\.(.+?)\[\*\]/.exec(operator.expression)?.[1] ?? '',
            iterator: operator.iterator || OC_LOOP_ITERATOR
        }))
        .filter(loop => !!loop.path);

    return connection.fromConnector.methods
        .filter(method => method.methodType !== OC_FREE_REQUEST)
        .flatMap(method => schemaPaths(method.response?.success?.body?.fields, loops).map(entry => ({
            group: method.connector?.title ? `${method.connector.title} · ${method.name}` : method.name,
            label: entry.path,
            reference: ocFieldReference(method.color, 'response', entry.path),
            isList: entry.isList
        })));
}


function schemaPaths(
    node: unknown,
    loops: ReadonlyArray<{ path: string; iterator: string }>,
    prefix = ''
): Array<{ path: string; isList?: boolean }> {
    if (node === null || node === undefined || prefix.split('.').length > 6) {
        return [];
    }

    if (Array.isArray(node)) {
        // Whichever loop walks this collection names its entries; anything unwalked is read at its
        // first entry. The loops' own paths already carry the iterators of the loops around them,
        // which is why matching on the prefix works at any depth.
        const element = loops.find(loop => loop.path === prefix)?.iterator ?? '0';
        const list = { path: `${prefix}[*]`, isList: true };

        return node.length === 0
            ? [list]
            : [list, ...schemaPaths(node[0], loops, `${prefix}[${element}]`)];
    }

    if (typeof node !== 'object') {
        return prefix ? [{ path: prefix }] : [];
    }

    return Object.entries(node as Record<string, unknown>)
        .flatMap(([key, value]) => schemaPaths(value, loops, prefix ? `${prefix}.${key}` : key));
}


/** Flattens a request tree to dotted paths, which is how the mapping names them too. */
function pairsOf(node: unknown, prefix = ''): WirePair[] {
    if (node === null || node === undefined) {
        return [];
    }

    if (typeof node !== 'object') {
        const value = String(node);

        return [{
            key: prefix,
            value,
            tokens: tokensOf(value),
            reference: value.startsWith('#'),
            bound: false,
            changed: false
        }];
    }

    if (Array.isArray(node)) {
        // An empty list still gets a row, at the position a value would take. An operation that
        // describes a list it does not fill - i-doit's params.filter.type is one - would otherwise
        // be invisible here and unfillable, while still being part of what the call sends.
        return node.length === 0
            ? pairsOf('', `${prefix}[0]`)
            : node.flatMap((item, index) => pairsOf(item, `${prefix}[${index}]`));
    }

    return Object.entries(node as Record<string, unknown>)
        .flatMap(([key, value]) => pairsOf(value, prefix ? `${prefix}.${key}` : key));
}
