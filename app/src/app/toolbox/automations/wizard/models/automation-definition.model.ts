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

/**
 * Bumped whenever the persisted shape changes so the codec can migrate or reject old drafts.
 *
 * 2 is where the calls stopped being derived. Up to 1 an automation named an action - create,
 * update, delete - and the compiler worked out the calls from it; since 2 the sequence lists them,
 * and the action is only read to keep an automation written before the change running.
 */
export const AUTOMATION_DEFINITION_VERSION = 2;

/** Last version whose calls the compiler still has to derive. See seedsItsOwnCalls(). */
export const AUTOMATION_DERIVED_CALLS_VERSION = 1;

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

/**
 * Where a mapping entry takes its value from.
 *
 * 'objectValue' is read out of the source system's answer; 'constant' is a value the wizard already
 * knows - the chosen object type, for instance - and is written into the request as a literal.
 */
export type AutomationSystemFieldKind = 'objectValue' | 'constant';

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


/**
 * An optional rule that reshapes a value on its way to the target field.
 *
 * Systems rarely agree on how a value looks - one expects "SRV-01", the next "srv01" - and without
 * this the only way out was the old editor's raw enhancement script. The user writes plain
 * JavaScript against a single variable named `value`; the compiler wraps it into the script
 * OpenCelium executes, so nothing about enhancements leaks into the wizard's vocabulary.
 */
export interface AutomationValueTransform {
    /** False keeps the script but passes the value through unchanged, so drafts survive. */
    enabled: boolean;

    /** JavaScript statements. `value` holds the source value and is what gets written. */
    script: string;
}


/**
 * What the automation does with a source object once it knows whether the target already holds it.
 *
 * 'skip' leaves it alone, 'error' aborts or reports according to the error handling setting, and
 * the write outcomes name the operation to run.
 */
export type AutomationMatchOutcome = 'skip' | 'create' | 'update' | 'delete' | 'error';


/**
 * How the automation recognises that a source object and a target object are the same thing.
 *
 * Without this an automation can only ever add: it has no way of telling a new object from one it
 * already wrote, so updating and deleting are impossible and creating produces duplicates on every
 * run. The wizard therefore looks the object up in the target system first and branches on the
 * answer, which is what the two `if` operators in the compiled connection do.
 */
export interface AutomationMatching {
    /**
     * Source field of the mapping pair that identifies the object, or '' for no matching at all.
     *
     * Deliberately one of the pairs the user already mapped rather than a separate choice: the pair
     * exists on both sides by construction, and the target side is what the lookup filters on.
     */
    identifyBy: string;

    /** What to do with a source object the target system does not hold. */
    whenMissing: AutomationMatchOutcome;

    /** What to do with one it already holds. */
    whenPresent: AutomationMatchOutcome;
}


/**
 * Whether the compiler still has to work the calls out for this automation.
 *
 * Only true for one written before the sequence step existed. Such a definition names an action and
 * nothing else, so reopening it would show an automation that writes nothing if the calls were not
 * derived. Anything written since lists its calls and is compiled as it stands.
 */
export function seedsItsOwnCalls(definition: AutomationDefinition): boolean {
    return definition.version <= AUTOMATION_DERIVED_CALLS_VERSION;
}


/** Whether an outcome writes anything, i.e. whether it needs a method of its own. */
export function outcomeWrites(outcome: AutomationMatchOutcome): boolean {
    return outcome === 'create' || outcome === 'update' || outcome === 'delete';
}


/**
 * The matching a freshly chosen action implies.
 *
 * The action fixes one of the two branches - updating happens when the object is there, creating
 * when it is not - and leaves the other for the user to decide. Defaulting the open branch to
 * 'skip' keeps a newly configured automation from doing anything the user did not ask for.
 */
export function defaultMatchingFor(operation: AutomationOperation): AutomationMatching {
    return {
        identifyBy: '',
        whenMissing: operation === 'create' ? 'create' : 'skip',
        whenPresent: operation === 'create' ? 'skip' : operation
    };
}


