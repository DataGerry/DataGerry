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
    AutomationField,
    AutomationMappingEntry,
    AutomationMappingSource,
    AutomationRuleCombinator,
    AutomationRuleOperator,
    AutomationValueTransform,
    createEmptyTransform,
    hasActiveTransform,
    ruleNeedsValue,
    sourceKindOf
} from '../../../models/automation-definition.model';
import { RULE_OPERATOR_CHOICES } from '../../../models/automation-wizard-step.model';
import { ocFieldReference, ocParseReference } from '../../../models/opencelium-connection.model';
import { TargetField } from '../../../models/target-catalog.model';
import {
    groupValueSources,
    referenceLabel,
    SequenceBinding,
    SequenceCall,
    tokensOf,
    ValueSource,
    ValueSourceGroup,
    ValueToken
} from '../wizard-step-flow/wizard-step-flow.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One value a row is built from, named the way the adjustment script sees it. */
interface SourceView {
    label: string;

    /** The whole route to the value, which the label hides - shown on hover. */
    reference: string;

    /** The call that answers with it, so a name shared by two calls still says where it came from. */
    call: string;

    /** `value`, or `value1`/`value2` when several sources meet in one target. */
    variable: string;
}


/** What the adjustment panel needs of a row, whichever direction the row belongs to. */
interface AdjustableRow {
    /** What the adjustment, and whether the panel is open, are keyed by. */
    key: string;

    /** The mapping entry carrying the adjustment, or null when the key carries it instead. */
    entry: AutomationMappingEntry | null;
    transform: AutomationValueTransform | null;

    /** True when the adjustment reshapes the value, as opposed to being an empty draft. */
    adjusted: boolean;

    /** True when the target takes more than one value, so the script has to combine them. */
    combined: boolean;
    sources: SourceView[];
}


/**
 * One value the sequence writes, as the table shows it.
 *
 * Read off the sequence rather than off the mapping: where a value lands is a field reference in a
 * request value, so nothing in the definition pairs the two, and only the compiled calls do.
 */
interface BindingRow extends AdjustableRow {
    /** The call writing this value, named and numbered the way the sequence names it. */
    call: string;
    callIndex: string;

    /** Where the value lands, as the path and its last segment. */
    path: string;
    field: string;
}


/** The values one call writes, under that call. */
interface BindingGroup {
    call: string;
    callIndex: string;
    rows: BindingRow[];
}


/**
 * One field of the DataGerry object type, and what an incoming automation writes into it.
 *
 * Every field of the type gets a row whether it is written or not: deciding means seeing the
 * fields that stay empty as much as the ones that fill up.
 */
interface WriteRow extends AdjustableRow {
    /** The DataGerry field name, which is also the target its mapping entry is keyed by. */
    field: string;
    label: string;

    /** What the picker stands on: '' for nothing, LITERAL_CHOICE, or the chosen reference. */
    choice: string;
    literal: string;

    /** The chosen reference cut up, so it reads as a name and hovers as the whole route. */
    tokens: ValueToken[];

    /** The reference read back from a draft the sequence no longer offers - see rebuild(). */
    unlisted: string;

    /** Colour of the call a hand-written path reads, and the path itself. */
    pathCall: string;
    path: string;
}


/** Shared fallbacks, so a row does not hand the template a new array on every check. */
const EMPTY_BINDING_ROWS: BindingRow[] = [];
const EMPTY_BINDING_GROUPS: BindingGroup[] = [];
const EMPTY_WRITE_ROWS: WriteRow[] = [];
const EMPTY_VIEWS: SourceView[] = [];

/** Stands for "a value I type in" in the picker; no reference can collide with it. */
const LITERAL_CHOICE = '$literal';

/**
 * The picker entry for a path written out by hand.
 *
 * The list only holds what the invokers describe, and an API answers with more than its
 * description covers often enough that leaving it at that would be a dead end. Whether the field
 * really arrives is the installation's business - OpenCelium reports a reference it cannot resolve
 * rather than failing the run.
 */
const PATH_CHOICE = '$path';

/** Whether an adjustment reshapes its value, as opposed to merely carrying an empty draft. */
function isActive(transform: AutomationValueTransform | null): boolean {
    return !!transform?.enabled && !!transform.script.trim();
}

