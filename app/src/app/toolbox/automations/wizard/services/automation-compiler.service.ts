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
    AutomationMatchOutcome,
    AutomationRuleOperator,
    findSystemField,
    isTriggerSupported,
    outcomeWrites,
    requiresMatching,
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
    ocIfNodeId,
    ocLoopNodeId,
    ocMethodNodeId,
    ocPresenceExpression,
    OC_DEFAULT_CONNECTOR_ID,
    OC_DEFAULT_CONNECTOR_TITLE,
    OC_IS_EMPTY,
    OC_LOOP_INDEX,
    OC_METHOD_COLORS,
    OC_SCHEDULER_ACTIVE,
    OC_SCHEDULER_INACTIVE,
    OC_NOT_EMPTY,
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

        // Without it the automation has no way of telling which object over there it means, so
        // updating and deleting would act on nothing and creating would duplicate on every run.
        if (requiresMatching(definition) && !definition.matching.identifyBy) {
            errors.push(
                'Mark the field that identifies the object in the target system, so the automation '
                + 'can find the object it should act on.'
            );
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

        const palette = OC_METHOD_COLORS;
        const sourceMethod = this.buildMethod(
            sides.source,
            sides.sourceConnector,
            ocMethodNodeId(0),
            OC_SOURCE_INDEX,
            palette[0],
            AutomationCompilerService.SOURCE_LABEL
        );

        this.applyListFilter(definition, sides, sourceMethod, warnings);
        this.applyListLimit(definition, sides, sourceMethod);

        const loop = this.buildLoopOperator(sides.source.responseArrayPath);
        const methods: OcMethod[] = [sourceMethod];
        const operators: OcOperator[] = [loop];
        const bindings: OcFieldBinding[] = [];
        const graph: GraphNode[] = [
            { id: AutomationCompilerService.START_NODE, kind: 'start', parent: '' },
            { id: sourceMethod.id, kind: 'method', parent: AutomationCompilerService.START_NODE, method: sourceMethod },
            { id: loop.id, kind: 'loop', parent: sourceMethod.id, operator: loop }
        ];

        // A restriction on which objects take part is an `if` of its own inside the loop, not a
        // property of the loop: the loop's expression is the collection it walks, and the engine
        // reads nothing else. Everything the loop does then hangs off that gate instead.
        const container = this.buildConditionGate(definition, context, sides, loop, operators, graph, warnings);
        const plan = this.planBranches(definition);

        if (plan.length === 0) {
            // No lookup: the single write hangs straight off the loop, which is what an automation
            // that only ever adds looks like.
            const writeMethod = this.buildMethod(
                sides.target,
                sides.targetConnector,
                ocMethodNodeId(1),
                `${container.index}_0`,
                palette[1],
                null
            );

            methods.push(writeMethod);
            bindings.push(...this.buildFieldBindings(definition, context, sides, writeMethod, warnings));
            graph.push({ id: writeMethod.id, kind: 'method', parent: container.id, method: writeMethod, below: true });
        } else {
            this.buildMatchedBranches(definition, context, sides, plan, {
                palette, methods, operators, bindings, graph, container, warnings
            });
        }

        return {
            title: definition.name,
            name: definition.name,
            description: definition.description,
            fieldBinding: bindings,
            fromConnector: {
                connectorId: OC_DEFAULT_CONNECTOR_ID,
                title: OC_DEFAULT_CONNECTOR_TITLE,
                methods,
                operators
            },
            toConnector: null,
            ui: this.buildUi(graph, withEdgeData)
        };
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       MATCHING                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * The `if` that restricts which objects take part, when the user asked for one.
     *
     * Returns whatever the loop's children should hang off: the gate when there is one, the loop
     * itself otherwise. The rule tree is handed to the node rather than parsed back out of the
     * expression, because a group of rules does not read back from a single string.
     */
    private buildConditionGate(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        loop: OcOperator,
        operators: OcOperator[],
        graph: GraphNode[],
        warnings: string[]
    ): { id: string; index: string } {
        const expression = this.buildConditionExpression(
            definition,
            context,
            sides.source!.responseArrayPath,
            warnings
        );

        if (!expression) {
            return { id: loop.id, index: loop.index };
        }

        const gate: OcOperator = {
            id: ocIfNodeId('gate'),
            index: `${loop.index}_0`,
            type: 'if',
            dataAggregator: null,
            expression,
            iterator: null
        };

        operators.push(gate);
        graph.push({
            id: gate.id,
            kind: 'if',
            parent: loop.id,
            operator: gate,
            below: true,
            tree: this.buildConditionUiGroup(gate.id, definition.conditions)
        });

        return { id: gate.id, index: gate.index };
    }


    /**
     * The branches the automation needs, in the order they are laid out.
     *
     * An outcome that writes nothing needs neither an `if` nor a method, so a plain "update what is
     * there, ignore the rest" produces a single branch rather than an empty second one.
     */
    private planBranches(definition: AutomationDefinition): PlannedBranch[] {
        if (!requiresMatching(definition) || !definition.matching.identifyBy) {
            return [];
        }

        const branches: PlannedBranch[] = [];
        const { whenMissing, whenPresent } = definition.matching;

        if (outcomeWrites(whenMissing)) {
            branches.push({ presence: OC_IS_EMPTY, outcome: whenMissing });
        }

        if (outcomeWrites(whenPresent)) {
            branches.push({ presence: OC_NOT_EMPTY, outcome: whenPresent });
        }

        return branches;
    }


    /**
     * Builds the lookup and the branches that hang off it.
     *
     * The lookup asks the target system whether it already holds the object, filtered by the pair
     * the user marked as identifying. Each branch is an `if` on that answer with its own write
     * method below it; a second branch hangs off the first one's false exit, which is how the
     * capture spells "otherwise".
     */
    private buildMatchedBranches(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        plan: PlannedBranch[],
        out: BranchBuildContext
    ): void {
        const { palette, methods, operators, bindings, graph, container, warnings } = out;
        const lookup = this.resolveLookup(sides, warnings);

        if (!lookup) {
            return;
        }

        const lookupMethod = this.buildMethod(
            lookup,
            sides.targetConnector,
            ocMethodNodeId(methods.length),
            `${container.index}_0`,
            palette[methods.length % palette.length],
            null
        );

        methods.push(lookupMethod);
        graph.push({
            id: lookupMethod.id, kind: 'method', parent: container.id, method: lookupMethod, below: true
        });
        this.bindLookupFilter(definition, context, sides, lookup, lookupMethod, bindings, warnings);

        let parent = lookupMethod.id;

        plan.forEach((branch, position) => {
            const operation = this.resolveBranchOperation(sides, branch.outcome, warnings);

            if (!operation) {
                return;
            }

            const conditional = this.buildIfOperator(
                ocIfNodeId(position),
                `${container.index}_${position + 1}`,
                lookupMethod.color,
                lookup.responseArrayPath,
                branch.presence
            );
            const writeMethod = this.buildMethod(
                operation,
                sides.targetConnector,
                ocMethodNodeId(methods.length),
                `${conditional.index}_0`,
                palette[methods.length % palette.length],
                null
            );

            operators.push(conditional);
            methods.push(writeMethod);
            graph.push({
                id: conditional.id,
                kind: 'if',
                parent,
                operator: conditional,
                // The first branch follows the lookup; every further one the previous branch's miss.
                branch: position === 0 ? undefined : 'false'
            });
            graph.push({
                id: writeMethod.id, kind: 'method', parent: conditional.id, method: writeMethod,
                below: true, branch: 'true'
            });

            bindings.push(...this.buildBranchBindings(
                definition, context, sides, branch, lookup, lookupMethod, writeMethod, warnings
            ));

            parent = conditional.id;
        });
    }


    /** The operation that answers "do you already have this object". */
    private resolveLookup(sides: ResolvedSides, warnings: string[]): ResolvedOperation | null {
        const lookup = this.catalog.resolveOperation(sides.targetConnector?.invoker, 'list');

        if (!lookup) {
            warnings.push(
                'The target system offers no operation for reading objects, so the automation cannot '
                + 'check whether an object already exists. Nothing is written.'
            );

            return null;
        }

        if (!lookup.responseArrayPath) {
            warnings.push(
                `The read operation "${lookup.name}" does not answer with a list, so a hit cannot be `
                + 'told from a miss. Nothing is written.'
            );

            return null;
        }

        return lookup;
    }


    private resolveBranchOperation(
        sides: ResolvedSides,
        outcome: AutomationMatchOutcome,
        warnings: string[]
    ): ResolvedOperation | null {
        const operation = this.catalog.resolveOperation(
            sides.targetConnector?.invoker,
            outcome as 'create' | 'update' | 'delete'
        );

        if (!operation) {
            warnings.push(`The target system offers no operation for "${outcome}", so that branch was skipped.`);
        }

        return operation;
    }


    private buildIfOperator(
        id: string,
        index: string,
        lookupColor: string,
        lookupArrayPath: string,
        presence: string
    ): OcOperator {
        return {
            id,
            index,
            type: 'if',
            dataAggregator: null,
            expression: ocPresenceExpression(lookupColor, lookupArrayPath, presence),
            iterator: null
        };
    }


    /**
     * Tells the lookup which object to look for.
     *
     * The identifying pair names a field on both sides; its target name is what the lookup filters
     * on, so `params.title` on the write becomes `params.filter.title` on the search.
     */
    private bindLookupFilter(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        lookup: ResolvedOperation,
        lookupMethod: OcMethod,
        bindings: OcFieldBinding[],
        warnings: string[]
    ): void {
        const entry = definition.mapping.find(pair => pair.source === definition.matching.identifyBy);
        const filter = this.catalog.matchFilter(sides.targetConnector?.invoker, lookup);

        if (!entry?.target || !filter) {
            warnings.push(
                'The target system\'s read operation takes no filter on an ordinary field, so the '
                + 'automation cannot look an object up. Nothing is written.'
            );

            return;
        }

        const key = entry.target.slice(entry.target.lastIndexOf('.') + 1);

        if (!filter.keys.includes(key)) {
            warnings.push(
                `The read operation cannot search by "${key}". It searches by `
                + `${filter.keys.join(', ')} - identify the object by one of those instead.`
            );

            return;
        }

        bindings.push(...this.buildFieldBindings(
            { ...definition, mapping: [{ ...entry, target: `${filter.basePath}.${key}` }] },
            context,
            sides,
            lookupMethod,
            warnings
        ));
    }


    /**
     * What a branch writes: the mapped fields, plus the identifier of the object that was found.
     *
     * A delete gets the identifier alone - the other fields have nowhere to go in a request that
     * only names what to remove, and writing them would invent keys the operation does not have.
     */
    private buildBranchBindings(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        branch: PlannedBranch,
        lookup: ResolvedOperation,
        lookupMethod: OcMethod,
        writeMethod: OcMethod,
        warnings: string[]
    ): OcFieldBinding[] {
        const bindings = branch.outcome === 'delete'
            ? []
            : this.buildFieldBindings(definition, context, sides, writeMethod, warnings);

        if (branch.outcome === 'create') {
            return bindings;
        }

        const idBinding = this.bindElementId(definition, lookup, lookupMethod, writeMethod, warnings);

        return idBinding ? [idBinding, ...bindings] : bindings;
    }


    /**
     * Hands the found object's identifier to the operation that acts on it.
     *
     * The only reference in the whole payload that reads another method's answer rather than the
     * source, and the reason a lookup is needed at all.
     */
    private bindElementId(
        definition: AutomationDefinition,
        lookup: ResolvedOperation,
        lookupMethod: OcMethod,
        writeMethod: OcMethod,
        warnings: string[]
    ): OcFieldBinding | null {
        const invoker = lookupMethod.connector.invokerName ? { name: lookupMethod.connector.invokerName } : null;
        const elementId = this.catalog.elementIdPath(invoker, lookup);
        const mapped = definition.mapping.find(entry => entry.target)?.target ?? '';
        const writeId = this.catalog.writeIdPath(
            { name: writeMethod.name, definition: { request: writeMethod.request }, responseArrayPath: '', verified: true },
            mapped
        );

        if (!elementId || !writeId) {
            warnings.push(
                `The automation could not work out where "${writeMethod.name}" takes the identifier of `
                + 'the object it acts on, so no identifier is passed. Set it in the technical view.'
            );

            return null;
        }

        // The lookup's answer is nobody's loop, so the first hit is meant rather than an iterator.
        const sourcePath = `body.$.${ocCollectionElementPath(lookup.responseArrayPath, elementId, '0')}`;
        const targetPath = `body.$.${writeId}`;

        this.setBodyField(
            writeMethod.request,
            writeId,
            ocFieldReference(lookupMethod.color, 'response', ocCollectionElementPath(lookup.responseArrayPath, elementId, '0'))
        );

        return {
            from: [{ color: lookupMethod.color, field: sourcePath, type: 'response' }],
            to: [{ color: writeMethod.color, field: targetPath, type: 'request' }],
            enhancement: this.buildEnhancement(
                sourcePath,
                targetPath,
                writeMethod.color,
                { source: definition.matching.identifyBy, target: writeId, origin: 'auto', confidence: 1 },
                warnings
            )
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
                to: [{ color: targetMethod.color, field: targetPath, type: 'request' }],
                enhancement: this.buildEnhancement(sourcePath, targetPath, targetMethod.color, entry, warnings)
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
            to: [{ color: targetMethod.color, field: targetPath, type: 'request' }],
            enhancement: this.buildEnhancement(
                sourcePath, targetPath, targetMethod.color, entry, warnings, literal
            )
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
        targetColor: string,
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
            expertVar: `//var RESULT_VAR = ${targetColor}.(request).${targetPath};\n`
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
    /**
     * The user's conditions, in the language OpenCelium's expression parser reads.
     *
     * Not JavaScript, which is what this produced before and what nothing on the other side could
     * evaluate. Operands are references wrapped in {%...%} or quoted literals; operators come from
     * the engine's own RelationalOperator vocabulary; terms are parenthesised and joined with &&
     * or ||, exactly as its parser tests spell out.
     */
    private buildConditionExpression(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        arrayPath: string,
        warnings: string[]
    ): string {
        const group = definition.conditions;
        const joiner = group.combinator === 'and' ? ' && ' : ' || ';
        const parts: string[] = [];

        for (const rule of group.rules) {
            // The same resolution the mapping uses. A rule names a field the way the user knows it,
            // and on the DataGerry side that is not where the value sits: business fields live in a
            // positional `fields[n].value`, so using the name as a path restricts on nothing.
            const value = this.resolveSourceValue(definition, context, rule.field, warnings);

            if (!value) {
                continue;
            }

            if (value.kind === 'constant') {
                warnings.push(
                    `The condition on "${rule.field}" compares a fixed value against itself, which is `
                    + 'either always or never true, so it was left out.'
                );

                continue;
            }

            parts.push(this.renderRule(
                `{%${ocFieldReference(
                    AutomationCompilerService.SOURCE_COLOR,
                    'response',
                    ocCollectionElementPath(arrayPath, value.path)
                )}%}`,
                rule.operator,
                rule.value
            ));
        }

        if (parts.length === 0) {
            return '';
        }

        const expression = parts.length > 1 ? `(${parts.join(joiner)})` : parts[0];

        return group.negate ? `!(${expression})` : expression;
    }


    /**
     * One rule as a parenthesised term.
     *
     * Two of the mappings are worth knowing about. A "contains" on text becomes `Like "%v%"` rather
     * than `Contains`, because the engine's Contains works on a list and would throw on a string.
     * And "is empty" becomes two terms, because a field can be empty by being absent or by holding
     * an empty string, and the engine treats those as different things.
     */
    private renderRule(left: string, operator: AutomationRuleOperator, value: string): string {
        const text = `"${(value ?? '').replace(/"/g, '\\"')}"`;
        const number = Number(value);
        const numeric = Number.isFinite(number) ? String(number) : '0';

        switch (operator) {
            case 'equals':
                return `(${left} = ${text})`;
            case 'not_equals':
                return `(${left} != ${text})`;
            case 'contains':
                return `(${left} Like "%${value}%")`;
            case 'not_contains':
                return `(${left} NotLike "%${value}%")`;
            case 'starts_with':
                return `(${left} Like "${value}%")`;
            case 'ends_with':
                return `(${left} Like "%${value}")`;
            case 'is_empty':
                return `((${left} IsNull) || (${left} = ""))`;
            case 'is_not_empty':
                return `((${left} NotNull) && (${left} != ""))`;
            case 'greater_than':
                return `(${left} > ${numeric})`;
            case 'less_than':
                return `(${left} < ${numeric})`;
            default:
                return `(${left} = ${text})`;
        }
    }


    /** An untouched condition tree - what the loop node carries when nothing restricts it. */
    private emptyConditionTree(): OcUiGroup {
        return { id: '0-group', type: 'group', properties: { not: false }, items: [] };
    }


    private buildConditionUiGroup(uiId: string, group: AutomationConditionGroup): OcUiGroup {
        return {
            id: `${uiId}-group`,
            type: 'group',
            properties: { not: group.negate },
            items: group.rules.map((rule, position) => ({
                id: `${uiId}-rule-${position}`,
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
    private buildUi(graph: GraphNode[], withEdgeData: boolean): OcUi {
        const positions = this.layout(graph);
        const nodes = graph.map(node => this.workflowNode(node, positions.get(node.id)!));
        const edges = graph
            .filter(node => node.parent)
            .map(node => this.edge(node));

        return {
            viewport: { ...OC_UI_LAYOUT.viewport },
            workflowNodes: nodes,
            workflowEdges: edges.map(edge => this.workflowEdge(edge, withEdgeData)),
            flowcharts: nodes.map(node => this.flowchart(node)),
            flowchartEdges: edges
        };
    }


    /**
     * Places the graph on the grid the captures use.
     *
     * A node continues its parent's row unless it runs inside it - a looped or conditional method
     * drops a row instead, which is what `below` marks. Either way it moves one column right of the
     * furthest node placed so far, so branches never land on top of each other.
     */
    private layout(graph: GraphNode[]): Map<string, { x: number; y: number }> {
        const { startX, stepX, rowY, branchDy } = OC_UI_LAYOUT;
        const positions = new Map<string, { x: number; y: number }>();
        let rightmost = startX - stepX;

        for (const node of graph) {
            const parent = node.parent ? positions.get(node.parent) : null;

            if (!parent) {
                positions.set(node.id, { x: startX, y: rowY });
                rightmost = startX;

                continue;
            }

            const x = node.below ? parent.x : Math.max(parent.x + stepX, rightmost + stepX);
            const y = node.below ? parent.y + branchDy : parent.y;

            positions.set(node.id, { x, y });
            rightmost = Math.max(rightmost, x);
        }

        return positions;
    }


    private workflowNode(node: GraphNode, position: { x: number; y: number }): OcWorkflowNode {
        if (node.kind === 'start') {
            return {
                id: node.id,
                type: 'start',
                position,
                data: { title: '', kind: 'start' },
                draggable: true,
                deletable: false
            };
        }

        if (node.kind === 'method') {
            return { ...this.connectorNode(node.method!, position) };
        }

        const operator = node.operator!;

        return {
            id: operator.id,
            type: node.kind,
            position,
            index: operator.index,
            data: node.kind === 'loop'
                ? {
                    title: 'Loop',
                    subtitle: operator.expression,
                    kind: 'loop',
                    conditionConfig: {
                        operatorType: 'loop',
                        tree: node.tree ?? this.emptyConditionTree(),
                        expression: operator.expression,
                        iterator: operator.iterator
                    }
                }
                : {
                    title: 'If',
                    kind: 'if',
                    conditionConfig: {
                        operatorType: 'if',
                        tree: node.tree ?? this.presenceTree(operator),
                        expression: operator.expression
                    }
                }
        };
    }


    /** The rule-builder form of an `if`, restating its expression as a single presence rule. */
    private presenceTree(operator: OcOperator): OcUiGroup {
        const [, reference, presence] = /^\((?:\{%)(.*?)(?:%\})\s+(\w+)\)$/.exec(operator.expression)
            ?? ['', '', ''];

        return {
            id: `${operator.id}-group`,
            type: 'group',
            properties: { not: false },
            items: [{
                id: `${operator.id}-rule`,
                type: 'rule',
                properties: { leftField: reference, operator: presence, rightField: '' }
            }]
        };
    }


    /**
     * How a node hangs off its parent.
     *
     * A node that runs inside its parent enters from the top; one that follows it enters from the
     * left. An `if` sends its hit down its `true` exit and everything else along `false`, which is
     * how a second branch is reached.
     */
    private edge(node: GraphNode): OcFlowchartEdge {
        const sourceHandle = node.branch ?? (node.below ? 'bottom' : undefined);
        const edge: OcFlowchartEdge = {
            id: '',
            source: node.parent,
            target: node.id,
            targetHandle: node.below ? 'top' : 'left'
        };

        if (sourceHandle) {
            edge.sourceHandle = sourceHandle;
        }

        edge.id = ocEdgeId(edge);

        return edge;
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


/** One branch of the lookup: what to do, and which answer selects it. */
interface PlannedBranch {
    /** IsEmpty or NotEmpty - which side of the lookup's answer this branch is for. */
    presence: string;
    outcome: AutomationMatchOutcome;
}


/** A node of the workflow graph, from which both the ui block and its edges are derived. */
interface GraphNode {
    id: string;
    kind: 'start' | 'method' | 'loop' | 'if';

    /** Ui id of the node this one hangs off; empty on the start node. */
    parent: string;
    method?: OcMethod;
    operator?: OcOperator;

    /** True when the node runs inside its parent and is drawn a row below it. */
    below?: boolean;

    /** Which exit of an `if` parent leads here. */
    branch?: 'true' | 'false';

    /** Rule tree for an `if` whose expression does not read back as a single rule. */
    tree?: OcUiGroup;
}


/** Everything buildMatchedBranches appends to while it walks the plan. */
interface BranchBuildContext {
    palette: ReadonlyArray<string>;
    methods: OcMethod[];
    operators: OcOperator[];
    bindings: OcFieldBinding[];
    graph: GraphNode[];

    /** What the loop's children hang off - the loop, or the gate that restricts it. */
    container: { id: string; index: string };
    warnings: string[];
}


/** The two operations and connectors an automation runs across. */
interface ResolvedSides {
    sourceConnector: any;
    targetConnector: any;
    source: ResolvedOperation | null;
    target: ResolvedOperation | null;
}
