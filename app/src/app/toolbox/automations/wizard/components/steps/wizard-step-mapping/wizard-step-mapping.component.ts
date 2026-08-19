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
    createEmptyTransform,
    findSystemField,
    hasActiveTransform,
    mappedSources,
    ruleNeedsValue,
    sourceKindOf,
    systemFieldValue
} from '../../../models/automation-definition.model';
import { RULE_OPERATOR_CHOICES } from '../../../models/automation-wizard-step.model';
import { ocFieldReference, ocParseReference } from '../../../models/opencelium-connection.model';
import { TargetField } from '../../../models/target-catalog.model';
import {
    referenceLabel,
    SequenceCall,
    tokensOf,
    ValueSource,
    ValueToken
} from '../wizard-step-flow/wizard-step-flow.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One source of a target field, named the way the adjustment script sees it. */
interface MappingSourceView {
    field: string;
    label: string;

    /** `value`, or `value1`/`value2` when several sources meet in one field. */
    variable: string;

    /** What a system field sends without being read from anywhere - the object type, say. */
    fixed: string;
}


/** One target field as the table shows it, with its sources already named. */
interface MappingRow {
    entry: AutomationMappingEntry;
    target: string;

    /** Last segment of the target path - the name the target system knows the field by. */
    targetName: string;
    sources: MappingSourceView[];

    /** True when the target takes more than one value, so the script has to combine them. */
    combined: boolean;
}


/**
 * One field of the DataGerry object type, and what an incoming automation writes into it.
 *
 * Every field of the type gets a row whether it is written or not: deciding means seeing the
 * fields that stay empty as much as the ones that fill up.
 */
interface WriteRow {
    /** The DataGerry field name, which is also the target its mapping entry is keyed by. */
    field: string;
    label: string;

    /** The entry writing this field, or null while nothing writes it. */
    entry: AutomationMappingEntry | null;

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

    /* Both only so one adjustment template can serve either direction; a written field has one
       source, so there is never anything to combine here. */
    combined: boolean;
    sources: MappingSourceView[];
}


/** One heading of the value picker: the call that answered, and what it answered with. */
interface ValueGroup {
    name: string;
    items: ValueSource[];
}

/** Shared fallbacks, so a row does not hand the template a new array on every check. */
const EMPTY_SOURCES: AutomationField[] = [];
const EMPTY_ROWS: MappingRow[] = [];
const EMPTY_WRITE_ROWS: WriteRow[] = [];
const EMPTY_VIEWS: MappingSourceView[] = [];

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

