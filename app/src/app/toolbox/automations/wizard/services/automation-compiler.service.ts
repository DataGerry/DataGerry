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
import { Injectable } from '@angular/core';

import {
    AutomationConditionGroup,
    AutomationDefinition,
    AutomationMappingEntry,
    AutomationRuleOperator,
    findSystemField,
    isTriggerSupported,
    systemFieldValue
} from '../models/automation-definition.model';
import {
    OcConnection,
    OcConnectorRef,
    OcCreateAutomationRequest,
    OcEnhancement,
    OcFieldBinding,
    OcFlowchart,
    OcFlowchartEdge,
    OcMethod,
    OcOperator,
    OcSchedulerPayload,
    OcUi,
    OcUiGroup,
    OcWorkflowEdge,
    OcWorkflowNode,
    ocCollectionElementPath,
    ocEdgeId,
    ocFieldReference,
    ocLoopExpression,
    ocLoopNodeId,
    ocMethodNodeId,
    OC_DEFAULT_CONNECTOR_ID,
    OC_DEFAULT_CONNECTOR_TITLE,
    OC_LOOP_INDEX,
    OC_METHOD_COLORS,
    OC_SCHEDULER_ACTIVE,
    OC_SCHEDULER_INACTIVE,
    OC_SOURCE_INDEX,
    OC_TARGET_INDEX,
    OC_UI_LAYOUT
} from '../models/opencelium-connection.model';
import { findAdapter, ResolvedOperation } from '../models/target-catalog.model';
import { TargetCatalogService } from './target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Everything the compiler needs beyond the definition itself. */
export interface AutomationCompileContext {
    /**
     * The internal DataGerry connector, with its invoker replaced by the full definition from
     * /rest/open_celium/invokers - the bare connector list only carries the invoker's name.
     */
    internalConnector: any;

    /** The external connector chosen as the target system, likewise with a full invoker. */
    targetConnector: any;

    /**
     * Field names of the selected object type in the order DataGerry returns them.
     *
     * DataGerry answers with `fields` as an array of name/value pairs, so addressing a business
     * field on the DataGerry side needs its position. See resolveDataGerryFieldPath.
     */
    objectTypeFieldOrder: string[];
}


export interface CompilationOutcome<T> {
    payload: T;

    /**
     * Non-blocking findings the UI shows next to the technical view - for instance an action that
     * had to be resolved by keyword instead of a verified adapter.
     */
    warnings: string[];
}

/**
 * Turns the business model into the OpenCelium connection payload.
 *
 * The structure produced here mirrors the two reference payloads captured from a running
 * installation, down to which keys a method carries and which its workflow node repeats. Where the
 * references give no example - user conditions - the compiler derives the shape from the schema and
 * says so through a warning rather than pretending certainty.
 */
@Injectable({ providedIn: 'root' })
export class AutomationCompilerService {

    /**
     * Constructor injection rather than inject(): it keeps the compiler instantiable outside an
     * Angular injection context, which is what lets it be verified against the reference payloads
     * without a browser.
     */
    constructor(private readonly catalog: TargetCatalogService) {
    }

    private static readonly SOURCE_COLOR = OC_METHOD_COLORS[0];
    private static readonly TARGET_COLOR = OC_METHOD_COLORS[1];
    private static readonly LOOP_ITERATOR = 'i';

    /** Node identities, shared between the connection body and its ui block. */
    private static readonly SOURCE_NODE = ocMethodNodeId(0);
    private static readonly TARGET_NODE = ocMethodNodeId(1);
    private static readonly LOOP_NODE = ocLoopNodeId(0);
    private static readonly START_NODE = 'start-1';