/** Whether the action can run at all without looking the object up first. */
export function requiresMatching(definition: AutomationDefinition): boolean {
    return definition.target.operation !== 'create'
        || outcomeWrites(definition.matching.whenPresent);
}


/** One value feeding a target field. */
export interface AutomationMappingSource {
    /** Field name on the source side, or the key of a system field such as '$type_id'. */
    field: string;
    origin: AutomationMappingOrigin;

    /** Similarity score of an automatic suggestion, 0..1. Always 1 for a manual choice. */
    confidence: number;
}


/**
 * Everything that goes into one field of the target system.
 *
 * Keyed by the target rather than by the source, because that is what the transport is: an
 * OpenCelium fieldBinding names one target and carries a list of sources, which the script sees as
 * VAR_0, VAR_1 and so on. Several source fields combining into one target field - a title built
 * from an inventory number and a location - is therefore the normal case rather than an extension.
 */
export interface AutomationMappingEntry {
    /** Field path on the target side, as offered by the target catalog. Unique in the mapping. */
    target: string;

    /** In the order the script sees them. Never empty; an entry without sources is removed. */
    sources: AutomationMappingSource[];

    /** Absent for the overwhelming majority of pairs, which move their value unchanged. */
    transform?: AutomationValueTransform;
}


/** The entry writing a target field, if any. */
export function entryForTarget(
    mapping: AutomationMappingEntry[],
    target: string
): AutomationMappingEntry | undefined {
    return mapping.find(entry => entry.target === target);
}


/** Every source field the mapping uses, in no particular order. */
export function mappedSources(mapping: AutomationMappingEntry[]): Set<string> {
    return new Set(mapping.flatMap(entry => entry.sources.map(source => source.field)));
}


/** Whether a target field takes its value from more than one source. */
export function isCombined(entry: AutomationMappingEntry): boolean {
    return entry.sources.length > 1;
}


/**
 * Changes the user made to a call the assistant built.
 *
 * The sequence is derived from the rest of the definition, which is what keeps it honest: it cannot
 * describe a call the payload does not carry. That leaves no room for a call of your own - but it
 * leaves plenty for correcting one, and a foreign API often wants a header or a parameter no field
 * mapping covers. Those corrections live here, keyed by the call's position in the execution tree,
 * and the compiler applies them after everything else so they always win.
 *
 * A field the mapping writes is deliberately not overridable. OpenCelium rewrites a bound field on
 * save, so an override there would be discarded on the way in and look like the wizard lost it.
 */
export interface AutomationCallOverride {
    /** Replaces the operation's endpoint, so a query parameter can be added or removed. */
    endpoint?: string;

    /** Header values to set or replace, by header name. */
    headers?: Record<string, string>;

    /** Request body values to set, by dotted path inside the body's fields. */
    body?: Record<string, string>;
}


/**
 * A call the user added to the sequence.
 *
 * The skeleton - read, loop, look up, branch, write - stays derived, because that is what keeps it
 * honest: it cannot show a call the payload does not carry, and it cannot fall behind a change made
 * elsewhere. What it cannot do is grow. Anything a particular system needs beyond the skeleton
 * lives here instead: an i-doit category written after the object, a notification, a second write.
 *
 * Placed by the step it follows rather than by an index of its own, so inserting a branch above it
 * does not silently move it somewhere else.
 */
export interface AutomationExtraCall {
    /** Stable across reordering, which is what edits and corrections are keyed by. */
    id: string;

    /** Execution index of the skeleton call this runs after, e.g. '1_2_0'. */
    after: string;

    /**
     * Whether the call goes through an invoker or is written out in full.
     *
     * An invoker is reusable and self-documenting and knows its own response shape, so it is the
     * better answer whenever one exists. A free request is for the endpoint that has none - called
     * once, or belonging to a service too small to describe.
     */
    kind: 'operation' | 'http' | 'if' | 'loop';

    /** Operation of the target system's invoker. Empty for a free request. */
    operation: string;