/**
 * Step group 4 - what each field is given, and the value adjustment that reshapes it.
 *
 * The direction decides what there is to do here, because it decides what the sequence already
 * settled. Reading DataGerry, the field pairs were settled in the sequence, where a request value
 * was given a field reference; repeating that decision here would put one answer in two places, so
 * that mapping is only read on this screen and the adjustment script is all a user changes.
 *
 * Writing DataGerry, the sequence only fetched - nothing has been said yet about what lands in the
 * object. So this screen lists the whole object type, one row per field, and each field is given
 * nothing, a typed value, or one of the answers the sequence collected.
 *
 * Either way an entry is keyed by the side being written: for an outgoing automation that is a
 * field path of the target system, for an incoming one the DataGerry field's technical name. Which
 * is what a field binding is - one target and a list of sources the script sees as VAR_0, VAR_1 -
 * so two fields combining into one is an ordinary row rather than a special case.
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
    @Input() public targetFields: TargetField[] = [];

    /**
     * Every field of the chosen object type, so an incoming automation can offer all of them.
     *
     * Not the same list as `sourceFields`: reading the foreign system, those are its response
     * fields, and the DataGerry fields are where the values go rather than where they come from.
     */
    @Input() public objectTypeFields: AutomationField[] = [];

    /** What the calls before this step answered, as the references that fetch those answers. */
    @Input() public valueSources: ValueSource[] = [];

    /**
     * Bound by the shell, read by nobody since the identification marker left this screen.
     *
     * Kept declared only so the shell's template still compiles while it is edited elsewhere; both
     * inputs and the autoMap output can go once those bindings are gone.
     */
    @Input() public matchableTargets: string[] = [];
    @Input() public matchingRelevant = false;

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();
    @Output() public autoMap = new EventEmitter<void>();

    public readonly operatorChoices = RULE_OPERATOR_CHOICES;
    public readonly ruleNeedsValue = ruleNeedsValue;
    public readonly hasActiveTransform = hasActiveTransform;
    public readonly literalChoice = LITERAL_CHOICE;
    public readonly pathChoice = PATH_CHOICE;

    /**
     * The calls the sequence makes, so a hand-written path can say which answer it reads.
     *
     * A reference is a colour and a path; the colour is what ties it to a call, and nothing else
     * on this screen knows which colours are in play.
     */
    @Input() public sequenceCalls: SequenceCall[] = [];

    /** Targets whose value adjustment is open, so the table stays compact by default. */
    private expanded = new Set<string>();

    /** Targets that have been through the check once, so a folded row is not unfolded again. */
    private seeded = new Set<string>();

    /** Derived view data, rebuilt only when an input actually changed - see ngDoCheck. */
    public rows: MappingRow[] = EMPTY_ROWS;
    public writeRows: WriteRow[] = EMPTY_WRITE_ROWS;
    public valueGroups: ValueGroup[] = [];
    public spares: AutomationField[] = EMPTY_SOURCES;

    /** True while DataGerry is the side being written, which is the screen that decides. */
    public incoming = false;

    /** How many fields of the object type are given a value, for the count above the table. */
    public writtenCount = 0;

    private seenMapping: AutomationMappingEntry[] | null = null;
    private seenSources: AutomationField[] | null = null;
    private seenTargets: TargetField[] | null = null;
    private seenObjectTypeFields: AutomationField[] | null = null;
    private seenValueSources: ValueSource[] | null = null;
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
        const incoming = this.definition?.direction === 'incoming';

        if (mapping === this.seenMapping
            && incoming === this.seenIncoming
            && this.sourceFields === this.seenSources
            && this.targetFields === this.seenTargets
            && this.objectTypeFields === this.seenObjectTypeFields
            && this.valueSources === this.seenValueSources) {
            return;
        }

        // The picker's options outlive the rows: what a field is given changes on every click, what
        // the sequence answers only when the sequence itself does.
        if (this.valueSources !== this.seenValueSources) {
            this.valueGroups = this.groupValues();
        }

        this.seenMapping = mapping;
        this.seenIncoming = incoming;
        this.seenSources = this.sourceFields;
        this.seenTargets = this.targetFields;
        this.seenObjectTypeFields = this.objectTypeFields;
        this.seenValueSources = this.valueSources;
        this.incoming = incoming;
        this.rebuild();
    }


    private rebuild(): void {
        const mapping = this.definition?.mapping ?? [];

        if (this.incoming) {
            this.rows = EMPTY_ROWS;
            this.spares = EMPTY_SOURCES;
            this.writeRows = this.objectTypeFields.map(field => this.toWriteRow(field, mapping));
            this.writtenCount = this.writeRows.filter(row => !!row.entry).length;
        } else {
            const used = mappedSources(mapping);

            this.writeRows = EMPTY_WRITE_ROWS;
            this.writtenCount = 0;
            this.rows = mapping.map(entry => this.toRow(entry));
            this.spares = this.sourceFields.filter(field => !used.has(field.name));
        }

        mapping.forEach(entry => this.seed(entry));
    }


    /**
     * Shows an adjustment the definition already carries, the first time its target turns up.
     *
     * An adjustment folded away is an adjustment nobody reviews, and reviewing is what this screen
     * is for. Only the first sighting opens it, so a row the user folded stays folded.
     */
    private seed(entry: AutomationMappingEntry): void {
        if (this.seeded.has(entry.target)) {
            return;
        }

        this.seeded.add(entry.target);

        if (entry.transform) {
            this.expanded.add(entry.target);
        }
    }


    private toRow(entry: AutomationMappingEntry): MappingRow {
        const combined = entry.sources.length > 1;

        return {
            entry,
            target: entry.target,
            targetName: this.targetNameOf(entry.target),
            combined,
            sources: entry.sources.map((source, index) => ({
                field: source.field,
                label: this.labelOf(source.field),
                variable: combined ? `value${index + 1}` : 'value',
                fixed: this.fixedValueOf(source.field)
            }))
        };
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
            field: field.name,
            label: field.label || field.name,
            entry,
            choice: kind === 'literal' ? LITERAL_CHOICE : (written ? PATH_CHOICE : reference),
            literal: kind === 'literal' ? source?.literal ?? '' : '',
            tokens: reference ? tokensOf(reference) : [],
            // A hand-written path is the user's own claim about the answer, so it is never reported
            // as one the sequence dropped.
            unlisted: reference && !offered && !written ? referenceLabel(reference) : '',
            pathCall: parsed?.color ?? '',
            path: parsed?.field ?? '',
            combined: false,
            sources: EMPTY_VIEWS
        };
    }


    /** The offered values under the call that answers with them, in the order they arrive. */
    private groupValues(): ValueGroup[] {
        const groups: ValueGroup[] = [];

        for (const source of this.valueSources) {
            const last = groups[groups.length - 1];

            if (last && last.name === source.group) {
                last.items.push(source);
            } else {
                groups.push({ name: source.group, items: [source] });
            }
        }

        return groups;
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

    public isExpanded(target: string): boolean {
        return this.expanded.has(target);
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
        return this.rows.filter(row => row.combined).length;
    }


    public get adjustedCount(): number {
        return this.definition.mapping.filter(entry => hasActiveTransform(entry)).length;
    }


    public labelOf(field: string): string {
        return this.sourceFields.find(candidate => candidate.name === field)?.label ?? field;
    }

    /* --------------------------------------------------- INTERNALS -------------------------------------------------- */

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


    /** What a source sends when it is not read from anywhere - the chosen object type, say. */
    private fixedValueOf(field: string): string {
        const systemField = findSystemField(field);

        return systemField?.kind === 'constant' ? systemFieldValue(systemField, this.definition) : '';
    }


    /** The catalog's name for a target, falling back to the path's last segment. */
    private targetNameOf(path: string): string {
        return this.targetFields.find(field => field.path === path)?.name ?? this.leafOf(path);
    }


    private leafOf(path: string): string {
        return path.slice(path.lastIndexOf('.') + 1);
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
