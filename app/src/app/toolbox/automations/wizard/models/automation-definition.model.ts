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
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The business model of an automation.
 *
 * Users only ever work with the terms in this file - object types, fields, target systems and
 * actions. The technical OpenCelium connection JSON is derived from it by the
 * AutomationCompilerService, so nothing in the wizard UI needs to know how OpenCelium represents
 * a connection.
 */

/** Bumped whenever the persisted shape changes so the codec can migrate or reject old drafts. */
export const AUTOMATION_DEFINITION_VERSION = 1;

/** Data flow direction, always expressed relative to DataGerry. */
export type AutomationDirection = 'outgoing' | 'incoming';

/**
 * Trigger vocabulary of the wizard.
 *
 * Only MANUAL and SCHEDULED are executable - see SUPPORTED_TRIGGER_TYPES. The remaining members
 * exist so the UI can advertise them as upcoming; the compiler rejects them.
 */
export type AutomationTriggerType =
    | 'manual'
    | 'scheduled'
    | 'object_created'
    | 'object_updated'
    | 'webhook';

/** Trigger types the compiler can currently translate into an OpenCelium scheduler. */
export const SUPPORTED_TRIGGER_TYPES: ReadonlyArray<AutomationTriggerType> = ['manual', 'scheduled'];

/** Functional action performed on the target system. */
export type AutomationOperation = 'create' | 'update' | 'delete';

/** What an automation does when a single item of a run fails. */
export type AutomationErrorHandling = 'abort' | 'continue' | 'notify';

/** Whether a mapping entry was suggested automatically or set by hand. */
export type AutomationMappingOrigin = 'auto' | 'manual';

/** How the rules of a condition group are combined. */
export type AutomationRuleCombinator = 'and' | 'or';

/** Comparison operators offered by the visual rule builder - no expressions. */
export type AutomationRuleOperator =
    | 'equals'
    | 'not_equals'
    | 'contains'
    | 'not_contains'
    | 'starts_with'
    | 'ends_with'
    | 'is_empty'
    | 'is_not_empty'
    | 'greater_than'
    | 'less_than';

/** Operators that compare against nothing, so the UI hides their value input. */
export const VALUELESS_RULE_OPERATORS: ReadonlyArray<AutomationRuleOperator> = [
    'is_empty',
    'is_not_empty'
];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                    MODEL PARTS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

export interface AutomationTrigger {
    type: AutomationTriggerType;

    /** Cron expression, only meaningful for the 'scheduled' trigger. */
    cronExp: string;
}


export interface AutomationObjectType {
    typeId: number | null;
    name: string;
    label: string;
}


export interface AutomationField {
    /** Technical DataGerry field name, unique within its type. */
    name: string;
    label: string;

    /** DataGerry field type (text, date, ref, ...), used for mapping hints and the test step. */
    type: string;
}


export interface AutomationTarget {
    connectorId: number | null;
    connectorTitle: string;

    /** Invoker behind the connector - selects the adapter in the target catalog. */
    invokerName: string;
    operation: AutomationOperation;

    /**
     * The foreign system's own identifier for the object type.
     *
     * Needed to restrict what an incoming automation reads: an i-doit type id cannot be derived
     * from a DataGerry type, so the user supplies it. Empty means "read every object", which the
     * wizard warns about.
     */
    remoteObjectTypeId: string;
}


export interface AutomationMappingEntry {
    /** Field name on the source side of the automation. */
    source: string;

    /** Field path on the target side, as offered by the target catalog. */
    target: string;
    origin: AutomationMappingOrigin;

    /** Similarity score of an automatic suggestion, 0..1. Always 1 for manual entries. */
    confidence: number;
}


export interface AutomationConditionRule {
    /** Source field the rule applies to. */
    field: string;
    operator: AutomationRuleOperator;
    value: string;
}


export interface AutomationConditionGroup {
    combinator: AutomationRuleCombinator;
    negate: boolean;
    rules: AutomationConditionRule[];
}


export interface AutomationAdvancedSettings {
    retryCount: number;
    retryDelaySeconds: number;
    timeoutSeconds: number;