    /** What an 'if' tests. Everything placed after it then runs only when it holds. */
    condition?: AutomationCallCondition;

    /** What a 'loop' walks. Everything placed after it then runs once per entry. */
    loop?: AutomationCallLoop;

    /** HTTP verb, for a free request only; an operation brings its own. */
    verb?: string;

    /** Where the identifier of the object the previous call touched goes, if it needs it. */
    parentIdPath?: string;

    /** Request body values, by dotted path inside the body's fields. */
    body?: Record<string, string>;
    headers?: Record<string, string>;
    endpoint?: string;
}


/**
 * What a condition in the sequence tests.
 *
 * Both sides are written as the engine reads them: a reference such as
 * `#FFCFB5.(response).body.$.results[i].type_id` fetches a value from a step that has already run,
 * anything else is the literal it looks like. Which of the two a side is decides how it is written
 * into the expression, and the '#' is what tells them apart - the same rule the captured conditions
 * follow, where a reference stands in braces and a literal in quotes.
 */
export interface AutomationCallCondition {
    left: string;

    /** One of the engine's own relational operators: '=', 'Like', 'NotNull', and so on. */
    operator: string;

    /** Empty on an operator that compares against nothing. */
    right: string;
}


/**
 * What a loop in the sequence walks.
 *
 * The list is a reference to a collection in an answer that has already been given, ending in the
 * `[*]` that says "every entry": `#FFCFB5.(response).body.$.results[*]`. The iterator is the name
 * the entry of the current pass goes by, and every reference into that list uses it - which is why
 * two loops must not share one, and why the wizard hands the name out rather than asking for it.
 */
export interface AutomationCallLoop {
    list: string;
    iterator: string;
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

    /**
     * Upper bound on how many objects one run reads, written as the read operation's page size.
     *
     * Not a chunk size: OpenCelium only fetches further pages when the invoker declares pagination,
     * and DataGerry's does not. Whatever is beyond this number is simply never seen.
     */
    batchSize: number;
    errorHandling: AutomationErrorHandling;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                    SYSTEM FIELDS                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * A value DataGerry knows about an object beyond the fields of its type.
 *
 * The object's own id and its type are what identify it, and identity is what most automations need
 * to line up: "this DataGerry object is that object over there". Those values are not part of the
 * type's field list, so without this table they could not be mapped at all.
 */
export interface AutomationSystemField {
    /**
     * Mapping key. Prefixed with '$' so it can never collide with a type field, whose names are
     * chosen by users.
     */
    key: string;
    label: string;
    type: string;
    hint: string;
    kind: AutomationSystemFieldKind;

    /** 'objectValue': dotted path inside one item of the DataGerry object response. */
    responsePath?: string;

