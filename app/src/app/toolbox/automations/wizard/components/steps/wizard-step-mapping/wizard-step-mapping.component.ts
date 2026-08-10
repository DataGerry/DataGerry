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

    /** True for a field another pair already writes to - shown, but not selectable twice. */
    disabled: boolean;
}

/** Shared fallback, so a row without choices does not hand ng-select a new array on every check. */
const EMPTY_CHOICES: TargetChoice[] = [];

/**
 * Step group 4 - how source and target fields line up, and which objects take part.
 *
 * Only fields the wizard could not match automatically need attention here. Conditions are built
 * visually; the user never writes an expression.
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

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();

    /** Asks the shell to re-run automatic matching for entries that are still empty. */
    @Output() public autoMap = new EventEmitter<void>();

    public readonly operatorChoices = RULE_OPERATOR_CHOICES;
    public readonly ruleNeedsValue = ruleNeedsValue;
    public readonly hasActiveTransform = hasActiveTransform;

    /** Hides pairs the wizard already resolved, so only the open ones remain. */
    public showOnlyUnresolved = false;

    /** Sources whose value adjustment is currently open, so the table stays compact by default. */
    private expanded = new Set<string>();

    /** Dropdown items per source, kept as one stable array each - see ngDoCheck(). */
    private choicesBySource = new Map<string, TargetChoice[]>();

    /** The rows the table renders, cached for the same reason as the choices. */
    private rows: AutomationMappingEntry[] = [];

    /** Inputs the caches were built from, compared by reference on every check. */
    private seenMapping: AutomationMappingEntry[] | null = null;
    private seenTargetFields: TargetField[] | null = null;
    private seenSourceFields: AutomationField[] | null = null;
    private seenFilter = false;

    /* ------------------------------------------------- CHANGE TRACKING ---------------------------------------------- */

    /**
     * Rebuilds the derived view data when, and only when, one of its inputs actually changed.
     *
     * Deriving it in the template instead looks tidier but is what made this step unusable: Angular
     * re-evaluates a binding on every change detection run, so every dropdown received a freshly
     * built array several times per second. ng-select treats a new `items` array as a new list and
     * rebuilds its panel, which with one dropdown per mapped field is enough to lock up the page
     * while the user is choosing a target.
     *
     * ngOnChanges cannot do this job here: the shell hands back the same definition object after
     * every edit and only replaces the arrays inside it, so no input binding is ever seen to change.
     */
    public ngDoCheck(): void {
        const mapping = this.definition?.mapping ?? null;

        if (mapping === this.seenMapping
            && this.targetFields === this.seenTargetFields
            && this.sourceFields === this.seenSourceFields
            && this.showOnlyUnresolved === this.seenFilter) {
            return;
        }

        const rebuildChoices = mapping !== this.seenMapping
            || this.targetFields !== this.seenTargetFields
            || this.sourceFields !== this.seenSourceFields;

        this.seenMapping = mapping;
        this.seenTargetFields = this.targetFields;
        this.seenSourceFields = this.sourceFields;
        this.seenFilter = this.showOnlyUnresolved;

        if (rebuildChoices) {
            this.rebuildChoices();
        }

        this.rebuildRows();
    }


    /**
     * Builds the target dropdown for every source in one pass.
     *
     * Which fields are taken is the same question for all rows, so it is answered once here rather
     * than rebuilt per row as it was before.
     */
    private rebuildChoices(): void {
        const mapping = this.definition?.mapping ?? [];
        const owners = new Map(
            mapping.filter(entry => entry.target).map(entry => [entry.target, entry.source])
        );

        this.choicesBySource = new Map(mapping.map(entry => [
            entry.source,
            this.targetFields.map(field => {
                const owner = owners.get(field.path);
                const takenByOther = owner !== undefined && owner !== entry.source;

                return {
                    path: field.path,
                    label: takenByOther ? `${field.path} - used by ${this.labelOf(owner!)}` : field.path,
                    disabled: takenByOther
                };
            })
        ]));
    }


    private rebuildRows(): void {
        const mapping = this.definition?.mapping ?? [];

        this.rows = this.showOnlyUnresolved ? mapping.filter(entry => !entry.target) : mapping;
    }

    /* --------------------------------------------------- MAPPING ---------------------------------------------------- */

    public onTargetSelected(source: string, target: string): void {
        this.definition.mapping = this.definition.mapping.map(entry => entry.source === source
            ? { ...entry, target: target ?? '', origin: 'manual' as const, confidence: 1 }
            : entry
        );
        this.emit();
    }


    public labelOf(source: string): string {
        return this.sourceFields.find(field => field.name === source)?.label ?? source;
    }


    /**
     * What a pair sends, when that is not a field of the source object.
     *
     * A fixed value - the chosen object type, say - has no counterpart to read, so showing the
     * literal is the only way the user can tell what will arrive on the other side.
     */
    public fixedValueOf(source: string): string {
        const systemField = findSystemField(source);

        return systemField?.kind === 'constant' ? systemFieldValue(systemField, this.definition) : '';
    }


    public isFixedValue(source: string): boolean {
        return findSystemField(source)?.kind === 'constant';
    }


    /**
     * Every field the target action accepts.
     *
     * Fields another pair already writes to stay in the list but cannot be picked twice: hiding them
     * outright made the dropdown shrink as the mapping filled up, which reads as fields going
     * missing rather than as fields being in use.
     *
     * A lookup rather than a computation: the template binds this into ng-select, which must keep
     * receiving the same array as long as nothing changed. rebuildChoices() fills the map.
     */
    public targetChoices(source: string): TargetChoice[] {
        return this.choicesBySource.get(source) ?? EMPTY_CHOICES;
    }

    /* ------------------------------------------------- VALUE ADJUSTMENT --------------------------------------------- */

    public isExpanded(source: string): boolean {
        return this.expanded.has(source);
    }


    /** Opens the adjustment for a pair, starting an empty one the first time it is opened. */
    public onToggleTransform(entry: AutomationMappingEntry): void {
        if (this.expanded.has(entry.source)) {
            this.expanded.delete(entry.source);

            return;
        }

        this.expanded.add(entry.source);

        if (!entry.transform) {
            this.patchEntry(entry.source, { transform: createEmptyTransform() });
        }
    }


    public onTransformScriptChanged(entry: AutomationMappingEntry, script: string): void {
        this.patchEntry(entry.source, {
            transform: { enabled: entry.transform?.enabled ?? true, script: script ?? '' }
        });
    }


    public onTransformEnabledChanged(entry: AutomationMappingEntry, enabled: boolean): void {
        this.patchEntry(entry.source, { transform: { enabled, script: entry.transform?.script ?? '' } });
    }


    /** Removes the adjustment entirely, so the value is transferred as it is. */
    public onRemoveTransform(entry: AutomationMappingEntry): void {
        this.expanded.delete(entry.source);
        this.definition.mapping = this.definition.mapping.map(current => {
            if (current.source !== entry.source) {
                return current;
            }

            const { transform: _dropped, ...rest } = current;

            return rest;
        });
        this.emit();
    }


    private patchEntry(source: string, patch: Partial<AutomationMappingEntry>): void {
        this.definition.mapping = this.definition.mapping.map(entry =>
            entry.source === source ? { ...entry, ...patch } : entry
        );
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
        // Operators that compare against nothing must not keep a stale value.
        const value = ruleNeedsValue(operator) ? this.definition.conditions.rules[index].value : '';
        this.patchRule(index, { operator, value });
    }


    public onRuleValueChanged(index: number, value: string): void {
        this.patchRule(index, { value: value ?? '' });
    }


    private patchRule(index: number, patch: Partial<{ field: string; operator: AutomationRuleOperator; value: string }>): void {
        this.definition.conditions.rules = this.definition.conditions.rules.map((rule, i) =>
            i === index ? { ...rule, ...patch } : rule
        );
        this.emit();
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public get visibleMapping(): AutomationDefinition['mapping'] {
        return this.rows;
    }


    public get unresolvedCount(): number {
        return this.definition.mapping.filter(entry => !entry.target).length;
    }


    public get resolvedCount(): number {
        return this.definition.mapping.filter(entry => !!entry.target).length;
    }


    public get adjustedCount(): number {
        return this.definition.mapping.filter(entry => hasActiveTransform(entry)).length;
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
