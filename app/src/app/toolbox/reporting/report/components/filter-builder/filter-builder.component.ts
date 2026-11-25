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
import { Component, Input, OnInit, OnChanges, SimpleChanges, EventEmitter, Output } from '@angular/core';
import { QueryBuilderConfig, QueryBuilderClassNames, Rule } from 'shout-angular-query-builder';
import { operatorLabel } from './report-filter-labels';

/** Own class names for every slot, so the library's default look does not apply. */
const QUERY_CLASS_NAMES: QueryBuilderClassNames = {
    arrowIconButton: 'qb-arrow-button',
    arrowIcon: 'qb-arrow-icon',
    removeIcon: 'qb-icon',
    addIcon: 'qb-icon',
    button: 'qb-button',
    buttonGroup: 'qb-button-group',
    removeButton: 'qb-remove-button',
    removeButtonSize: 'qb-remove-button',
    switchRow: 'qb-switch-row',
    switchGroup: 'qb-switch-group',
    switchLabel: 'qb-switch-label',
    switchRadio: 'qb-switch-radio',
    switchControl: 'qb-switch-control',
    rightAlign: 'qb-end',
    transition: 'qb-transition',
    collapsed: 'qb-collapsed',
    treeContainer: 'qb-tree-container',
    tree: 'qb-tree',
    row: 'qb-row',
    connector: 'qb-connector',
    rule: 'qb-rule',
    ruleSet: 'qb-ruleset',
    invalidRuleSet: 'qb-ruleset--invalid',
    emptyWarning: 'qb-empty-warning',
    fieldControl: 'qb-control',
    fieldControlSize: 'qb-control-size',
    entityControl: 'qb-control',
    entityControlSize: 'qb-control-size',
    operatorControl: 'qb-control',
    operatorControlSize: 'qb-control-size',
    inputControl: 'qb-control',
    inputControlSize: 'qb-control-size'
};

const FIELD_TYPE_ICONS: Record<string, string> = {
    number: 'fas fa-hashtag',
    date: 'far fa-calendar',
    category: 'fas fa-list-ul',
    boolean: 'far fa-check-square'
};

@Component({
    selector: 'app-filter-builder',
    templateUrl: './filter-builder.component.html',
    styleUrls: ['./filter-builder.component.scss'],
    standalone: false
})
export class FilterBuilderComponent implements OnInit, OnChanges {
    @Input() fields: Array<{ name: string; label: string; type?: string; options?: Array<{ name: string; value: any }> }> = [];
    @Output() conditionsChange = new EventEmitter<any>();
    @Output() filterBuilderValidation = new EventEmitter<any>();
    @Input() conditions: any; // Receive conditions from parent component



    public query = { condition: 'and', rules: [] };
    public config: QueryBuilderConfig = {
        fields: {},
        coerceValueForOperator: (operator, value, rule) => this.coerceValueForOperator(operator, value, rule)
    };
    public classNames: QueryBuilderClassNames = QUERY_CLASS_NAMES;
    public showQueryBuilder = true;

    /* --------------------------------------------------- LIFECYCLE METHODS -------------------------------------------------- */


    ngOnInit(): void {
        this.initializeConfig();
        if (this.conditions) {
            this.query = { ...this.conditions }; // Initialize with edit conditions if available
        }
    }


    ngOnChanges(changes: SimpleChanges): void {
        if (changes.fields && !changes.fields.firstChange) {
            // Hide the query-builder component to force reinitialization
            this.showQueryBuilder = false;

            // Reset the entire query object
            this.query = {
                condition: 'and',
                rules: []
            };

            // Reinitialize the configuration
            this.initializeConfig();

            // Use setTimeout to re-show the component after it has been destroyed
            setTimeout(() => {
                this.showQueryBuilder = true;
            }, 0);
        }
    }

    /* --------------------------------------------------- QUERY CONFIGURATIONS -------------------------------------------------- */


