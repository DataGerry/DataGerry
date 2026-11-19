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

/** A field of the report's type, as the type API returns it. */
export interface ReportFilterField {
    name: string;
    label?: string;
    type?: string;
    options?: Array<{ name?: string; label?: string; value?: unknown }>;
}

interface FilterRuleNode {
    field?: string;
    operator?: string;
    value?: unknown;
    condition?: string;
    rules?: FilterRuleNode[];
}

const NULL_OPERATORS = ['is null', 'is not null'];

/** Display labels only; the stored operator stays the symbol. */
const OPERATOR_LABELS: Record<string, string> = {
    '=': 'is',
    '!=': 'is not',
    'contains': 'contains',
    'like': 'contains, any case',
    'is null': 'is empty',
    'is not null': 'is not empty',
    'in': 'is any of',
    'not in': 'is none of',
    '<': 'less than',
    '>': 'more than',
    '<=': 'at most',
    '>=': 'at least'
};

const DATE_OPERATOR_LABELS: Record<string, string> = {
    '<': 'before',
    '>': 'after',
    '<=': 'on or before',
    '>=': 'on or after'
};

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

export function operatorLabel(operator: string, fieldType: string | undefined): string {
    return (fieldType === 'date' && DATE_OPERATOR_LABELS[operator]) || OPERATOR_LABELS[operator] || operator;
}

/**
 * Reads a condition tree as a sentence, e.g. "Server objects where RAM is at least 16 and Status is Active."
 * Rules without a value yet are left out.
 */
export function describeConditions(conditions: FilterRuleNode | null | undefined, fields: ReportFilterField[], subject: string): string {
    const fieldsByName = new Map(fields.map((field) => [field.name, field]));
    const sentence = describeRuleSet(conditions, fieldsByName, true);

    return sentence ? `${ subject } where ${ sentence }.` : `All ${ subject }.`;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function describeRuleSet(ruleSet: FilterRuleNode | null | undefined, fieldsByName: Map<string, ReportFilterField>, isRoot: boolean): string {
    const parts = (ruleSet?.rules ?? [])
        .map((rule) => Array.isArray(rule?.rules)
            ? describeRuleSet(rule, fieldsByName, false)
            : describeRule(rule, fieldsByName))
        .filter((part) => !!part);

    if (parts.length <= 1) {
        return parts[0] ?? '';
    }

    const joined = `${ parts.slice(0, -1).join(', ') } ${ ruleSet.condition === 'or' ? 'or' : 'and' } ${ parts[parts.length - 1] }`;

    return isRoot ? joined : `(${ joined })`;
}

function describeRule(rule: FilterRuleNode, fieldsByName: Map<string, ReportFilterField>): string {
    const field = fieldsByName.get(rule?.field);

    if (!field || !rule.operator) {
        return '';
    }

    const label = field.label || field.name;

    if (NULL_OPERATORS.includes(rule.operator)) {
        return `${ label } ${ operatorLabel(rule.operator, field.type) }`;
    }

    if (field.type === 'checkbox') {
        const isChecked = (rule.operator === '=') === (rule.value === true || rule.value === 'true');
        return `${ label } is ${ isChecked ? 'checked' : 'not checked' }`;
    }

    const values = (Array.isArray(rule.value) ? rule.value : [rule.value])
        .filter((value) => value !== null && value !== undefined && String(value).trim() !== '')
        .map((value) => describeValue(value, field));

    return values.length ? `${ label } ${ operatorLabel(rule.operator, field.type) } ${ values.join(', ') }` : '';
}

function describeValue(value: unknown, field: ReportFilterField): string {
    if (field.type === 'select' || field.type === 'radio') {
        const option = (field.options ?? []).find((entry) => (entry?.value !== undefined ? entry.value : entry?.name) === value);
        return option?.label || option?.name || String(value);
    }

    return field.type === 'number' || field.type === 'date' ? String(value) : `“${ value }”`;
}
