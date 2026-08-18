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

/** Shared fallback, so a row does not hand the template a new array on every check. */
const EMPTY_SOURCES: AutomationField[] = [];

/**
 * Step group 4 - the finished field mapping, and the value adjustment that reshapes it.
 *
 * Which source field feeds which target field is settled in the sequence, where a request value is
 * given a field reference. Repeating that decision here would put one answer in two places, so the
 * mapping is only read on this screen: what a user changes here is the JavaScript a value runs
 * through on its way over, and nothing else.
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

    /** Targets whose value adjustment is open, so the table stays compact by default. */
    private expanded = new Set<string>();

    /** Targets that have been through the check once, so a folded row is not unfolded again. */
    private seeded = new Set<string>();

    /** Derived view data, rebuilt only when an input actually changed - see ngDoCheck. */
    public rows: MappingRow[] = [];
    public spares: AutomationField[] = EMPTY_SOURCES;

    private seenMapping: AutomationMappingEntry[] | null = null;
    private seenSources: AutomationField[] | null = null;
    private seenTargets: TargetField[] | null = null;

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

        if (mapping === this.seenMapping
            && this.sourceFields === this.seenSources
            && this.targetFields === this.seenTargets) {
            return;
        }

        this.seenMapping = mapping;
        this.seenSources = this.sourceFields;
        this.seenTargets = this.targetFields;
        this.rebuild();
    }


    private rebuild(): void {
        const mapping = this.definition?.mapping ?? [];
        const used = mappedSources(mapping);

        this.rows = mapping.map(entry => this.toRow(entry));
        this.spares = this.sourceFields.filter(field => !used.has(field.name));
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