    /**
     * 'constant': reads the literal out of the definition the user has already filled in.
     *
     * Deliberately not named valueOf - that name is taken by Object.prototype and typing it as a
     * string factory makes every object literal in the table fail to type-check.
     */
    fixedValue?: (definition: AutomationDefinition) => string;
}

/**
 * The DataGerry values an automation can map besides the type's own fields.
 *
 * Paths are the ones DataGerry's REST API answers with, as declared by the shipped invoker
 * (cmdb/open_celium/invokers/dg_cloud_invoker.xml).
 */
export const DATAGERRY_SYSTEM_FIELDS: ReadonlyArray<AutomationSystemField> = [
    {
        key: '$public_id',
        label: 'DataGerry object ID',
        type: 'number',
        hint: 'The object\'s own identifier - map it onto the identifier of the target system.',
        kind: 'objectValue',
        responsePath: 'public_id'
    },
    {
        key: '$active',
        label: 'Active',
        type: 'boolean',
        hint: 'Whether the object is active in DataGerry.',
        kind: 'objectValue',
        responsePath: 'active'
    },
    {
        key: '$author_id',
        label: 'Author ID',
        type: 'number',
        hint: 'The user who created the object.',
        kind: 'objectValue',
        responsePath: 'author_id'
    },
    {
        key: '$creation_time',
        label: 'Created at',
        type: 'date',
        hint: 'When the object was created.',
        kind: 'objectValue',
        responsePath: 'creation_time'
    },
    {
        key: '$last_edit_time',
        label: 'Last changed at',
        type: 'date',
        hint: 'When the object was last changed.',
        kind: 'objectValue',
        responsePath: 'last_edit_time'
    },
    {
        key: '$remote_type_id',
        label: 'Target system object type',
        type: 'text',
        hint: 'The type identifier of the target system, as given on the connection step. This is '
            + 'what a foreign system wants in its own type field - its numbering is not DataGerry\'s.',
        kind: 'constant',
        fixedValue: definition => definition.target.remoteObjectTypeId
    },
    {
        key: '$type_id',
        label: 'DataGerry object type ID',
        type: 'number',
        hint: 'The ID of the selected object type, sent as a fixed value.',
        kind: 'constant',
        fixedValue: definition => definition.objectType.typeId === null ? '' : String(definition.objectType.typeId)
    },
    {
        key: '$type_name',
        label: 'DataGerry object type name',
        type: 'text',
        hint: 'The technical name of the selected object type, sent as a fixed value.',
        kind: 'constant',
        fixedValue: definition => definition.objectType.name
    },
    {
        key: '$type_label',
        label: 'DataGerry object type label',
        type: 'text',
        hint: 'The display name of the selected object type, sent as a fixed value.',
        kind: 'constant',
        fixedValue: definition => definition.objectType.label
    }
];


export function findSystemField(name: string): AutomationSystemField | null {
    return DATAGERRY_SYSTEM_FIELDS.find(field => field.key === name) ?? null;
}


export function isSystemField(name: string): boolean {
    return findSystemField(name) !== null;
}


/**
 * The system fields that make sense for a direction.
 *
 * A value read out of a DataGerry object is only available when DataGerry is the side being read.
 * Constants hold either way: an incoming automation needs the object type id just as much, to create
 * its objects under the right type.
 */
export function systemFieldsFor(direction: AutomationDirection): AutomationSystemField[] {
    return DATAGERRY_SYSTEM_FIELDS.filter(field => {
        // The target system's own type is a value to send, so it belongs to the outgoing direction.
        // Reading a foreign system, that identifier narrows the read instead and is not mapped.
        if (field.key === '$remote_type_id') {
            return direction === 'outgoing';
        }

        return direction === 'outgoing' || field.kind === 'constant';
    });
}


/** The literal a constant system field stands for, or '' when the wizard cannot supply it yet. */
export function systemFieldValue(field: AutomationSystemField, definition: AutomationDefinition): string {
    return field.fixedValue ? field.fixedValue(definition) ?? '' : '';
}


/** System fields in the shape the field picker and the mapping step work with. */
export function toAutomationField(field: AutomationSystemField): AutomationField {
    return { name: field.key, label: field.label, type: field.type };
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

    /**
     * Source fields the user deliberately left unassigned.
     *
     * Without this a cleared field would be suggested again on the next pass, undoing the decision.
     * Keyed by field name because an unassigned field has no target to be keyed by.
     */
    unmapped: string[];
    matching: AutomationMatching;

    /**
     * Corrections to the calls the assistant built, keyed by execution index ('1_0', '1_2_0').
     *
     * Empty for an automation nobody had to correct, which is the normal case.
     */
    overrides: Record<string, AutomationCallOverride>;

    /**
     * Calls added to the sequence, in the order they were added.
     *
     * Empty for an automation the skeleton covers, which is most of them.
     */
    extras: AutomationExtraCall[];
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
        unmapped: [],
        matching: defaultMatchingFor('create'),
        overrides: {},
        extras: [],
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
        // Kept as read rather than stamped: it is what says whether this definition lists its
        // own calls, and stamping it would make every stored automation claim that it does.
        version: raw.version ?? AUTOMATION_DERIVED_CALLS_VERSION,
        name: raw.name ?? base.name,
        description: raw.description ?? base.description,
        direction: raw.direction ?? base.direction,
        trigger: { ...base.trigger, ...(raw.trigger ?? {}) },
        objectType: { ...base.objectType, ...(raw.objectType ?? {}) },
        fields: Array.isArray(raw.fields) ? raw.fields : base.fields,
        target: { ...base.target, ...(raw.target ?? {}) },
        mapping: normalizeMapping(raw.mapping as unknown),
        unmapped: Array.isArray(raw.unmapped) ? raw.unmapped : legacyUnmapped(raw.mapping as unknown),
        overrides: normalizeOverrides(raw.overrides),
        extras: Array.isArray(raw.extras) ? raw.extras.filter(isUsableExtra).map(normalizeExtra) : [],
        matching: { ...defaultMatchingFor(raw.target?.operation ?? 'create'), ...(raw.matching ?? {}) },
        conditions: {
            ...base.conditions,
            ...(raw.conditions ?? {}),
            rules: Array.isArray(raw.conditions?.rules) ? raw.conditions.rules : []
        },
        advanced: { ...base.advanced, ...(raw.advanced ?? {}) },
        active: raw.active ?? base.active
    };
}