/**
 * Step group 4 - what each field is given, and the value adjustment that reshapes it.
 *
 * The direction decides what there is to do here, because it decides what the sequence already
 * settled. Reading DataGerry, the field pairs were settled in the sequence, where a request value
 * was given a field reference; repeating that decision here would put one answer in two places, so
 * this screen only reads those pairs back off the calls and the adjustment script is all a user
 * changes.
 *
 * Writing DataGerry, the sequence only fetched - nothing has been said yet about what lands in the
 * object. So this screen lists the whole object type, one row per field, and each field is given
 * nothing, a typed value, or one of the answers the sequence collected.
 *
 * Which is also why an adjustment is kept in two different places. An incoming row is a mapping
 * entry and carries its adjustment; an outgoing row is a value one call writes, which no entry
 * exists for, so its adjustment is kept under the binding's key - the call and the request path,
 * because two calls can write the same path and an adjustment belongs to one of them.
 */
@Component({
    selector: 'app-wizard-step-mapping',
    templateUrl: './wizard-step-mapping.component.html',
    styleUrls: ['./wizard-step-mapping.component.scss'],
    standalone: false
})
export class WizardStepMappingComponent implements DoCheck {

    @Input() public definition!: AutomationDefinition;
    @Input() public sourceFields: AutomationField[] = [];

    /**
     * Every field of the chosen object type, so an incoming automation can offer all of them.
     *
     * Not the same list as `sourceFields`: reading the foreign system, those are its response
     * fields, and the DataGerry fields are where the values go rather than where they come from.
     */
    @Input() public objectTypeFields: AutomationField[] = [];

    /** What the calls before this step answered, as the references that fetch those answers. */
    @Input() public valueSources: ValueSource[] = [];

    /** Every value the sequence writes, which is the whole of what an outgoing automation does. */
    @Input() public sequenceBindings: SequenceBinding[] = [];

    /**
     * Bound by the shell, read by nobody since the identification marker left this screen and the
     * written fields stopped being read off the target catalog.
     *
     * Kept declared only so the shell's template still compiles while it is edited elsewhere; all
     * three inputs and the autoMap output can go once those bindings are gone.
     */
    @Input() public targetFields: TargetField[] = [];
    @Input() public matchableTargets: string[] = [];
    @Input() public matchingRelevant = false;

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();
    @Output() public autoMap = new EventEmitter<void>();

    public readonly operatorChoices = RULE_OPERATOR_CHOICES;
    public readonly ruleNeedsValue = ruleNeedsValue;
    public readonly literalChoice = LITERAL_CHOICE;
    public readonly pathChoice = PATH_CHOICE;

    /**
     * The calls the sequence makes, so a hand-written path can say which answer it reads.
     *
     * A reference is a colour and a path; the colour is what ties it to a call, and nothing else
     * on this screen knows which colours are in play.
     */
    @Input() public sequenceCalls: SequenceCall[] = [];

    /** Rows whose value adjustment is open, so the table stays compact by default. */
    private expanded = new Set<string>();

    /** Rows that have been through the check once, so a folded row is not unfolded again. */
    private seeded = new Set<string>();

    /** Derived view data, rebuilt only when an input actually changed - see ngDoCheck. */
    public bindingRows: BindingRow[] = EMPTY_BINDING_ROWS;
    public bindingGroups: BindingGroup[] = EMPTY_BINDING_GROUPS;
    public writeRows: WriteRow[] = EMPTY_WRITE_ROWS;
    public valueGroups: ValueSourceGroup[] = [];

    /** True while DataGerry is the side being written, which is the screen that decides. */
    public incoming = false;

    /** How many fields of the object type are given a value, for the count above the table. */
    public writtenCount = 0;

    private seenMapping: AutomationMappingEntry[] | null = null;
    private seenAdjustments: Record<string, AutomationValueTransform> | null = null;
    private seenObjectTypeFields: AutomationField[] | null = null;
    private seenValueSources: ValueSource[] | null = null;
    private seenBindings: SequenceBinding[] | null = null;
    private seenIncoming: boolean | null = null;

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    /**
     * Rebuilds the derived data when, and only when, one of its inputs changed.
     *
     * The shell hands the same definition object back after every edit and replaces the arrays
     * inside it, so ngOnChanges never fires. Deriving in the template instead would rebuild every
     * row on every change detection run, which is what once made this step lock up.
     */
    public ngDoCheck(): void {
        const mapping = this.definition?.mapping ?? null;
        const adjustments = this.definition?.adjustments ?? null;
        const incoming = this.definition?.direction === 'incoming';

        if (mapping === this.seenMapping
            && adjustments === this.seenAdjustments
            && incoming === this.seenIncoming
            && this.objectTypeFields === this.seenObjectTypeFields
            && this.valueSources === this.seenValueSources
            && this.sequenceBindings === this.seenBindings) {
            return;
        }

        // The picker's options outlive the rows: what a field is given changes on every click, what
        // the sequence answers only when the sequence itself does.
        if (this.valueSources !== this.seenValueSources) {
            this.valueGroups = this.groupValues();
        }

        this.seenMapping = mapping;
        this.seenAdjustments = adjustments;
        this.seenIncoming = incoming;
        this.seenObjectTypeFields = this.objectTypeFields;
        this.seenValueSources = this.valueSources;
        this.seenBindings = this.sequenceBindings;
        this.incoming = incoming;
        this.rebuild();
    }


