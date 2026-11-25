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

/** One piece of the report sentence; the kind decides how it is highlighted. */
export interface ReportSentencePart {
    kind: 'text' | 'type' | 'field' | 'value' | 'join';
    text: string;
    /** Free-text values are quoted when the sentence is copied. */
    quoted?: boolean;
}

export interface FilterRuleNode {
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
 * Reads a condition tree as sentence parts, e.g. "Server objects where RAM at least 16 and Status is Active."
 * Rules without a value yet are left out.
 */
export function describeConditionParts(conditions: FilterRuleNode | null | undefined, fields: ReportFilterField[], typeLabel?: string): ReportSentencePart[] {
    const fieldsByName = new Map(fields.map((field) => [field.name, field]));
    const subject: ReportSentencePart[] = typeLabel ? [{ kind: 'type', text: typeLabel }, textPart(' objects')] : [textPart('objects')];
    const filter = describeRuleSet(conditions, fieldsByName, true);

    return filter.length
        ? [...subject, textPart(' where '), ...filter, textPart('.')]
        : [textPart('All '), ...subject, textPart('.')];
}

/** Joins sentence parts back into plain text, quoting text values. */
export function sentenceText(parts: ReportSentencePart[]): string {
    return parts.map((part) => part.quoted ? `“${ part.text }”` : part.text).join('');
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function textPart(text: string): ReportSentencePart {
    return { kind: 'text', text };
}

function describeRuleSet(ruleSet: FilterRuleNode | null | undefined, fieldsByName: Map<string, ReportFilterField>, isRoot: boolean): ReportSentencePart[] {
    const parts = (ruleSet?.rules ?? [])
        .map((rule) => Array.isArray(rule?.rules)
            ? describeRuleSet(rule, fieldsByName, false)
            : describeRule(rule, fieldsByName))
        .filter((part) => part.length > 0);

    if (parts.length <= 1) {
        return parts[0] ?? [];
    }

    const join: ReportSentencePart = { kind: 'join', text: ruleSet.condition === 'or' ? 'or' : 'and' };
    const joined: ReportSentencePart[] = [];

    parts.forEach((part, index) => {
        if (index === parts.length - 1) {
            joined.push(textPart(' '), join, textPart(' '));
        } else if (index > 0) {
            joined.push(textPart(', '));
        }
        joined.push(...part);
    });

    return isRoot ? joined : [textPart('('), ...joined, textPart(')')];
}

function describeRule(rule: FilterRuleNode, fieldsByName: Map<string, ReportFilterField>): ReportSentencePart[] {
    const field = fieldsByName.get(rule?.field);

    if (!field || !rule.operator) {
        return [];
    }

    const fieldPart: ReportSentencePart = { kind: 'field', text: field.label || field.name };

    if (NULL_OPERATORS.includes(rule.operator)) {
        return [fieldPart, textPart(` ${ operatorLabel(rule.operator, field.type) }`)];
    }

    if (field.type === 'checkbox') {
        const isChecked = (rule.operator === '=') === (rule.value === true || rule.value === 'true');
        return [fieldPart, textPart(' is '), { kind: 'value', text: isChecked ? 'checked' : 'not checked' }];
    }

    const values = (Array.isArray(rule.value) ? rule.value : [rule.value])
        .filter((value) => value !== null && value !== undefined && String(value).trim() !== '')
        .map((value) => describeValue(value, field));

    if (!values.length) {
        return [];
    }

    return [
        fieldPart,
        textPart(` ${ operatorLabel(rule.operator, field.type) } `),
        ...values.flatMap((value, index) => index === 0 ? [value] : [textPart(', '), value])
    ];
}

function describeValue(value: unknown, field: ReportFilterField): ReportSentencePart {
    if (field.type === 'select' || field.type === 'radio') {
        const option = (field.options ?? []).find((entry) => (entry?.value !== undefined ? entry.value : entry?.name) === value);
        return { kind: 'value', text: option?.label || option?.name || String(value) };
    }

    const isPlainValue = field.type === 'number' || field.type === 'location' || field.type === 'date';

    return { kind: 'value', text: String(value), quoted: !isPlainValue };
}
