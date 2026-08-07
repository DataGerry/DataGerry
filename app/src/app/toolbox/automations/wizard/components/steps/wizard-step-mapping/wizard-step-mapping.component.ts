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
export class WizardStepMappingComponent {

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
     */
    public targetChoices(source: string): TargetChoice[] {
        const takenBy = new Map(
            this.definition.mapping
                .filter(entry => entry.source !== source && entry.target)
                .map(entry => [entry.target, entry.source])
        );

        return this.targetFields.map(field => {
            const owner = takenBy.get(field.path);

            return {
                path: field.path,
                label: owner ? `${field.path} - used by ${this.labelOf(owner)}` : field.path,
                disabled: !!owner
            };
        });
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
        return this.showOnlyUnresolved
            ? this.definition.mapping.filter(entry => !entry.target)
            : this.definition.mapping;
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