    private rebuild(): void {
        const mapping = this.definition?.mapping ?? [];

        if (this.incoming) {
            this.bindingRows = EMPTY_BINDING_ROWS;
            this.bindingGroups = EMPTY_BINDING_GROUPS;
            this.writeRows = this.objectTypeFields.map(field => this.toWriteRow(field, mapping));
            this.writtenCount = this.writeRows.filter(row => !!row.entry).length;
            mapping.forEach(entry => this.seed(entry.target, entry.transform ?? null));

            return;
        }

        this.writeRows = EMPTY_WRITE_ROWS;
        this.writtenCount = 0;
        this.bindingRows = this.sequenceBindings.map(binding => this.toBindingRow(binding));
        this.bindingGroups = this.groupBindings(this.bindingRows);
        this.bindingRows.forEach(row => this.seed(row.key, row.transform));
    }


    /**
     * Shows an adjustment the definition already carries, the first time its row turns up.
     *
     * An adjustment folded away is an adjustment nobody reviews, and reviewing is what this screen
     * is for. Only the first sighting opens it, so a row the user folded stays folded.
     */
    private seed(key: string, transform: AutomationValueTransform | null): void {
        if (this.seeded.has(key)) {
            return;
        }

        this.seeded.add(key);

        if (transform) {
            this.expanded.add(key);
        }
    }


    private toBindingRow(binding: SequenceBinding): BindingRow {
        const transform = this.definition?.adjustments?.[binding.key] ?? null;
        const combined = binding.sources.length > 1;

        return {
            key: binding.key,
            call: binding.call,
            callIndex: binding.callIndex,
            path: binding.path,
            field: binding.field,
            entry: null,
            transform,
            adjusted: isActive(transform),
            combined,
            sources: binding.sources.map((source, index) => ({
                label: source.label || referenceLabel(source.reference),
                reference: source.reference,
                call: source.call,
                variable: combined ? `value${index + 1}` : 'value'
            }))
        };
    }


    /**
     * The rows under the call that writes them.
     *
     * Two calls can write the same path, so the path alone does not say what a row belongs to - and
     * an automation of four calls reads as one flat list of fields without the calls in it.
     */
    private groupBindings(rows: BindingRow[]): BindingGroup[] {
        const groups = new Map<string, BindingGroup>();

        for (const row of rows) {
            const group = groups.get(row.callIndex);

            if (group) {
                group.rows.push(row);
            } else {
                groups.set(row.callIndex, { call: row.call, callIndex: row.callIndex, rows: [row] });
            }
        }

        return [...groups.values()];
    }


    /**
     * One row per field of the object type, carrying whatever the definition already writes into it.
     *
     * A reference the sequence no longer offers is kept rather than quietly dropped: a call the user
     * moved or deleted must not silently unset the fields it fed, so the picker keeps standing on
     * it until somebody picks something else.
     */
    private toWriteRow(field: AutomationField, mapping: AutomationMappingEntry[]): WriteRow {
        const entry = mapping.find(candidate => candidate.target === field.name) ?? null;
        const source = entry?.sources[0];
        const kind = source ? sourceKindOf(source) : 'field';
        const reference = kind === 'reference' ? source?.reference ?? '' : '';
        const offered = this.valueSources.some(candidate => candidate.reference === reference);
        const written = !!source?.handWritten;
        const parsed = written ? ocParseReference(reference) : null;

        return {
            key: field.name,
            field: field.name,
            label: field.label || field.name,
            entry,
            transform: entry?.transform ?? null,
            adjusted: !!entry && hasActiveTransform(entry),
            choice: kind === 'literal' ? LITERAL_CHOICE : (written ? PATH_CHOICE : reference),
            literal: kind === 'literal' ? source?.literal ?? '' : '',
            tokens: reference ? tokensOf(reference) : [],
            // A hand-written path is the user's own claim about the answer, so it is never reported
            // as one the sequence dropped.
            unlisted: reference && !offered && !written ? referenceLabel(reference) : '',
            pathCall: parsed?.color ?? '',
            path: parsed?.field ?? '',
            // Both only so one adjustment template can serve either direction; a written field has
            // one source, so there is never anything to combine here.
            combined: false,
            sources: EMPTY_VIEWS
        };
    }


