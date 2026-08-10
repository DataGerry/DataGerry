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
    AutomationRuleCombinator,
    AutomationRuleOperator,
    createEmptyTransform,
    findSystemField,
    hasActiveTransform,
    mappedSources,
    ruleNeedsValue,
    systemFieldValue
} from '../../../models/automation-definition.model';
import { RULE_OPERATOR_CHOICES } from '../../../models/automation-wizard-step.model';
import { TargetField } from '../../../models/target-catalog.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One entry of the target dropdown: every field the action accepts, taken ones included. */
interface TargetChoice {
    path: string;
    label: string;

    /** True for a field another entry already writes to - shown, but not selectable twice. */
    disabled: boolean;
}


/** One target field as the table shows it, with its sources already named. */
interface MappingRow {
    entry: AutomationMappingEntry;
    target: string;
    sources: Array<{ field: string; label: string; variable: string; fixed: string }>;

    /** True when the target takes more than one value, so the script has to combine them. */
    combined: boolean;
    identifies: boolean;
    canIdentify: boolean;
}

/** Shared fallbacks, so a row does not hand ng-select a new array on every check. */
const EMPTY_CHOICES: TargetChoice[] = [];
const EMPTY_SOURCES: AutomationField[] = [];

/**
 * Step group 4 - which values end up in which field of the target system.
 *
 * Grouped by target rather than by source, because that is what a field binding is: one target and
 * a list of sources, which the script sees in order as VAR_0, VAR_1. Two fields combining into one
 * is therefore an ordinary row here rather than a special case.
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

    /** Target field names the lookup can search by; empty when the system offers no search. */
    @Input() public matchableTargets: string[] = [];

    /** False for an automation that only ever adds, where nothing has to be recognised. */
    @Input() public matchingRelevant = false;

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();

    /** Asks the shell to suggest targets for whatever is still unassigned. */
    @Output() public autoMap = new EventEmitter<void>();

    public readonly operatorChoices = RULE_OPERATOR_CHOICES;
    public readonly ruleNeedsValue = ruleNeedsValue;
    public readonly hasActiveTransform = hasActiveTransform;

    /** Targets whose value adjustment is open, so the table stays compact by default. */
    private expanded = new Set<string>();

    /** Derived view data, rebuilt only when an input actually changed - see ngDoCheck. */
    public rows: MappingRow[] = [];
    public spares: AutomationField[] = EMPTY_SOURCES;
    private choices = new Map<string, TargetChoice[]>();

    private seenMapping: AutomationMappingEntry[] | null = null;
    private seenSources: AutomationField[] | null = null;
    private seenTargets: TargetField[] | null = null;
    private seenIdentifier = '';

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    /**
     * Rebuilds the derived data when, and only when, one of its inputs changed.
     *
     * The shell hands the same definition object back after every edit and replaces the arrays
     * inside it, so ngOnChanges never fires. Deriving in the template instead would rebuild every
     * dropdown on every change detection run, which is what once made this step lock up.
     */
    public ngDoCheck(): void {
        const mapping = this.definition?.mapping ?? null;

        const identifier = this.definition?.matching?.identifyBy ?? '';

        if (mapping === this.seenMapping
            && this.sourceFields === this.seenSources
            && this.targetFields === this.seenTargets
            && identifier === this.seenIdentifier) {
            return;
        }

        this.seenMapping = mapping;
        this.seenSources = this.sourceFields;
        this.seenTargets = this.targetFields;
        this.seenIdentifier = identifier;
        this.rebuild();
    }


    private rebuild(): void {
        const mapping = this.definition?.mapping ?? [];
        const used = mappedSources(mapping);
        const taken = new Set(mapping.map(entry => entry.target));

        this.rows = mapping.map(entry => this.toRow(entry));
        this.spares = this.sourceFields.filter(field => !used.has(field.name));

        this.choices = new Map(mapping.map(entry => [entry.target, this.targetFields.map(field => {
            const blocked = taken.has(field.path) && field.path !== entry.target;

            return {
                path: field.path,
                label: blocked ? `${field.path} - already in use` : field.path,
                disabled: blocked
            };
        })]));
    }


    private toRow(entry: AutomationMappingEntry): MappingRow {
        const combined = entry.sources.length > 1;

        return {
            entry,
            target: entry.target,
            combined,
            identifies: !!this.definition.matching.identifyBy
                && entry.sources.some(source => source.field === this.definition.matching.identifyBy),
            canIdentify: !combined && this.matchableTargets.includes(this.leafOf(entry.target)),
            sources: entry.sources.map((source, index) => ({
                field: source.field,
                label: this.labelOf(source.field),
                variable: combined ? `value${index + 1}` : 'value',
                fixed: this.fixedValueOf(source.field)
            }))
        };
    }

    /* ---------------------------------------------------- SOURCES --------------------------------------------------- */

    /** Adds a source to a target, which turns a plain copy into a combination. */
    public onAddSource(target: string, field: string): void {
        if (!field) {
            return;
        }

        this.replace(target, entry => ({
            ...entry,
            sources: [...entry.sources, { field, origin: 'manual' as const, confidence: 1 }]
        }));
        this.definition.unmapped = this.definition.unmapped.filter(name => name !== field);
    }


    public onRemoveSource(target: string, field: string): void {
        const entry = this.definition.mapping.find(candidate => candidate.target === target);

        if (!entry) {
            return;
        }

        const sources = entry.sources.filter(source => source.field !== field);

        // A target nobody writes to is not a row with a gap, it is no row.
        this.definition.mapping = sources.length > 0
            ? this.definition.mapping.map(candidate =>
                candidate.target === target ? { ...candidate, sources } : candidate)
            : this.definition.mapping.filter(candidate => candidate.target !== target);

        if (!this.definition.unmapped.includes(field)) {
            this.definition.unmapped = [...this.definition.unmapped, field];
        }

        this.emit();
    }


    /** Moves a source within its target, which is what decides value1 from value2. */
    public onMoveSource(target: string, field: string, by: number): void {
        this.replace(target, entry => {
            const sources = [...entry.sources];
            const from = sources.findIndex(source => source.field === field);
            const to = from + by;

            if (from === -1 || to < 0 || to >= sources.length) {
                return entry;
            }

            [sources[from], sources[to]] = [sources[to], sources[from]];

            return { ...entry, sources };
        });
    }


    /** Gives a source that had no target one, starting a new row or joining an existing one. */
    public onAssign(field: string, target: string): void {
        if (!target) {
            return;
        }

        const existing = this.definition.mapping.find(entry => entry.target === target);

        this.definition.mapping = existing
            ? this.definition.mapping.map(entry => entry.target === target
                ? { ...entry, sources: [...entry.sources, { field, origin: 'manual' as const, confidence: 1 }] }
                : entry)
            : [...this.definition.mapping, {
                target,
                sources: [{ field, origin: 'manual' as const, confidence: 1 }]
            }];

        this.definition.unmapped = this.definition.unmapped.filter(name => name !== field);
        this.emit();
    }


    public onTargetChanged(previous: string, target: string): void {
        if (!target || target === previous) {
            return;
        }

        this.definition.mapping = this.definition.mapping.map(entry =>
            entry.target === previous ? { ...entry, target } : entry
        );
        this.emit();
    }

    /* ------------------------------------------------- IDENTIFICATION ----------------------------------------------- */

    public onIdentifyBy(row: MappingRow): void {
        this.definition.matching = {
            ...this.definition.matching,
            identifyBy: row.identifies ? '' : (row.sources[0]?.field ?? '')
        };
        this.emit();
    }


    public get identifierMissing(): boolean {
        return this.matchingRelevant && !this.definition.matching.identifyBy;
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

    public targetChoices(target: string): TargetChoice[] {
        return this.choices.get(target) ?? EMPTY_CHOICES;
    }


    /** Targets nothing writes to yet, offered to a source that is still unassigned. */
    public get freeTargets(): TargetChoice[] {
        const taken = new Set(this.definition.mapping.map(entry => entry.target));

        return this.targetFields
            .filter(field => !taken.has(field.path))
            .map(field => ({ path: field.path, label: field.path, disabled: false }));
    }


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


    private leafOf(path: string): string {
        return path.slice(path.lastIndexOf('.') + 1);
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
