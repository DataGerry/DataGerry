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
    AutomationRuleOperator,
    isTriggerSupported
} from '../models/automation-definition.model';
import {
    OcArrow,
    OcConnection,
    OcCreateAutomationRequest,
    OcFieldBinding,
    OcMethod,
    OcOperator,
    OcSchedulerPayload,
    OcSvgItem,
    OcUiGroup,
    OcUiRule,
    ocCollectionElementPath,
    ocEmptyError,
    ocFieldReference,
    ocLoopExpression,
    OC_EXPERT_TEMPLATE,
    OC_FROM_CONNECTOR,
    OC_LAYOUT,
    OC_METHOD_COLORS,
    OC_SCHEDULER_ACTIVE,
    OC_SCHEDULER_INACTIVE,
    OC_TO_CONNECTOR
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
 * installation, down to which keys appear on a method versus its svgItem entity. Where the
 * references give no example - the outgoing direction and user conditions - the compiler derives
 * the shape from the schema and says so through a warning rather than pretending certainty.
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
    private static readonly SOURCE_INDEX = '0';
    private static readonly TARGET_INDEX = '0_0';
    private static readonly LOOP_ITERATOR = 'i';

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
        const connection = this.buildConnection(definition, context, warnings, false);

        connection.id = 0;

        return {
            payload: { connection, scheduler: this.buildScheduler(definition) },
            warnings
        };
    }


    /**
     * Builds the body of PUT /rest/open_celium/connections/:id.
     *
     * Here the connectors do carry their title and the connection repeats its id in both `id` and
     * `connectionId`, again matching the reference update payload.
     */
    public compileForUpdate(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        connectionId: number
    ): CompilationOutcome<OcConnection> {
        const warnings: string[] = [];
        const connection = this.buildConnection(definition, context, warnings, true);

        connection.id = connectionId;
        connection.connectionId = connectionId;
        this.stripInvokerCredentials(connection);

        return { payload: connection, warnings };
    }


    /**
     * Blanks the credential fields of every embedded invoker.
     *
     * The reference update payload sends invoker.data and invoker.auth as empty strings while the
     * create payload carries the real values - credentials are established once with the connector
     * and are not resent when a connection is edited.
     */
    private stripInvokerCredentials(connection: OcConnection): void {
        const invokers = [
            connection.fromConnector.invoker,
            connection.toConnector.invoker,
            ...connection.fromConnector.svgItems.map(item => item.entity?.invoker),
            ...connection.toConnector.svgItems.map(item => item.entity?.invoker)
        ];

        invokers.filter(Boolean).forEach(invoker => {
            invoker.data = '';
            invoker.auth = '';
        });
    }


    /** The scheduler half of an automation, derived entirely from trigger and advanced settings. */
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

    private buildConnection(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        warnings: string[],
        includeConnectorTitles: boolean
    ): OcConnection {
        const sides = this.resolveSides(definition, context);

        if (!sides.source || !sides.target) {
            throw new Error('The automation cannot be compiled - validate() first.');
        }

        this.collectResolutionWarnings(definition, sides, warnings);

        const sourceMethod = this.buildMethod(
            sides.source,
            AutomationCompilerService.SOURCE_INDEX,
            AutomationCompilerService.SOURCE_COLOR,
            AutomationCompilerService.SOURCE_LABEL
        );

        this.applyListFilter(definition, sides, sourceMethod, warnings);
        this.applyListLimit(definition, sides, sourceMethod);
        const targetMethod = this.buildMethod(
            sides.target,
            AutomationCompilerService.TARGET_INDEX,
            AutomationCompilerService.TARGET_COLOR,
            null
        );

        const bindings = this.buildFieldBindings(definition, context, sides, targetMethod, warnings);
        const loop = this.buildLoopOperator(sides.source.responseArrayPath);
        const uiGroups: OcUiGroup[] = [this.buildLoopUiGroup(loop)];

        if (definition.conditions.rules.length > 0) {
            warnings.push(
                'Conditions are compiled into the loop operator\'s condition. No reference payload '
                + 'covers a populated condition yet, so run the test step before activating.'
            );
            loop.condition = this.buildConditionExpression(
                definition.conditions,
                sides.source.responseArrayPath
            );
            uiGroups.push(this.buildConditionUiGroup(this.uuid(), definition.conditions));
        }

        return {
            title: definition.name,
            description: definition.description,
            fromConnector: this.buildConnectorSide(
                sides.sourceConnector,
                [sourceMethod],
                [],
                OC_FROM_CONNECTOR,
                AutomationCompilerService.SOURCE_INDEX,
                includeConnectorTitles
            ),
            toConnector: this.buildConnectorSide(
                sides.targetConnector,
                [targetMethod],
                [loop],
                OC_TO_CONNECTOR,
                AutomationCompilerService.TARGET_INDEX,
                includeConnectorTitles
            ),
            fieldBinding: bindings,
            categoryId: null,
            ui: { operators: uiGroups },
            id: 0,
            template: OC_EXPERT_TEMPLATE,
            readOnly: false
        };
    }


    /**
     * Assembles one side of the connection.
     *
     * `methods` entries carry an `error` block but no invoker, while their svgItem `entity`
     * carries the invoker but no `error` - an asymmetry taken verbatim from the reference payloads.
     */
    private buildConnectorSide(
        connector: any,
        methods: OcMethod[],
        operators: OcOperator[],
        connectorType: string,
        currentItemIndex: string,
        includeTitle: boolean
    ): any {
        // Cloned so later post-processing - stripping credentials for the update payload - cannot
        // reach back into the caller's connector objects.
        const invoker = this.clone(connector.invoker);

        const side: any = {
            invoker,
            connectorId: connector.connectorId,
            methods,
            icon: connector.icon ?? '',
            operators
        };

        if (includeTitle) {
            side.title = connector.title;
        }

        side.currentItemIndex = currentItemIndex;
        side.svgItems = this.buildSvgItems(invoker, methods, operators, connectorType);
        side.arrows = this.buildArrows(operators, connectorType);

        return side;
    }


    /**
     * Builds one method entry.
     *
     * The reference payloads omit `label` entirely on the target method rather than sending null,
     * so the key is only added when there is a label to send.
     */
    private buildMethod(
        operation: ResolvedOperation,
        index: string,
        color: string,
        label: string | null
    ): OcMethod {
        const method: any = {
            name: operation.name,
            request: this.clone(operation.definition.request),
            response: this.clone(operation.definition.response),
            dataAggregator: null,
            index
        };

        if (label !== null) {
            method.label = label;
        }

        method.color = color;
        method.error = ocEmptyError();

        return method as OcMethod;
    }


    private buildLoopOperator(arrayPath: string): OcOperator {
        return {
            index: AutomationCompilerService.SOURCE_INDEX,
            type: 'loop',
            condition: null,
            expression: ocLoopExpression(AutomationCompilerService.SOURCE_COLOR, arrayPath),
            uiId: this.uuid(),
            dataAggregator: null,
            iterator: AutomationCompilerService.LOOP_ITERATOR,
            error: ocEmptyError()
        };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   FIELD BINDINGS                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Wires each mapped field pair.
     *
     * Two things happen per pair: the reference string is written straight into the target method's
     * request body, and a fieldBinding entry records the same pair with the enhancement script
     * OpenCelium executes. The reference payloads contain both, so both are produced.
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

            const sourceField = this.resolveSourceFieldPath(definition, context, entry.source, warnings);

            if (!sourceField) {
                continue;
            }

            const sourcePath = `body.$.${ocCollectionElementPath(arrayPath, sourceField)}`;
            const targetPath = `body.$.${entry.target}`;
            const reference = ocFieldReference(
                AutomationCompilerService.SOURCE_COLOR,
                'response',
                ocCollectionElementPath(arrayPath, sourceField)
            );

            this.setBodyField(targetMethod.request, entry.target, reference);

            bindings.push({
                from: [{ color: AutomationCompilerService.SOURCE_COLOR, field: sourcePath, type: 'response' }],
                to: [{ color: AutomationCompilerService.TARGET_COLOR, field: targetPath, type: 'request' }],
                enhancement: {
                    name: '',
                    description: '',
                    language: 'js',
                    simpleCode: null,
                    expertVar: `//var RESULT_VAR = ${AutomationCompilerService.TARGET_COLOR}.(request).${targetPath};\n`
                        + `//var VAR_0 = ${AutomationCompilerService.SOURCE_COLOR}.(response).${sourcePath};`,
                    expertCode: 'RESULT_VAR = VAR_0;'
                }
            });
        }

        return bindings;
    }


    /**
     * Works out how to address a source field.
     *
     * When the source is a foreign system the mapping already holds its response path. When the
     * source is DataGerry, the value lives inside the `fields` array of the object, which OpenCelium
     * addresses positionally - hence the lookup through the type's field order.
     */
    private resolveSourceFieldPath(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        source: string,
        warnings: string[]
    ): string | null {
        if (definition.direction === 'incoming') {
            return source;
        }

        return this.resolveDataGerryFieldPath(context, source, warnings);
    }


    /**
     * Positional path of a DataGerry object field.
     *
     * DataGerry's object endpoints answer with `fields: [{ name, value }, ...]` in the order the
     * type declares them, so a business field is addressed by its index in that declaration. No
     * reference payload covers the outgoing direction, so this derivation is reported as a warning.
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
            warnings.push(
                'Filtering DataGerry by object type is applied as a query parameter. No reference '
                + 'payload covers the outgoing direction, so run the test step before activating.'
            );

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


    /**
     * The rule-builder representation of the loop, mirroring the reference payload's ui.operators.
     *
     * leftField is the loop expression without its leading `for `, which is exactly what the
     * reference stores.
     */
    private buildLoopUiGroup(loop: OcOperator): OcUiGroup {
        const rule: OcUiRule = {
            id: this.uuid(),
            type: 'rule',
            properties: {
                operator: 'for',
                leftField: loop.expression.replace(/^for\s+/, ''),
                rightField: ''
            }
        };

        return { id: loop.uiId, type: 'group', properties: { not: false }, items: [rule] };
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
/*                                                      SVG GRAPH                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Rebuilds the visual graph OpenCelium stores alongside the executable definition.
     *
     * Coordinates come from the reference payloads: the source method sits at the origin, the target
     * loop top right with its method below it.
     */
    private buildSvgItems(
        invoker: any,
        methods: OcMethod[],
        operators: OcOperator[],
        connectorType: string
    ): OcSvgItem[] {
        const items: OcSvgItem[] = [];
        const isTarget = connectorType === OC_TO_CONNECTOR;

        for (const operator of operators) {
            items.push({
                id: `${connectorType}_${operator.index}`,
                type: operator.type,
                label: '',
                x: OC_LAYOUT.targetOperatorX,
                y: OC_LAYOUT.targetOperatorY,
                width: OC_LAYOUT.operatorWidth,
                height: OC_LAYOUT.operatorHeight,
                isDragged: false,
                isDraggedForCopy: false,
                isAvailableForDragging: false,
                isSelectedAll: false,
                connectorType,
                invoker: null,
                entity: this.operatorEntity(operator),
                items: [],
                arrows: []
            });
        }

        for (const method of methods) {
            items.push({
                id: `${connectorType}_${method.index}`,
                name: method.name,
                x: isTarget ? OC_LAYOUT.targetMethodX : OC_LAYOUT.sourceMethodX,
                y: isTarget ? OC_LAYOUT.targetMethodY : OC_LAYOUT.sourceMethodY,
                width: OC_LAYOUT.methodWidth,
                height: OC_LAYOUT.methodHeight,
                isDragged: false,
                isDraggedForCopy: false,
                isAvailableForDragging: false,
                isSelectedAll: false,
                connectorType,
                invoker: null,
                entity: this.methodEntity(method, invoker)
            });
        }

        return items;
    }


    /** The svgItem entity of a method: the method plus its invoker, without the error block. */
    private methodEntity(method: OcMethod, invoker: any): any {
        const entity: any = {
            name: method.name,
            request: method.request,
            response: method.response,
            dataAggregator: null,
            index: method.index
        };

        if (method.label !== undefined && method.label !== null) {
            entity.label = method.label;
        }

        entity.color = method.color;
        entity.invoker = invoker;

        return entity;
    }


    /** The svgItem entity of an operator: the operator without its error block. */
    private operatorEntity(operator: OcOperator): any {
        return {
            index: operator.index,
            type: operator.type,
            condition: operator.condition,
            expression: operator.expression,
            uiId: operator.uiId,
            dataAggregator: null,
            iterator: operator.iterator
        };
    }


    /** Links each operator to the method it wraps. */
    private buildArrows(operators: OcOperator[], connectorType: string): OcArrow[] {
        if (operators.length === 0) {
            return [];
        }

        return [{
            from: `${connectorType}_${AutomationCompilerService.SOURCE_INDEX}`,
            to: `${connectorType}_${AutomationCompilerService.TARGET_INDEX}`
        }];
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


/** The two operations and connectors an automation runs across. */
interface ResolvedSides {
    sourceConnector: any;
    targetConnector: any;
    source: ResolvedOperation | null;
    target: ResolvedOperation | null;
}