    /**
     * The offered values under the call that answers with them, and under the object they sit on.
     *
     * A call answers with far more paths than fit a dropdown anybody can read, and they differ at
     * the far end of a long path - so the route becomes the heading and the name stays on the row.
     */
    private groupValues(): ValueSourceGroup[] {
        return groupValueSources(this.valueSources);
    }

    /* ---------------------------------------------- WHAT DATAGERRY IS GIVEN ----------------------------------------- */

    /**
     * Gives a field a value, or takes it back out of the automation entirely.
     *
     * Not being written is the absence of an entry rather than an entry writing nothing, which is
     * what the mapping means everywhere else - so choosing nothing removes the row's entry, and its
     * adjustment with it.
     */
    public onWriteChoiceChanged(row: WriteRow, choice: string): void {
        if (!choice) {
            this.expanded.delete(row.field);
            this.definition.mapping = this.definition.mapping.filter(entry => entry.target !== row.field);
            this.emit();

            return;
        }

        if (choice === PATH_CHOICE) {
            this.writeHandWrittenPath(row, row.pathCall || this.sequenceCalls[0]?.color || '', row.path);

            return;
        }

        this.write(row, choice === LITERAL_CHOICE
            ? { field: '', origin: 'manual', confidence: 1, literal: row.literal }
            : { field: '', origin: 'manual', confidence: 1, reference: choice });
    }


    public onWritePathCallChanged(row: WriteRow, color: string): void {
        this.writeHandWrittenPath(row, color, row.path);
    }


    public onWritePathChanged(row: WriteRow, path: string): void {
        this.writeHandWrittenPath(row, row.pathCall || this.sequenceCalls[0]?.color || '', path);
    }


    /**
     * Builds a reference out of a call and a path somebody typed.
     *
     * Written even while the path is still empty, so the row keeps standing on this choice between
     * keystrokes rather than falling back to nothing and closing the input.
     */
    private writeHandWrittenPath(row: WriteRow, color: string, path: string): void {
        this.write(row, {
            field: '',
            origin: 'manual',
            confidence: 1,
            reference: ocFieldReference(color, 'response', (path ?? '').trim()),
            handWritten: true
        });
    }


    public onWriteLiteralChanged(row: WriteRow, literal: string): void {
        this.write(row, { field: '', origin: 'manual', confidence: 1, literal: literal ?? '' });
    }


    /** Puts one source into the field's entry, keeping the adjustment the entry already carries. */
    private write(row: WriteRow, source: AutomationMappingSource): void {
        const mapping = this.definition.mapping;

        this.definition.mapping = mapping.some(entry => entry.target === row.field)
            ? mapping.map(entry => entry.target === row.field ? { ...entry, sources: [source] } : entry)
            : [...mapping, { target: row.field, sources: [source] }];
        this.emit();
    }

    /* ------------------------------------------------- VALUE ADJUSTMENT --------------------------------------------- */

    public isExpanded(key: string): boolean {
        return this.expanded.has(key);
    }


    /**
     * Opens a row's adjustment, and starts a draft for it when there is none yet.
     *
     * The four handlers below each send the change to wherever this row's adjustment is kept: to
     * the mapping entry when the row is one, and under the row's key when no entry exists for it.
     */
    public onAdjustmentToggled(row: AdjustableRow): void {
        if (row.entry) {
            this.onToggleTransform(row.entry);

            return;
        }

        if (this.expanded.has(row.key)) {
            this.expanded.delete(row.key);

            return;
        }

        this.expanded.add(row.key);

        if (!row.transform) {
            this.writeAdjustment(row.key, createEmptyTransform());
        }
    }


    public onAdjustmentScriptChanged(row: AdjustableRow, script: string): void {
        if (row.entry) {
            this.onTransformScriptChanged(row.entry, script);

            return;
        }

        this.writeAdjustment(row.key, { enabled: row.transform?.enabled ?? true, script: script ?? '' });
    }