    /**
     * Initializes the configuration for query fields based on available fields, setting default operators and types.
     */
    private initializeConfig(): void {
        if (this.fields && this.fields.length > 0) {
            const configFields: { [key: string]: any } = {};

            this.fields.forEach(field => {
                let fieldType = field.type;
                let operators = ['=', '!=', 'contains', 'is null', 'is not null', 'like']; // Default operators for non-numeric types

                if (fieldType === 'ref') {
                    fieldType = 'number';
                    operators = ['=', '!=', 'in', 'not in', 'is null', 'is not null'];
                  }
               else if (fieldType === 'number' || fieldType === 'date') {
                    operators = ['=', '!=', '<', '>', '<=', '>='];
                }
                else if (fieldType === 'select') {
                    operators = ['=', '!=', 'in', 'not in'];
                    fieldType = 'category';
                } else if (fieldType === 'checkbox') {
                    fieldType = 'boolean';
                    operators = ['=', '!='];
                } else if (fieldType === 'radio') {
                    fieldType = 'category';

                }
                else {
                    // Treat any other type as 'string'
                    fieldType = 'string';
                }

                configFields[field.name] = {
                    name: field.label,
                    type: fieldType,
                    operators: operators,
                    defaultValue: '',
                    ...(fieldType === 'category' && field.options ? { options: this.normalizeCategoryOptions(field.options) } : {})
                };
            });

            this.config.fields = configFields;
        } else {
            // Reset the query if no fields are available
            this.query = {
                condition: 'and',
                rules: []
            };
            this.config.fields = {};
        }
    }

    /**
     * Normalizes option objects for query-builder category inputs.
     * Query-builder uses `opt.value` for the outgoing rule value.
     */
    private normalizeCategoryOptions(options: Array<{ name?: string; label?: string; value?: any }>): Array<{ name: string; value: any }> {
        return options.map((option) => {
            const resolvedValue = option?.value !== undefined ? option.value : option?.name;
            const resolvedName = option?.label || option?.name || String(resolvedValue ?? '');

            return {
                name: resolvedName,
                value: resolvedValue
            };
        }).filter((option) => option.value !== undefined);
    }


    /**
     * Keeps the value shape in line with the operator: a list for "is any of" / "is none of", one value otherwise.
     * A list of several values cannot become one value, so it is cleared.
     */
    private coerceValueForOperator(operator: string, value: unknown, rule: Rule): unknown {
        const takesList = this.takesList(operator, rule.field);

        if (takesList && !Array.isArray(value)) {
            return value === '' || value === null || value === undefined ? [] : [value];
        }

        if (!takesList && Array.isArray(value)) {
            return value.length === 1 ? value[0] : '';
        }

        return value;
    }


    /** Mirrors the library, which only shows a multi-select for these field types. */
    private takesList(operator: string, fieldName: string): boolean {
        const fieldType = this.config.fields[fieldName]?.type;

        return (operator === 'in' || operator === 'not in') && (fieldType === 'category' || fieldType === 'boolean');
    }


    /**
     * Emits an updated query when conditions change.
     */
    onQueryChange(): void {
        this.conditionsChange.emit(this.query);
        this.isAnyFieldEmpty()
    }


    /* --------------------------------------------------- TEMPLATE HELPER -------------------------------------------------- */


    operatorLabel(operator: string, fieldName: string): string {
        const fieldType = this.config.fields[fieldName]?.type;

        return operatorLabel(operator, fieldType);
    }


    fieldTypeIcon(fieldType: string | undefined): string {
        return FIELD_TYPE_ICONS[fieldType] ?? 'fas fa-font';
    }


    valueLabel(rule: { field: string }): string {
        return `Value for ${ this.config.fields[rule.field]?.name ?? 'this rule' }`;
    }


    /**
     * Determines if the value field should be hidden based on the selected operator.
     */
    shouldHideValueField(operator: string): boolean {
        return operator === 'is null' || operator === 'is not null';
    }


    /**
     * Checks if any field in the query rules is empty (including nested rules and empty groups) and emits validation status.
     * Returns true only if both conditions are true or false.
     */
    isAnyFieldEmpty() {
        const checkForEmptyFields = (rules: any[]): boolean => {
            for (const rule of rules) {
                if (rule.rules) {
                    // If it's a nested group, check if it's empty or has empty fields
                    if (rule.rules.length === 0 || checkForEmptyFields(rule.rules)) {
                        return true;
                    }
                } else if (
                    rule.operator !== 'is null' &&
                    rule.operator !== 'is not null' &&
                    (
                        rule.value === '' ||
                        rule.value === undefined ||
                        rule.value === null ||
                        (Array.isArray(rule.value) && rule.value.length === 0) ||
                        (Array.isArray(rule.value) && !this.takesList(rule.operator, rule.field))
                    )
                ) {
                    // If the value is empty and the operator is not null checks, return true
                    return true;
                }
            }
            return false;
        };

        const hasEmptyFields = checkForEmptyFields(this.query.rules);
        this.filterBuilderValidation.emit(!hasEmptyFields);
    }
}