/**
 * Drops a malformed transform rather than carrying it into the compiler.
 *
 * A definition that predates transforms has none at all, and a hand-edited one could carry anything,
 * so the shape is established once here.
 */
function normalizeMappingEntry(raw: any): AutomationMappingEntry {
    const transform = raw?.transform;
    const sources: AutomationMappingSource[] = Array.isArray(raw?.sources)
        ? raw.sources
            .filter((source: any) => typeof source?.field === 'string' && source.field)
            .map((source: any) => ({
                field: source.field,
                origin: source.origin === 'manual' ? 'manual' : 'auto',
                confidence: typeof source.confidence === 'number' ? source.confidence : 0
            }))
        : [];

    const entry: AutomationMappingEntry = { target: raw.target, sources };

    if (transform && typeof transform.script === 'string') {
        entry.transform = { enabled: !!transform.enabled, script: transform.script };
    }

    return entry;
}


/**
 * An added step the compiler can still place.
 *
 * It needs a step to follow and something to do: an operation to call, a request written out, or a
 * condition with a left-hand side to test. A condition missing that would compile to an operator
 * with no expression, which OpenCelium rejects outright.
 */
function isUsableExtra(raw: any): boolean {
    if (!raw?.id || !raw?.after) {
        return false;
    }

    if (raw.kind === 'http') {
        return true;
    }

    if (raw.kind === 'if') {
        return !!raw.condition?.left;
    }

    return raw.kind === 'loop' ? !!raw.loop?.list : !!raw.operation;
}


/** Fills in the kind for steps stored before free requests, conditions and loops existed. */
function normalizeExtra(raw: any): AutomationExtraCall {
    const known = ['http', 'if', 'loop'].includes(raw.kind) ? raw.kind : 'operation';

    return { ...raw, kind: known };
}


/** Keeps only the three kinds of correction the compiler knows how to apply. */
function normalizeOverrides(raw: unknown): Record<string, AutomationCallOverride> {
    if (!raw || typeof raw !== 'object') {
        return {};
    }

    const out: Record<string, AutomationCallOverride> = {};

    for (const [index, value] of Object.entries(raw as Record<string, any>)) {
        const override: AutomationCallOverride = {};

        if (typeof value?.endpoint === 'string') {
            override.endpoint = value.endpoint;
        }

        for (const part of ['headers', 'body'] as const) {
            if (value?.[part] && typeof value[part] === 'object') {
                const pairs = Object.entries(value[part])
                    .filter(([, item]) => typeof item === 'string') as Array<[string, string]>;

                if (pairs.length > 0) {
                    override[part] = Object.fromEntries(pairs);
                }
            }
        }

        if (Object.keys(override).length > 0) {
            out[index] = override;
        }
    }

    return out;
}