    /** Maps onto the OpenCelium scheduler's debugMode. */
    loggingEnabled: boolean;
    parallelExecution: boolean;
    batchSize: number;
    errorHandling: AutomationErrorHandling;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     DEFINITION                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

export interface AutomationDefinition {
    version: number;
    name: string;
    description: string;
    direction: AutomationDirection;
    trigger: AutomationTrigger;
    objectType: AutomationObjectType;
    fields: AutomationField[];
    target: AutomationTarget;
    mapping: AutomationMappingEntry[];
    conditions: AutomationConditionGroup;
    advanced: AutomationAdvancedSettings;
    active: boolean;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      FACTORIES                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

/** Defaults for the advanced settings, matching OpenCelium's own connector defaults. */
export function createDefaultAdvancedSettings(): AutomationAdvancedSettings {
    return {
        retryCount: 0,
        retryDelaySeconds: 30,
        timeoutSeconds: 1000,
        loggingEnabled: false,
        parallelExecution: false,
        batchSize: 100,
        errorHandling: 'abort'
    };
}


/** An empty draft the wizard starts from. */
export function createEmptyAutomationDefinition(): AutomationDefinition {
    return {
        version: AUTOMATION_DEFINITION_VERSION,
        name: '',
        description: '',
        direction: 'outgoing',
        trigger: { type: 'manual', cronExp: '' },
        objectType: { typeId: null, name: '', label: '' },
        fields: [],
        target: {
            connectorId: null,
            connectorTitle: '',
            invokerName: '',
            operation: 'create',
            remoteObjectTypeId: ''
        },
        mapping: [],
        conditions: { combinator: 'and', negate: false, rules: [] },
        advanced: createDefaultAdvancedSettings(),
        active: true
    };
}


/**
 * Fills in everything a stored definition might be missing.
 *
 * Drafts are persisted as JSON inside the OpenCelium connection description, so a definition
 * written by an older wizard build can lack whole branches. Normalising once here keeps every
 * consumer free of defensive checks.
 */
export function normalizeAutomationDefinition(raw: Partial<AutomationDefinition> | null): AutomationDefinition {
    const base = createEmptyAutomationDefinition();

    if (!raw) {
        return base;
    }

    return {
        version: AUTOMATION_DEFINITION_VERSION,
        name: raw.name ?? base.name,
        description: raw.description ?? base.description,
        direction: raw.direction ?? base.direction,
        trigger: { ...base.trigger, ...(raw.trigger ?? {}) },
        objectType: { ...base.objectType, ...(raw.objectType ?? {}) },
        fields: Array.isArray(raw.fields) ? raw.fields : base.fields,
        target: { ...base.target, ...(raw.target ?? {}) },
        mapping: Array.isArray(raw.mapping) ? raw.mapping : base.mapping,
        conditions: {
            ...base.conditions,
            ...(raw.conditions ?? {}),
            rules: Array.isArray(raw.conditions?.rules) ? raw.conditions.rules : []
        },
        advanced: { ...base.advanced, ...(raw.advanced ?? {}) },
        active: raw.active ?? base.active
    };
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       HELPERS                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

export function isTriggerSupported(type: AutomationTriggerType): boolean {
    return SUPPORTED_TRIGGER_TYPES.includes(type);
}


export function ruleNeedsValue(operator: AutomationRuleOperator): boolean {
    return !VALUELESS_RULE_OPERATORS.includes(operator);
}


/**
 * Renders the automation as one readable sentence for the summary step.
 *
 * Deliberately free of technical terms - this is the text that tells a user what they built.
 */
export function describeAutomation(definition: AutomationDefinition): string {
    const objectLabel = definition.objectType.label || 'objects';
    const targetLabel = definition.target.connectorTitle || 'the target system';
    const fieldCount = definition.fields.length;
    const fieldPart = fieldCount === 1 ? '1 field' : `${fieldCount} fields`;

    const action = {
        create: 'create',
        update: 'update',
        delete: 'delete'
    }[definition.target.operation];

    const triggerPart = {
        manual: 'when started manually',
        scheduled: definition.trigger.cronExp
            ? `on the schedule ${definition.trigger.cronExp}`
            : 'on a schedule',
        object_created: 'whenever an object is created',
        object_updated: 'whenever an object is updated',
        webhook: 'whenever an external webhook fires'
    }[definition.trigger.type];

    const flow = definition.direction === 'outgoing'
        ? `${action} ${objectLabel} in ${targetLabel} from DataGerry`
        : `${action} ${objectLabel} in DataGerry from ${targetLabel}`;

    const conditionPart = definition.conditions.rules.length > 0
        ? `, limited to objects matching ${definition.conditions.rules.length} condition(s)`
        : '';

    return `${triggerPart}, ${flow} using ${fieldPart}${conditionPart}.`;
}