    public onAdjustmentEnabledChanged(row: AdjustableRow, enabled: boolean): void {
        if (row.entry) {
            this.onTransformEnabledChanged(row.entry, enabled);

            return;
        }

        this.writeAdjustment(row.key, { enabled, script: row.transform?.script ?? '' });
    }


    public onAdjustmentRemoved(row: AdjustableRow): void {
        if (row.entry) {
            this.onRemoveTransform(row.entry);

            return;
        }

        const { [row.key]: _dropped, ...rest } = this.definition.adjustments ?? {};

        this.expanded.delete(row.key);
        this.definition.adjustments = rest;
        this.emit();
    }


    public onToggleTransform(entry: AutomationMappingEntry): void {
        if (this.expanded.has(entry.target)) {
            this.expanded.delete(entry.target);

            return;
        }

        this.expanded.add(entry.target);

        if (!entry.transform) {
            this.replace(entry.target, current => ({ ...current, transform: createEmptyTransform() }));
        }
    }


    public onTransformScriptChanged(entry: AutomationMappingEntry, script: string): void {
        this.replace(entry.target, current => ({
            ...current,
            transform: { enabled: current.transform?.enabled ?? true, script: script ?? '' }
        }));
    }


    public onTransformEnabledChanged(entry: AutomationMappingEntry, enabled: boolean): void {
        this.replace(entry.target, current => ({
            ...current,
            transform: { enabled, script: current.transform?.script ?? '' }
        }));
    }


    public onRemoveTransform(entry: AutomationMappingEntry): void {
        this.expanded.delete(entry.target);
        this.definition.mapping = this.definition.mapping.map(current => {
            if (current.target !== entry.target) {
                return current;
            }

            const { transform: _dropped, ...rest } = current;

            return rest;
        });
        this.emit();
    }

    /* -------------------------------------------------- CONDITIONS -------------------------------------------------- */

    public onCombinatorChanged(combinator: AutomationRuleCombinator): void {
        this.definition.conditions.combinator = combinator;
        this.emit();
    }


    public onAddRule(): void {
        this.definition.conditions.rules = [
            ...this.definition.conditions.rules,
            { field: this.sourceFields[0]?.name ?? '', operator: 'equals', value: '' }
        ];
        this.emit();
    }


    public onRemoveRule(index: number): void {
        this.definition.conditions.rules = this.definition.conditions.rules.filter((_rule, i) => i !== index);
        this.emit();
    }


    public onRuleFieldChanged(index: number, field: string): void {
        this.patchRule(index, { field });
    }


    public onRuleOperatorChanged(index: number, operator: AutomationRuleOperator): void {
        const value = ruleNeedsValue(operator) ? this.definition.conditions.rules[index].value : '';
        this.patchRule(index, { operator, value });
    }


    public onRuleValueChanged(index: number, value: string): void {
        this.patchRule(index, { value: value ?? '' });
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public get combinedCount(): number {
        return this.bindingRows.filter(row => row.combined).length;
    }


    /**
     * How many values are adjusted, counting only what a row on the screen carries.
     *
     * An adjustment left behind by a call that has since been removed reaches nothing, so counting
     * it would report work the user cannot find.
     */
    public get adjustedCount(): number {
        return this.incoming
            ? this.definition.mapping.filter(entry => hasActiveTransform(entry)).length
            : this.bindingRows.filter(row => row.adjusted).length;
    }

    /* --------------------------------------------------- INTERNALS -------------------------------------------------- */

    /** Replaces the record rather than writing into it, so the rows are rebuilt on the next check. */
    private writeAdjustment(key: string, transform: AutomationValueTransform): void {
        this.definition.adjustments = { ...(this.definition.adjustments ?? {}), [key]: transform };
        this.emit();
    }


    private replace(
        target: string,
        change: (entry: AutomationMappingEntry) => AutomationMappingEntry
    ): void {
        this.definition.mapping = this.definition.mapping.map(entry =>
            entry.target === target ? change(entry) : entry
        );
        this.emit();
    }


    private patchRule(
        index: number,
        patch: Partial<{ field: string; operator: AutomationRuleOperator; value: string }>
    ): void {
        this.definition.conditions.rules = this.definition.conditions.rules.map((rule, i) =>
            i === index ? { ...rule, ...patch } : rule
        );
        this.emit();
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