    /**
     * Display label of the read method, as the reference payloads carry it.
     *
     * Operation names are technical ('cmdb.objects.read') and invoker definitions provide no label,
     * so the compiler supplies a readable one. The target method carries no label at all.
     */
    private static readonly SOURCE_LABEL = 'GetObjects';

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     VALIDATION                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Collects everything that prevents compilation.
     *
     * Returned as a list rather than thrown so the wizard can show all problems at once on the
     * summary step instead of revealing them one by one.
     */
    public validate(definition: AutomationDefinition, context: AutomationCompileContext): string[] {
        const errors: string[] = [];

        if (!definition.name?.trim()) {
            errors.push('The automation needs a name.');
        }

        if (!isTriggerSupported(definition.trigger.type)) {
            errors.push(`The trigger "${definition.trigger.type}" cannot be executed yet. Choose a manual or scheduled trigger.`);
        }

        if (definition.trigger.type === 'scheduled' && !definition.trigger.cronExp?.trim()) {
            errors.push('A scheduled automation needs a cron expression.');
        }

        if (!definition.objectType.typeId) {
            errors.push('Select the DataGerry object type the data belongs to.');
        }

        if (definition.fields.length === 0) {
            errors.push('Select at least one field to transfer.');
        }

        if (!definition.target.connectorId) {
            errors.push('Select a target system.');
        }

        if (!context.internalConnector?.invoker?.operations) {
            errors.push('The internal DataGerry connector is not configured. Set up its API credentials first.');
        }

        if (!context.targetConnector?.invoker?.operations) {
            errors.push('The selected target system has no usable interface definition.');
        }

        if (errors.length > 0) {
            return errors;
        }

        const sides = this.resolveSides(definition, context);

        if (!sides.source) {
            errors.push('The source system offers no operation for reading objects.');
        }

        if (!sides.target) {
            errors.push(`The target system offers no operation for "${definition.target.operation}".`);
        }

        if (sides.source && !sides.source.responseArrayPath) {
            errors.push('The source operation does not return a list of objects, so there is nothing to iterate.');
        }

        if (definition.mapping.filter(entry => entry.target).length === 0) {
            errors.push('Map at least one field to the target system.');
        }

        return errors;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     COMPILATION                                                    */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Builds the body of POST /rest/open_celium/schedulers.
     *
     * On this endpoint the connectors carry no title and the connection id is 0, matching the
     * reference create payload.
     */
    public compileForCreate(
        definition: AutomationDefinition,
        context: AutomationCompileContext
    ): CompilationOutcome<OcCreateAutomationRequest> {
        const warnings: string[] = [];
        const connection = this.buildConnection(definition, context, warnings, true);

        return {
            payload: { connection, scheduler: this.buildScheduler(definition) },
            warnings
        };
    }


    /**
     * Builds the body of PUT /rest/open_celium/connections/:id.
     *
     * The same connection as on create, with its id added. Credentials no longer need stripping:
     * the connection carries no invoker definitions to strip them from.
     */
    public compileForUpdate(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        connectionId: number
    ): CompilationOutcome<OcConnection> {
        const warnings: string[] = [];
        const connection = this.buildConnection(definition, context, warnings, false);

        connection.connectionId = connectionId;

        return { payload: connection, warnings };
    }


    public buildScheduler(definition: AutomationDefinition): OcSchedulerPayload {
        return {
            title: definition.name,
            debugMode: definition.advanced.loggingEnabled,
            status: definition.active ? OC_SCHEDULER_ACTIVE : OC_SCHEDULER_INACTIVE,
            cronExp: definition.trigger.type === 'scheduled' ? definition.trigger.cronExp : ''
        };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                    CONNECTION                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Assembles the connection both endpoints send.
     *
     * `withEdgeData` is the one difference between them: the create capture carries an empty `data`
     * object on every workflow edge, the update capture omits the key.
     */
    private buildConnection(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        warnings: string[],
        withEdgeData: boolean
    ): OcConnection {
        const sides = this.resolveSides(definition, context);

        if (!sides.source || !sides.target) {
            throw new Error('The automation cannot be compiled - validate() first.');
        }

        this.collectResolutionWarnings(definition, sides, warnings);

        const sourceMethod = this.buildMethod(
            sides.source,
            sides.sourceConnector,
            AutomationCompilerService.SOURCE_NODE,
            OC_SOURCE_INDEX,
            AutomationCompilerService.SOURCE_COLOR,
            AutomationCompilerService.SOURCE_LABEL
        );

        this.applyListFilter(definition, sides, sourceMethod, warnings);
        this.applyListLimit(definition, sides, sourceMethod);

        const targetMethod = this.buildMethod(
            sides.target,
            sides.targetConnector,
            AutomationCompilerService.TARGET_NODE,
            OC_TARGET_INDEX,
            AutomationCompilerService.TARGET_COLOR,
            null
        );

        const bindings = this.buildFieldBindings(definition, context, sides, targetMethod, warnings);
        const loop = this.buildLoopOperator(sides.source.responseArrayPath);
        let conditionTree: OcUiGroup = this.emptyConditionTree();

        if (definition.conditions.rules.length > 0) {
            warnings.push(
                'Conditions are compiled into the loop operator\'s condition. No reference payload '
                + 'covers a populated condition yet, so run the test step before activating.'
            );
            loop.condition = this.buildConditionExpression(
                definition.conditions,
                sides.source.responseArrayPath
            );
            conditionTree = this.buildConditionUiGroup(this.uuid(), definition.conditions);
        }

        return {
            title: definition.name,
            name: definition.name,
            description: definition.description,
            fieldBinding: bindings,
            fromConnector: {
                connectorId: OC_DEFAULT_CONNECTOR_ID,
                title: OC_DEFAULT_CONNECTOR_TITLE,
                methods: [sourceMethod, targetMethod],
                operators: [loop]
            },
            toConnector: null,
            ui: this.buildUi(sourceMethod, targetMethod, loop, conditionTree, withEdgeData)
        };
    }


    /**
     * Builds one method entry.
     *
     * The captures omit `label` entirely on the target method rather than sending null, so the key
     * is only added when there is a label to send. The invoker itself is no longer embedded - the
     * method names its connector and OpenCelium looks the rest up.
     */
    private buildMethod(
        operation: ResolvedOperation,
        connector: any,
        id: string,
        index: string,
        color: string,
        label: string | null
    ): OcMethod {
        const method: any = {
            id,
            name: operation.name,
            index,
            methodType: 'CONNECTOR',
            dataAggregator: null,
            color,
            connector: this.connectorRef(connector),
            request: this.clone(operation.definition.request),
            response: this.buildMethodResponse(id, operation)
        };

        if (label !== null) {
            method.label = label;
        }

        return method as OcMethod;
    }


    /** How a method points at its connector, in place of the invoker it used to carry. */
    private connectorRef(connector: any): OcConnectorRef {
        const ref: OcConnectorRef = {
            connectorId: connector?.connectorId,
            title: connector?.title ?? '',
            // The captures spell "no icon" as null; the connector list uses an empty string for it.
            icon: connector?.icon || null,
            invokerName: connector?.invoker?.name ?? ''
        };

        // Passed through rather than invented: only a connector OpenCelium has tested carries it.
        if (connector?.lastTestPassed !== undefined) {
            ref.lastTestPassed = connector.lastTestPassed;
        }

        return ref;
    }


    /** The operation's response, tagged with the id the ui block refers to it by. */
    private buildMethodResponse(methodId: string, operation: ResolvedOperation): any {
        return {
            responseId: `response-${methodId}`,
            ...this.clone(operation.definition.response)
        };
    }


    private buildLoopOperator(arrayPath: string): OcOperator {
        return {
            id: AutomationCompilerService.LOOP_NODE,
            index: OC_LOOP_INDEX,
            type: 'loop',
            dataAggregator: null,
            expression: ocLoopExpression(AutomationCompilerService.SOURCE_COLOR, arrayPath),
            iterator: AutomationCompilerService.LOOP_ITERATOR
        };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   FIELD BINDINGS                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Wires each mapped field pair.
     *
     * A pair that reads from the source produces two things: the reference string written straight
     * into the target method's request body, and a fieldBinding entry carrying the script OpenCelium
     * executes. The reference payloads contain both, so both are produced. A pair whose value is a
     * constant needs neither - the literal goes into the body and there is nothing to read.
     */
    private buildFieldBindings(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        targetMethod: OcMethod,
        warnings: string[]
    ): OcFieldBinding[] {
        const arrayPath = sides.source!.responseArrayPath;
        const bindings: OcFieldBinding[] = [];

        for (const entry of definition.mapping) {
            if (!entry.target) {
                continue;
            }

            const value = this.resolveSourceValue(definition, context, entry.source, warnings);

            if (!value) {
                continue;
            }

            if (value.kind === 'constant') {
                this.bindConstant(entry, value.value, sides, targetMethod, bindings, warnings);

                continue;
            }

            const sourcePath = `body.$.${ocCollectionElementPath(arrayPath, value.path)}`;
            const targetPath = `body.$.${entry.target}`;
            const reference = ocFieldReference(
                AutomationCompilerService.SOURCE_COLOR,
                'response',
                ocCollectionElementPath(arrayPath, value.path)
            );

            this.setBodyField(targetMethod.request, entry.target, reference);

            bindings.push({
                from: [{ color: AutomationCompilerService.SOURCE_COLOR, field: sourcePath, type: 'response' }],
                to: [{ color: AutomationCompilerService.TARGET_COLOR, field: targetPath, type: 'request' }],
                enhancement: this.buildEnhancement(sourcePath, targetPath, entry, warnings)
            });
        }

        return bindings;
    }


    /**
     * Wires a pair whose value is a fixed literal rather than something read from the source.
     *
     * Without an adjustment the literal simply goes into the request body, which is what the
     * reference payloads show. With one, the script has to run somewhere, and OpenCelium only runs
     * scripts inside a fieldBinding - which insists on a `from` response field even when the script
     * ignores it. So a field the read operation returns anyway is named as the source, the body
     * carries the matching reference as it does for every other bound pair, and the script starts
     * from the literal instead of from that field's value.
     *
     * The borrowed field is never read: `value` is seeded with the literal and the script's result
     * overwrites it. It exists only to give the binding a well-formed origin.
     */
    private bindConstant(
        entry: AutomationMappingEntry,
        literal: string,
        sides: ResolvedSides,
        targetMethod: OcMethod,
        bindings: OcFieldBinding[],
        warnings: string[]
    ): void {
        const script = entry.transform?.enabled ? entry.transform.script.trim() : '';
        const borrowed = script ? this.borrowedSourcePath(sides) : '';

        if (entry.transform?.enabled && !script) {
            warnings.push(
                `The value adjustment for "${entry.source}" has no content, so the fixed value is sent `
                + 'unchanged.'
            );
        }

        if (script && !borrowed) {
            warnings.push(
                `The value adjustment for "${entry.source}" needs a field the read operation returns, and `
                + 'this operation describes none, so the fixed value is sent unchanged.'
            );
        }

        if (!script || !borrowed) {
            this.setBodyField(targetMethod.request, entry.target, literal);

            return;
        }

        const elementPath = ocCollectionElementPath(sides.source!.responseArrayPath, borrowed);
        const sourcePath = `body.$.${elementPath}`;
        const targetPath = `body.$.${entry.target}`;

        this.setBodyField(
            targetMethod.request,
            entry.target,
            ocFieldReference(AutomationCompilerService.SOURCE_COLOR, 'response', elementPath)
        );

        bindings.push({
            from: [{ color: AutomationCompilerService.SOURCE_COLOR, field: sourcePath, type: 'response' }],
            to: [{ color: AutomationCompilerService.TARGET_COLOR, field: targetPath, type: 'request' }],
            enhancement: this.buildEnhancement(sourcePath, targetPath, entry, warnings, literal)
        });
    }


    /**
     * A response field of the read operation, used as the formal origin of a constant's binding.
     *
     * The first field the operation describes is taken rather than one of the mapped pairs, so the
     * choice does not shift when the user changes the mapping.
     */
    private borrowedSourcePath(sides: ResolvedSides): string {
        return this.catalog.sourceItemFields(sides.source)[0]?.path ?? '';
    }


    /**
     * The script OpenCelium runs for one pair.
     *
     * Without a transformation this is the plain assignment the reference payloads carry. With one,
     * the user's statements are wrapped so they operate on a variable named `value`: the wizard's
     * vocabulary never mentions RESULT_VAR or VAR_0, and the wrapping keeps a mistyped script from
     * reaching past its own pair.
     *
     * `literal` is set for a fixed value, whose script starts from that literal rather than from the
     * response field the binding names.
     */
    private buildEnhancement(
        sourcePath: string,
        targetPath: string,
        entry: AutomationMappingEntry,
        warnings: string[],
        literal?: string
    ): OcEnhancement {
        const script = entry.transform?.enabled ? entry.transform.script.trim() : '';

        if (literal === undefined && entry.transform?.enabled && !script) {
            warnings.push(
                `The value adjustment for "${entry.source}" has no content, so the value is transferred `
                + 'unchanged.'
            );
        }

        const seed = literal === undefined ? 'VAR_0' : JSON.stringify(literal);

        return {
            name: '',
            description: '',
            language: 'js',
            simpleCode: null,
            expertVar: `//var RESULT_VAR = ${AutomationCompilerService.TARGET_COLOR}.(request).${targetPath};\n`
                + `//var VAR_0 = ${AutomationCompilerService.SOURCE_COLOR}.(response).${sourcePath};`,
            expertCode: script
                ? `var value = ${seed};\n${script}\nRESULT_VAR = value;`
                : 'RESULT_VAR = VAR_0;'
        };
    }


    /**
     * Works out where one mapping entry takes its value from.
     *
     * Three cases: a value the wizard already knows (the chosen object type) is a literal; a
     * DataGerry system value such as the object id sits at the top of the object; everything else is
     * an ordinary field, which on the DataGerry side lives inside the object's `fields` array.
     */
    private resolveSourceValue(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        source: string,
        warnings: string[]
    ): SourceValue | null {
        const systemField = findSystemField(source);

        if (systemField) {
            if (systemField.kind === 'constant') {
                const value = systemFieldValue(systemField, definition);

                if (!value) {
                    warnings.push(`"${systemField.label}" has no value yet and was skipped.`);

                    return null;
                }

                return { kind: 'constant', value };
            }

            if (definition.direction !== 'outgoing') {
                warnings.push(
                    `"${systemField.label}" can only be read when DataGerry is the source, so it was skipped.`
                );

                return null;
            }

            return { kind: 'path', path: systemField.responsePath! };
        }

        if (definition.direction === 'incoming') {
            return { kind: 'path', path: source };
        }

        const path = this.resolveDataGerryFieldPath(context, source, warnings);

        return path ? { kind: 'path', path } : null;
    }


    /**
     * Positional path of a DataGerry object field.
     *
     * DataGerry's object endpoints answer with `fields: [{ name, value }, ...]` in the order the
     * type declares them, so a business field is addressed by its index in that declaration. That
     * makes the address depend on the type's field order, which is what the warning is about.
     */
    private resolveDataGerryFieldPath(
        context: AutomationCompileContext,
        fieldName: string,
        warnings: string[]
    ): string | null {
        const index = context.objectTypeFieldOrder.indexOf(fieldName);

        if (index === -1) {
            warnings.push(`The field "${fieldName}" is not part of the selected object type and was skipped.`);

            return null;
        }

        return `fields[${index}].value`;
    }


    /**
     * Restricts the read operation to the selected object type.
     *
     * Without this an automation would read every object the source system holds and then write all
     * of them, which is the difference between "sync my servers" and "sync everything". Where the
     * restriction goes is adapter knowledge: i-doit takes it in the request body, DataGerry as a
     * query parameter on the endpoint.
     */
    private applyListFilter(
        definition: AutomationDefinition,
        sides: ResolvedSides,
        sourceMethod: OcMethod,
        warnings: string[]
    ): void {
        const adapter = findAdapter(sides.sourceConnector?.invoker?.name);
        const placement = adapter?.listFilter;

        if (!placement) {
            warnings.push(
                'The source system has no known way to filter by object type, so the automation reads '
                + 'every object it returns. Narrow it down with a condition.'
            );

            return;
        }

        // Incoming automations read the foreign system, so the foreign type id applies. Outgoing
        // automations read DataGerry, where the object type is known from the wizard.
        const typeId = definition.direction === 'incoming'
            ? definition.target.remoteObjectTypeId
            : String(definition.objectType.typeId ?? '');

        if (!typeId) {
            warnings.push(
                'No object type identifier was given for the source system, so the automation reads '
                + 'every object it returns.'
            );

            return;
        }

        if (placement.endpointQuery) {
            this.appendEndpointQuery(sourceMethod.request, placement.endpointQuery, `{"type_id":${typeId}}`);

            return;
        }

        this.setBodyField(
            sourceMethod.request,
            placement.bodyPath!,
            placement.asArray ? [typeId] as any : typeId,
            placement.pruneSiblings
        );
    }


    /**
     * Applies the batch size to the read operation's page size.
     *
     * This is what makes the wizard's "batch size" advanced setting do something rather than be
     * decorative. A batch size of 0 is treated as "no limit" and leaves the operation untouched.
     */
    private applyListLimit(
        definition: AutomationDefinition,
        sides: ResolvedSides,
        sourceMethod: OcMethod
    ): void {
        const placement = findAdapter(sides.sourceConnector?.invoker?.name)?.listLimit;
        const batchSize = definition.advanced.batchSize;

        if (!placement || !batchSize || batchSize <= 0) {
            return;
        }

        if (placement.endpointQuery) {
            this.appendEndpointQuery(sourceMethod.request, placement.endpointQuery, String(batchSize));

            return;
        }

        this.setBodyField(sourceMethod.request, placement.bodyPath!, String(batchSize));
    }


    /** Appends a query parameter to an operation endpoint, preserving any it already has. */
    private appendEndpointQuery(request: any, key: string, value: string): void {
        const endpoint: string = request.endpoint ?? '';
        const separator = endpoint.includes('?') ? '&' : '?';

        request.endpoint = `${endpoint}${separator}${key}=${encodeURIComponent(value)}`;
    }


    /** Writes a value into the request body's field tree, creating intermediate objects as needed. */
    private setBodyField(
        request: any,
        dottedPath: string,
        value: string | string[],
        pruneSiblings = false
    ): void {
        if (!request.body) {
            request.body = { type: 'object', format: 'json', data: 'raw', fields: {} };
        }

        if (!request.body.fields) {
            request.body.fields = {};
        }

        const segments = dottedPath.split('.');
        let node = request.body.fields;

        for (const segment of segments.slice(0, -1)) {
            if (typeof node[segment] !== 'object' || node[segment] === null || Array.isArray(node[segment])) {
                node[segment] = {};
            }

            node = node[segment];
        }

        const leaf = segments[segments.length - 1];

        if (pruneSiblings) {
            // The invoker template carries every filter key it supports; the reference keeps only
            // the one actually used, so unused keys are dropped rather than sent empty.
            Object.keys(node).forEach(key => {
                if (key !== leaf) {
                    delete node[key];
                }
            });
        }

        node[leaf] = value;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     CONDITIONS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Compiles the visual rules into the loop operator's condition string.
     *
     * Kept in one place because the condition syntax is derived from the operator schema rather than
     * from a reference payload; if OpenCelium expects something else, only this method changes.
     */
    private buildConditionExpression(group: AutomationConditionGroup, arrayPath: string): string {
        const joiner = group.combinator === 'and' ? ' && ' : ' || ';
        const parts = group.rules.map(rule => {
            const left = `{%${ocFieldReference(
                AutomationCompilerService.SOURCE_COLOR,
                'response',
                ocCollectionElementPath(arrayPath, rule.field)
            )}%}`;

            return this.renderRule(left, rule.operator, rule.value);
        });

        const expression = parts.length > 1 ? `(${parts.join(joiner)})` : parts.join(joiner);

        return group.negate ? `!${expression}` : expression;
    }


    private renderRule(left: string, operator: AutomationRuleOperator, value: string): string {
        switch (operator) {
            case 'equals':
                return `${left} == "${value}"`;
            case 'not_equals':
                return `${left} != "${value}"`;
            case 'contains':
                return `${left}.includes("${value}")`;
            case 'not_contains':
                return `!${left}.includes("${value}")`;
            case 'starts_with':
                return `${left}.startsWith("${value}")`;
            case 'ends_with':
                return `${left}.endsWith("${value}")`;
            case 'is_empty':
                return `${left} == ""`;
            case 'is_not_empty':
                return `${left} != ""`;
            case 'greater_than':
                return `${left} > ${Number(value) || 0}`;
            case 'less_than':
                return `${left} < ${Number(value) || 0}`;
            default:
                return `${left} == "${value}"`;
        }
    }


    /** An untouched condition tree - what the loop node carries when nothing restricts it. */
    private emptyConditionTree(): OcUiGroup {
        return { id: '0-group', type: 'group', properties: { not: false }, items: [] };
    }


    private buildConditionUiGroup(uiId: string, group: AutomationConditionGroup): OcUiGroup {
        return {
            id: uiId,
            type: 'group',
            properties: { not: group.negate },
            items: group.rules.map(rule => ({
                id: this.uuid(),
                type: 'rule' as const,
                properties: {
                    operator: rule.operator,
                    leftField: rule.field,
                    rightField: rule.value
                }
            }))
        };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                    WORKFLOW GRAPH                                                  */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Rebuilds the graph OpenCelium's editor draws from.
     *
     * It repeats what the methods and operators already say, in the shape the editor reads: a start
     * node, the reading method, the loop, and the writing method hanging below the loop. The same
     * graph is sent twice - once fully as `workflowNodes`/`workflowEdges`, once reduced to positions
     * as `flowcharts`/`flowchartEdges` - which is what the captures show.
     */
    private buildUi(
        sourceMethod: OcMethod,
        targetMethod: OcMethod,
        loop: OcOperator,
        conditionTree: OcUiGroup,
        withEdgeData: boolean
    ): OcUi {
        const { startX, stepX, rowY, branchDy } = OC_UI_LAYOUT;
        const loopX = startX + 2 * stepX;

        const nodes: OcWorkflowNode[] = [
            {
                id: AutomationCompilerService.START_NODE,
                type: 'start',
                position: { x: startX, y: rowY },
                data: { title: '', kind: 'start' },
                draggable: true,
                deletable: false
            },
            this.connectorNode(sourceMethod, { x: startX + stepX, y: rowY }),
            {
                id: loop.id,
                type: 'loop',
                position: { x: loopX, y: rowY },
                index: loop.index,
                data: {
                    title: 'Loop',
                    subtitle: loop.expression,
                    kind: 'loop',
                    conditionConfig: {
                        operatorType: 'loop',
                        tree: conditionTree,
                        expression: loop.expression,
                        iterator: loop.iterator
                    }
                }
            },
            // The written method runs inside the loop, so it drops below it instead of continuing
            // the row - the loop's own column is kept.
            this.connectorNode(targetMethod, { x: loopX, y: rowY + branchDy })
        ];

        const edges = [
            this.edge(AutomationCompilerService.START_NODE, sourceMethod.id, undefined, 'left'),
            this.edge(sourceMethod.id, loop.id, undefined, 'left'),
            this.edge(loop.id, targetMethod.id, 'bottom', 'top')
        ];

        return {
            viewport: { ...OC_UI_LAYOUT.viewport },
            workflowNodes: nodes,
            workflowEdges: edges.map(edge => this.workflowEdge(edge, withEdgeData)),
            flowcharts: nodes.map(node => this.flowchart(node)),
            flowchartEdges: edges
        };
    }


    private connectorNode(method: OcMethod, position: { x: number; y: number }): OcWorkflowNode {
        return {
            id: method.id,
            type: 'connector',
            position,
            index: method.index,
            data: {
                title: method.connector.title,
                subtitle: method.name,
                kind: 'connector',
                connector: method.connector,
                methodConfig: this.methodConfig(method)
            }
        };
    }


    /**
     * The method restated the way the editor's request form reads it.
     *
     * Same content as the method's own request and response, only flattened: the body's envelope
     * becomes `bodyFormat`/`bodyData` and its fields become `body`.
     */
    private methodConfig(method: OcMethod): any {
        const request = method.request ?? {};
        const body = request.body ?? {};

        return {
            url: request.endpoint ?? '',
            method: request.method ?? '',
            headers: request.header ?? {},
            bodyFormat: body.format ?? 'json',
            bodyData: body.data ?? 'raw',
            body: body.fields ?? {},
            response: method.response,
            name: method.name,
            queryParams: this.queryParams(request.endpoint ?? '')
        };
    }


    /**
     * The endpoint's query string, restated as the editor's parameter rows.
     *
     * Values keep the encoding they carry in the endpoint: the row records what is sent, and
     * decoding it here would make a re-encoded value differ from the endpoint it came from.
     */
    private queryParams(endpoint: string): any[] {
        const query = endpoint.slice(endpoint.indexOf('?') + 1);

        if (!endpoint.includes('?') || !query) {
            return [];
        }

        return query.split('&').filter(Boolean).map(pair => {
            const separator = pair.indexOf('=');

            return {
                id: this.uuid(),
                key: separator === -1 ? pair : pair.slice(0, separator),
                value: separator === -1 ? '' : pair.slice(separator + 1),
                enabled: true,
                autoEncode: true
            };
        });
    }


    private edge(
        source: string,
        target: string,
        sourceHandle: string | undefined,
        targetHandle: string
    ): OcFlowchartEdge {
        const edge: OcFlowchartEdge = { id: '', source, target, targetHandle };

        if (sourceHandle) {
            edge.sourceHandle = sourceHandle;
        }

        edge.id = ocEdgeId(edge);

        return edge;
    }


    private workflowEdge(edge: OcFlowchartEdge, withData: boolean): OcWorkflowEdge {
        const full: OcWorkflowEdge = { ...edge, type: 'workflow-edge' };

        if (withData) {
            full.data = {};
        }

        return full;
    }


    private flowchart(node: OcWorkflowNode): OcFlowchart {
        return { flowId: node.id, x: node.position.x, y: node.position.y };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      INTERNALS                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Decides which connector reads and which one writes.
     *
     * Outgoing means DataGerry is read and the foreign system written; incoming is the mirror image.
     */
    private resolveSides(definition: AutomationDefinition, context: AutomationCompileContext): ResolvedSides {
        const outgoing = definition.direction === 'outgoing';
        const sourceConnector = outgoing ? context.internalConnector : context.targetConnector;
        const targetConnector = outgoing ? context.targetConnector : context.internalConnector;

        return {
            sourceConnector,
            targetConnector,
            source: this.catalog.resolveOperation(sourceConnector?.invoker, 'list'),
            target: this.catalog.resolveOperation(targetConnector?.invoker, definition.target.operation)
        };
    }


    private collectResolutionWarnings(
        definition: AutomationDefinition,
        sides: ResolvedSides,
        warnings: string[]
    ): void {
        if (sides.source && !sides.source.verified) {
            warnings.push(
                `The read operation "${sides.source.name}" was matched by name similarity, not from a `
                + 'verified interface description. Run the test step before activating.'
            );
        }

        if (sides.target && !sides.target.verified) {
            warnings.push(
                `The "${definition.target.operation}" operation "${sides.target.name}" was matched by name `
                + 'similarity, not from a verified interface description. Run the test step before activating.'
            );
        }

        if (definition.direction === 'outgoing') {
            warnings.push(
                'Outgoing automations address DataGerry fields by their position in the object type. '
                + 'Reordering the type\'s fields later requires saving this automation again.'
            );
        }
    }


    /** Turns an operation name into a compact label, mirroring the reference's 'GetObjects'. */
    private friendlyLabel(operationName: string): string {
        const words = operationName.split(/[^A-Za-z0-9]+/).filter(Boolean);

        if (words.length === 0) {
            return operationName;
        }

        return words.map(word => word.charAt(0).toUpperCase() + word.slice(1)).join('');
    }


    private clone<T>(value: T): T {
        return JSON.parse(JSON.stringify(value ?? null));
    }


    /** RFC 4122 version 4 identifier, as OpenCelium uses for operator uiIds. */
    private uuid(): string {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID();
        }

        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, char => {
            const random = Math.random() * 16 | 0;
            const value = char === 'x' ? random : (random & 0x3 | 0x8);

            return value.toString(16);
        });
    }
}


/**
 * Where a mapping entry's value comes from.
 *
 * 'path' is read out of the source system's answer and needs a fieldBinding; 'constant' is written
 * into the request as a literal, exactly as the reference payloads carry their own fixed values.
 */
type SourceValue =
    | { kind: 'path'; path: string }
    | { kind: 'constant'; value: string };


/** The two operations and connectors an automation runs across. */
interface ResolvedSides {
    sourceConnector: any;
    targetConnector: any;
    source: ResolvedOperation | null;
    target: ResolvedOperation | null;
}
