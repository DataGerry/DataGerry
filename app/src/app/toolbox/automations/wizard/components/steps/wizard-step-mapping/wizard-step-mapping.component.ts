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
    AutomationRuleCombinator,
    AutomationRuleOperator,
    ruleNeedsValue
} from '../../../models/automation-definition.model';
import { RULE_OPERATOR_CHOICES } from '../../../models/automation-wizard-step.model';
import { TargetField } from '../../../models/target-catalog.model';
/* ------------------------------------------------------------------------------------------------------------------ */

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

    /** Hides pairs the wizard already resolved, so only the open ones remain. */
    public showOnlyUnresolved = false;

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


    /** Target fields not yet taken by another pair, plus the one this pair holds. */
    public availableTargets(source: string): TargetField[] {
        const taken = new Set(
            this.definition.mapping
                .filter(entry => entry.source !== source && entry.target)
                .map(entry => entry.target)
        );

        return this.targetFields.filter(field => !taken.has(field.path));
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


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