/**
 * Reads a stored mapping, whichever shape it was written in.
 *
 * Up to now an entry was one source and one target, so several fields writing the same target could
 * not be expressed and a cleared field was kept as an entry with an empty target. Both are folded
 * into the current shape here: entries are grouped by their target, and the ones that named no
 * target become the list of fields the user left alone.
 */
function normalizeMapping(raw: unknown): AutomationMappingEntry[] {
    if (!Array.isArray(raw)) {
        return [];
    }

    if (!(raw as any[]).some(entry => typeof entry?.source === 'string')) {
        return (raw as any[])
            .filter(entry => typeof entry?.target === 'string' && entry.target)
            .map(normalizeMappingEntry)
            .filter(entry => entry.sources.length > 0);
    }

    const byTarget = new Map<string, AutomationMappingEntry>();

    for (const legacy of raw as any[]) {
        if (!legacy?.target || typeof legacy.source !== 'string') {
            continue;
        }

        const entry: AutomationMappingEntry = byTarget.get(legacy.target)
            ?? { target: legacy.target, sources: [] };

        entry.sources.push({
            field: legacy.source,
            origin: legacy.origin === 'manual' ? 'manual' : 'auto',
            confidence: typeof legacy.confidence === 'number' ? legacy.confidence : 0
        });

        if (legacy.transform && typeof legacy.transform.script === 'string' && !entry.transform) {
            entry.transform = { enabled: !!legacy.transform.enabled, script: legacy.transform.script };
        }

        byTarget.set(legacy.target, entry);
    }

    return [...byTarget.values()];
}

/**
 * The fields a stored mapping shows were deliberately left alone.
 *
 * The older shape had no list for them: a field the user cleared stayed in the mapping as an entry
 * naming a source and no target. Read back as nothing at all, those fields would be suggested a
 * target again the moment the automation is reopened - which is the wizard undoing a decision
 * somebody made on purpose.
 */
function legacyUnmapped(raw: unknown): string[] {
    if (!Array.isArray(raw)) {
        return [];
    }

    return (raw as any[])
        .filter(entry => typeof entry?.source === 'string' && entry.source && !entry.target)
        .map(entry => entry.source as string);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       HELPERS                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

export function isTriggerSupported(type: AutomationTriggerType): boolean {
    return SUPPORTED_TRIGGER_TYPES.includes(type);
}


export function createEmptyTransform(): AutomationValueTransform {
    return { enabled: true, script: '' };
}


/** Whether an entry actually reshapes its value, as opposed to merely carrying an empty draft. */
export function hasActiveTransform(entry: AutomationMappingEntry): boolean {
    return !!entry.transform?.enabled && !!entry.transform.script.trim();
}


export function ruleNeedsValue(operator: AutomationRuleOperator): boolean {
    return !VALUELESS_RULE_OPERATORS.includes(operator);
}


/**
 * Renders the automation as one readable sentence for the summary step.
 *
 * Deliberately free of technical terms - this is the text that tells a user what they built.
 */
/**
 * The lookup, in the same plain sentence the rest of the summary is written in.
 *
 * The branching is the part of an automation users are most likely to get wrong, so it is said out
 * loud rather than left to be inferred from the technical view.
 */
function describeMatching(definition: AutomationDefinition): string {
    const { identifyBy, whenMissing, whenPresent } = definition.matching;

    if (!requiresMatching(definition) || !identifyBy) {
        return '';
    }

    const known = definition.fields.find(field => field.name === identifyBy)?.label ?? identifyBy;
    const outcome = (verb: AutomationMatchOutcome, present: boolean) => ({
        skip: present ? 'it is left as it is' : 'the object is skipped',
        create: 'it is created',
        update: 'it is updated',
        delete: 'it is deleted',
        error: 'it is reported as an error'
    }[verb]);

    return ` Objects are recognised by ${known}: if it is already there, ${outcome(whenPresent, true)}`
        + `; if not, ${outcome(whenMissing, false)}.`;
}


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

    return `${triggerPart}, ${flow} using ${fieldPart}${conditionPart}.${describeMatching(definition)}`;
}
