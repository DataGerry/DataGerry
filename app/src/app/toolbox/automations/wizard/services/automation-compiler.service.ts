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
    AutomationCallCondition,
    AutomationCallOverride,
    AutomationDefinition,
    AutomationExtraCall,
    AutomationMappingEntry,
    AutomationMatchOutcome,
    AutomationRuleOperator,
    AutomationValueTransform,
    findSystemField,
    isTriggerSupported,
    outcomeWrites,
    requiresMatching,
    seedsItsOwnCalls,
    sourceValueOf,
    writesIntoDataGerry,
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
    OcUiRule,
    OcWorkflowEdge,
    OcWorkflowNode,
    ocCollectionElementPath,
    ocEdgeId,
    ocFieldReference,
    ocLoopExpression,
    ocIfNodeId,
    ocLoopNodeId,
    ocMethodNodeId,
    ocParseReference,
    ocPresenceExpression,
    ocPresenceField,
    ocSystemNodeId,
    OC_DEFAULT_CONNECTOR_ID,
    OC_DEFAULT_CONNECTOR_TITLE,
    OC_FREE_REQUEST,
    OC_FREE_REQUEST_TITLE,
    OC_IS_EMPTY,
    OC_LOOP_INDEX,
    OC_LOOP_ITERATOR,
    OC_METHOD_COLORS,
    OC_SCHEDULER_ACTIVE,
    OC_SCHEDULER_INACTIVE,
    OC_NOT_EMPTY,
    OC_PAGING_OPERATION,
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
     * Everything that stands between the automation and being saved.
     *
     * Returned as a list rather than thrown so the wizard can show all problems at once on the
     * summary step instead of revealing them one by one.
     */
    public validate(definition: AutomationDefinition, context: AutomationCompileContext): string[] {
        const errors = this.structuralErrors(definition, context);

        return errors.length > 0 ? errors : this.readinessErrors(definition);
    }


    /**
     * What has to hold before the connection can be built at all.
     *
     * Kept apart from the rest because the sequence is put together on top of a compiled
     * connection: a step is placed inside the container the compiler produces, so nothing can be
     * added until there is one. Anything that merely makes the automation not worth running yet
     * belongs in readinessErrors, or the wizard deadlocks - no calls without a mapping, and no
     * mapping without calls to hang it on.
     */
    public structuralErrors(
        definition: AutomationDefinition,
        context: AutomationCompileContext
    ): string[] {
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

        // Only asked for where they are what gets read. Writing DataGerry, the link step says as
        // much - "the mapping chooses the fields" - and never fills them in, so demanding them
        // here left an automation that could not be finished and no screen that would fix it.
        if (definition.direction === 'outgoing' && definition.fields.length === 0) {
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

        // Only an automation whose calls are still derived needs one to exist: a newer one names
        // its calls in the sequence, and an action it never chose must not hold it back.
        if (seedsItsOwnCalls(definition) && !sides.target) {
            errors.push(`The target system offers no operation for "${definition.target.operation}".`);
        }

        if (sides.source && !sides.source.responseArrayPath) {
            errors.push('The source operation does not return a list of objects, so there is nothing to iterate.');
        }

        return errors;
    }


    /**
     * What has to hold before the automation is worth running.
     *
     * Checked when it is saved, not while it is being built. A field reaches the target system by
     * a request value naming it, which is done on a call - so an automation that has no calls yet
     * has no mapping yet either, and saying so while the calls are still being added would be
     * telling the user off for not having finished.
     */
    private readinessErrors(definition: AutomationDefinition): string[] {
        const errors: string[] = [];

        if (definition.mapping.filter(entry => entry.target).length === 0) {
            errors.push('No field is sent anywhere yet. Give a request value a field reference on a call.');
        }

        // Without it the automation has no way of telling which object over there it means, so
        // updating and deleting would act on nothing and creating would duplicate on every run.
        if (seedsItsOwnCalls(definition) && requiresMatching(definition) && !definition.matching.identifyBy) {
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

        if (!sides.source || (seedsItsOwnCalls(definition) && !sides.target)) {
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
        this.applyListLimit(definition, sides, sourceMethod, warnings);

        const loop = this.buildLoopOperator(sides.source.responseArrayPath);
        const methods: OcMethod[] = [sourceMethod];
        const operators: OcOperator[] = [loop];
        const bindings: OcFieldBinding[] = [];
        const graph: GraphNode[] = [
            { id: AutomationCompilerService.START_NODE, kind: 'start', parent: '' },
            { id: sourceMethod.id, kind: 'method', parent: AutomationCompilerService.START_NODE, method: sourceMethod },
            {
                id: loop.id,
                kind: 'loop',
                parent: sourceMethod.id,
                operator: loop,
                tree: this.loopTree(loop.id, ocPresenceField(
                    AutomationCompilerService.SOURCE_COLOR,
                    sides.source.responseArrayPath
                ))
            }
        ];

        // A restriction on which objects take part is an `if` of its own inside the loop, not a
        // property of the loop: the loop's expression is the collection it walks, and the engine
        // reads nothing else. Everything the loop does then hangs off that gate instead.
        const container = this.buildConditionGate(definition, context, sides, loop, operators, graph, warnings);

        // What the target system is asked to do is the sequence's answer, not this compiler's.
        // Guessing it from an action the user picked meant guessing what that system calls the
        // action, which is exactly the guess that kept being wrong - see seedsItsOwnCalls().
        if (seedsItsOwnCalls(definition)) {
            this.seedCalls(definition, context, sides, container, {
                palette, methods, operators, bindings, graph, warnings
            });
        }

        const fromExtras = this.appendExtras(definition, context, {
            palette, methods, operators, bindings, graph, warnings
        });

        // An incoming automation exists to put objects into DataGerry, so the write is the
        // automation itself in the same way the read is on the way out - the sequence only
        // gathers what goes into it. It comes last inside the container, after everything the
        // user added, because it needs their answers.
        if (writesIntoDataGerry(definition)) {
            this.appendDataGerryWrite(definition, context, container, {
                palette, methods, operators, bindings, graph, warnings
            });
        }

        this.applyOverrides(
            { ...definition.overrides, ...fromExtras },
            definition.adjustments ?? {},
            methods,
            bindings,
            warnings
        );

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

    /**
     * Adds the calls the user put into the sequence, after the skeleton is complete.
     *
     * Each one hangs off the step it was placed after and inherits its position in the tree, so a
     * category written after the object write runs inside the same branch and only when that branch
     * is taken. The identifier of whatever the previous call touched is bound in where it is wanted,
     * which is the whole reason such a call exists: it belongs to an object that has just been
     * created or found, and until then that object has no id to name.
     */
    private appendExtras(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        out: {
            palette: ReadonlyArray<string>;
            methods: OcMethod[];
            operators: OcOperator[];
            bindings: OcFieldBinding[];
            graph: GraphNode[];
            warnings: string[];
        }
    ): Record<string, AutomationCallOverride> {
        const values: Record<string, AutomationCallOverride> = {};

        // What each added step became, so the next one can name it. An added step is named by its
        // own id rather than by the position it happened to land on, which moves as soon as
        // anything is inserted above it - and a step inside a condition would then be orphaned.
        const placed = new Map<string, Anchor>();

        for (const extra of definition.extras) {
            const anchor = placed.get(extra.after) ?? this.anchorOf(extra, out);

            if (!anchor) {
                out.warnings.push(
                    `The added step "${extra.operation || extra.kind}" follows a step that no longer `
                    + 'exists, so it was left out. Place it after another step or remove it.'
                );

                continue;
            }

            // Everything placed after a condition runs inside it - that is what putting it there
            // means - so it takes a position below rather than beside.
            const index = anchor.contains
                ? this.nextChildIndex(anchor.index, out)
                : this.nextSiblingIndex(anchor.index, out);
            const attachment = this.attachmentFor(anchor, index, out);

            if (extra.kind === 'if' || extra.kind === 'loop') {
                const container = extra.kind === 'if'
                    ? this.appendConditionStep(extra, attachment, index, out)
                    : this.appendLoopStep(extra, attachment, index, out);

                if (container) {
                    placed.set(extra.id, container);
                }

                continue;
            }

            // Named after the entry rather than after a position: an added call is found again by
            // the step it came from, and a position moves as soon as anything is inserted above it.
            const id = ocMethodNodeId(extra.id);
            const color = out.palette[out.methods.length % out.palette.length];
            let method: OcMethod;

            if (extra.kind === 'http') {
                method = this.buildFreeRequest(extra, ocSystemNodeId(extra.id), index, color);
            } else {
                // The system the user chose, not the side that happens to be written: an added call
                // through an invoker always goes to the foreign system, whichever way it runs.
                const operation = this.operationByName(context.targetConnector?.invoker, extra.operation);

                if (!operation) {
                    out.warnings.push(
                        `The target system offers no operation "${extra.operation}", so that added `
                        + 'call was left out.'
                    );

                    continue;
                }

                method = this.buildMethod(operation, context.targetConnector, id, index, color, null);
            }

            out.methods.push(method);
            out.graph.push({
                id: method.id,
                kind: 'method',
                parent: attachment.parent,
                method,
                below: attachment.below,
                branch: attachment.branch
            });

            placed.set(extra.id, { id: method.id, index: method.index, method });

            // Values the user typed reach it the same way a correction does - handed back rather
            // than written into the definition, which the compiler must not touch.
            values[method.index] = {
                endpoint: extra.endpoint,
                headers: extra.headers,
                body: extra.body
            };
        }

        return values;
    }


    /**
     * A request written out in full, with no invoker and no connector behind it.
     *
     * For an endpoint no invoker describes. The trade is spelled out where it is offered: an invoker
     * is reusable, documents itself and knows its own response shape, and none of that comes with a
     * request typed in by hand - including the response schema, which is why nothing downstream can
     * read a value back out of one.
     */
    private buildFreeRequest(
        extra: AutomationExtraCall,
        id: string,
        index: string,
        color: string
    ): OcMethod {
        const envelope = () => ({ type: 'object', format: 'json', data: 'raw', fields: {} });
        const verb = extra.verb || 'POST';

        return {
            id,
            // Named after the verb, as the capture shows - the address is already in the request.
            name: verb,
            index,
            methodType: OC_FREE_REQUEST,
            dataAggregator: null,
            color,
            // Explicitly null rather than absent: the capture carries the key.
            connector: null as any,
            request: {
                endpoint: extra.endpoint ?? '',
                method: verb,
                header: { ...(extra.headers ?? {}) },
                body: envelope()
            },
            response: {
                name: 'response',
                success: { status: '200', header: {}, body: envelope() },
                fail: { status: '500', header: {}, body: envelope() }
            }
        };
    }


    /**
     * The step an added one hangs off.
     *
     * A condition counts as much as a call does: putting something after a condition is the only
     * way to say "do this when it holds", so an added step may name one - and then it is drawn and
     * indexed inside it rather than beside it, which is what `branch` carries.
     */
    private anchorOf(
        extra: AutomationExtraCall,
        out: { methods: OcMethod[]; operators: OcOperator[] }
    ): Anchor | null {
        const method = out.methods.find(candidate => candidate.index === extra.after);

        if (method) {
            return { id: method.id, index: method.index, method };
        }

        const operator = out.operators.find(candidate => candidate.index === extra.after);

        return operator
            ? { id: operator.id, index: operator.index, contains: operator.type }
            : null;
    }


    /**
     * Where an added step is drawn from - which is not always the step it was placed after.
     *
     * Placed inside a condition or a loop, it drops a row below its anchor and enters from the top,
     * down the exit that was taken. Placed beside it, it lands behind whatever already follows that
     * anchor, so the step it is drawn from is the one occupying the position before its own: a
     * second condition after the same call is reached from the first condition's `false` exit, the
     * way OpenCelium's own captures wire "otherwise". Drawing it from the call instead forks the
     * sequence, and the editor then shows the two conditions side by side rather than one after the
     * other - while the execution indices say they run in turn.
     */
    private attachmentFor(
        anchor: Anchor,
        index: string,
        out: { methods: OcMethod[]; operators: OcOperator[] }
    ): Attachment {
        if (anchor.contains) {
            return {
                parent: anchor.id,
                below: true,
                branch: anchor.contains === 'if' ? 'true' : undefined
            };
        }

        const previous = this.entryBefore(index, out);

        if (!previous) {
            return { parent: anchor.id, below: false };
        }

        return {
            parent: previous.id,
            below: false,
            // A condition passes on what it did not catch, and only through its `false` exit.
            branch: previous.kind === 'if' ? 'false' : undefined
        };
    }


    /** The step occupying the position right before this one, on the same level of the tree. */
    private entryBefore(
        index: string,
        out: { methods: OcMethod[]; operators: OcOperator[] }
    ): { id: string; kind: 'method' | 'if' | 'loop' } | null {
        const parts = index.split('_');
        const position = Number(parts[parts.length - 1]);

        if (!(position > 0)) {
            return null;
        }

        const before = [...parts.slice(0, -1), position - 1].join('_');
        const operator = out.operators.find(candidate => candidate.index === before);

        if (operator) {
            return { id: operator.id, kind: operator.type };
        }

        const method = out.methods.find(candidate => candidate.index === before);

        return method ? { id: method.id, kind: 'method' } : null;
    }


    /**
     * The condition itself: an operator in the tree, and the node the editor draws for it.
     *
     * No method and no colour - a condition sends nothing. What follows it in the sequence finds it
     * as its anchor and lands one level further in, which is how a branch comes to hold anything.
     */
    private appendConditionStep(
        extra: AutomationExtraCall,
        attachment: Attachment,
        index: string,
        out: { operators: OcOperator[]; graph: GraphNode[]; warnings: string[] }
    ): Anchor | null {
        const id = ocIfNodeId(extra.id);
        const rendered = this.renderCallCondition(extra.condition, id);

        if (!rendered) {
            out.warnings.push(
                'A condition in the sequence has nothing to test, so it and everything placed after '
                + 'it were left out. Give it a value to compare, or remove it.'
            );

            return null;
        }

        const operator: OcOperator = {
            id,
            index,
            type: 'if',
            dataAggregator: null,
            expression: rendered.expression,
            iterator: null
        };

        out.operators.push(operator);
        out.graph.push({
            id: operator.id,
            kind: 'if',
            parent: attachment.parent,
            below: attachment.below,
            branch: attachment.branch,
            operator,
            tree: rendered.tree
        });

        // Everything placed after a condition runs inside it, down its `true` exit.
        return { id: operator.id, index: operator.index, contains: 'if' };
    }


    /**
     * A loop of the user's own: something in an answer holds a list, and each entry gets the same
     * treatment.
     *
     * The list is picked; the iterator is not. Every reference into a list carries the name of the
     * loop that walks it, so two loops sharing one would read each other's entry - the wizard hands
     * the name out for that reason, and the sequence is where it comes from.
     */
    private appendLoopStep(
        extra: AutomationExtraCall,
        attachment: Attachment,
        index: string,
        out: { operators: OcOperator[]; graph: GraphNode[]; warnings: string[] }
    ): Anchor | null {
        const list = extra.loop?.list?.trim();

        if (!list) {
            out.warnings.push(
                'A loop in the sequence names no list, so it and everything placed after it were '
                + 'left out. Pick the list it should walk, or remove it.'
            );

            return null;
        }

        const id = ocLoopNodeId(extra.id);
        const operator: OcOperator = {
            id,
            index,
            type: 'loop',
            dataAggregator: null,
            expression: `for {%${list}%}`,
            iterator: extra.loop!.iterator || OC_LOOP_ITERATOR
        };

        out.operators.push(operator);
        out.graph.push({
            id,
            kind: 'loop',
            parent: attachment.parent,
            below: attachment.below,
            branch: attachment.branch,
            operator,
            tree: this.loopTree(id, list)
        });

        // Everything placed after a loop runs inside it, once per entry.
        return { id, index, contains: 'loop' };
    }


    /**
     * The rule-builder form of a loop: one rule, `for` over the list it walks.
     *
     * The editor rebuilds the expression out of this tree, so a loop saved with an empty one comes
     * back walking nothing - which is what the captured loops show it should hold instead.
     */
    private loopTree(uiId: string, list: string): OcUiGroup {
        return {
            id: `${uiId}-group`,
            type: 'group',
            properties: { not: false },
            items: [{
                id: `${uiId}-rule`,
                type: 'rule',
                properties: { operator: 'for', leftField: list }
            }]
        };
    }


    /**
     * A condition the user built, in both the forms it is stored in.
     *
     * Which side is a reference and which a literal is decided by the '#' that starts every
     * reference: one goes into the expression in braces, the other in quotes, exactly as the
     * captured conditions carry them.
     */
    private renderCallCondition(
        condition: AutomationCallCondition | undefined,
        uiId: string
    ): { expression: string; tree: OcUiGroup } | null {
        const left = condition?.left?.trim();

        if (!left || !condition?.operator) {
            return null;
        }

        const right = (condition.right ?? '').trim();
        const rightSide = right.startsWith('#') ? `{%${right}%}` : quoteLiteral(right);

        if (right && rightSide === null) {
            return null;
        }

        return {
            expression: right
                ? `({%${left}%} ${condition.operator} ${rightSide})`
                : `({%${left}%} ${condition.operator})`,
            tree: {
                id: `${uiId}-group`,
                type: 'group',
                properties: { not: false },
                items: [{
                    id: `${uiId}-rule`,
                    type: 'rule',
                    properties: right
                        ? { leftField: left, operator: condition.operator, rightField: right }
                        : { leftField: left, operator: condition.operator }
                }]
            }
        };
    }


    /** The operation of that name, for a call the user chose rather than the wizard resolved. */
    private operationByName(invoker: any, name: string): ResolvedOperation | null {
        const match = (invoker?.operations ?? []).find((operation: any) => operation?.name === name);

        return match ? { name: match.name, definition: match, responseArrayPath: '', verified: true } : null;
    }


    /** The next free position beside a step, so an added call runs after it rather than inside it. */
    private nextSiblingIndex(anchor: string, out: { methods: OcMethod[]; operators: OcOperator[] }): string {
        const parts = anchor.split('_');
        const parent = parts.slice(0, -1).join('_');

        return this.nextFreePosition(parent, parts.length, out);
    }


    /** The next free position inside a step, which is where everything after a condition goes. */
    private nextChildIndex(anchor: string, out: { methods: OcMethod[]; operators: OcOperator[] }): string {
        return this.nextFreePosition(anchor, anchor.split('_').length + 1, out);
    }


    /**
     * The first position under a parent nothing occupies yet.
     *
     * Operators count as much as methods do: an execution index addresses one tree, and a condition
     * sitting at '1_1' means the next call beside it is '1_2' - numbering the two separately would
     * put a call on top of a branch.
     */
    private nextFreePosition(
        parent: string,
        depth: number,
        out: { methods: OcMethod[]; operators: OcOperator[] }
    ): string {
        const taken = [...out.methods, ...out.operators]
            .map(entry => entry.index)
            .filter(index => index.startsWith(parent ? `${parent}_` : '') && index.split('_').length === depth)
            .map(index => Number(index.split('_').pop()));

        const next = Math.max(...taken, -1) + 1;

        return parent ? `${parent}_${next}` : String(next);
    }






    /**
     * Wires a value somebody put a reference into.
     *
     * A request value carrying a reference is only half of it: every capture pairs one with a
     * binding, and without it the reference sits in the body as text. The value is written either
     * way, so this adds what was missing rather than replacing anything.
     *
     * A value that is part text and part reference - `Bearer` and then a token - keeps the whole
     * value in the body and names every reference in it as an origin.
     */
    private bindWrittenReferences(
        method: OcMethod,
        path: string,
        value: string,
        bindings: OcFieldBinding[],
        adjustments: Record<string, AutomationValueTransform>
    ): void {
        const references = (value.match(/#[0-9A-Fa-f]{6}\.\([a-z]+\)[^\s,;)"']*/g) ?? [])
            .map(reference => ocParseReference(reference))
            .filter((parsed): parsed is { color: string; section: 'request' | 'response'; field: string } => !!parsed);

        if (references.length === 0) {
            return;
        }

        const targetPath = `body.$.${path}`;
        // Keyed by the call as well as the path: two calls can write the same one, and an
        // adjustment belongs to exactly one of them.
        const adjustment = adjustments[`${method.index}:${path}`];
        const script = adjustment?.enabled ? adjustment.script.trim() : '';

        bindings.push({
            from: references.map(reference => ({
                color: reference.color,
                field: reference.field,
                type: 'response' as const
            })),
            to: [{ color: method.color, field: targetPath, type: 'request' as const }],
            enhancement: this.buildEnhancement(
                references[0].field,
                targetPath,
                method.color,
                references.map(reference => ({ kind: 'path' as const, path: reference.field })),
                script
            )
        });
    }


    /**
     * Applies the corrections the user made to the calls, last of everything.
     *
     * Last on purpose: whatever the assistant worked out, a person who went and changed a header
     * meant it. The one exception is a field the mapping writes - OpenCelium replaces a bound field
     * with its own reference when the connection is saved, so an override there would be dropped on
     * the way in and look like the wizard lost it. Those are reported instead of applied.
     */
    private applyOverrides(
        overrides: Record<string, AutomationCallOverride>,
        adjustments: Record<string, AutomationValueTransform>,
        methods: OcMethod[],
        bindings: OcFieldBinding[],
        warnings: string[]
    ): void {
        // Per method: the same path can be bound on the call that writes the object and free on a
        // call added after it, and blocking both would make the added one impossible to fill in.
        const boundOn = (color: string) => new Set(
            bindings
                .filter(binding => binding.to[0].color === color)
                .map(binding => binding.to[0].field.replace('body.$.', ''))
        );

        for (const method of methods) {
            const override = overrides[method.index];

            if (!override) {
                continue;
            }

            if (override.endpoint) {
                method.request.endpoint = override.endpoint;
            }

            for (const [name, value] of Object.entries(override.headers ?? {})) {
                const headers = { ...(method.request.header ?? {}) };

                if (value === null) {
                    delete headers[name];
                } else {
                    headers[name] = value;
                }

                method.request.header = headers;
            }

            const bound = boundOn(method.color);

            for (const [path, value] of Object.entries(override.body ?? {})) {
                if (value === null) {
                    this.removeBodyField(method.request, path);

                    continue;
                }

                if (bound.has(path)) {
                    warnings.push(
                        `"${path}" on ${method.name} is written by the field assignment, so the value `
                        + 'entered by hand is not sent. Remove the assignment for it, or the change.'
                    );

                    continue;
                }

                this.setBodyField(method.request, path, value);
                this.bindWrittenReferences(method, path, value, bindings, adjustments);
            }
        }
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
        const { expression, tree } = this.buildCondition(
            definition,
            context,
            sides.source!.responseArrayPath,
            ocIfNodeId('gate'),
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
            tree
        });

        return { id: gate.id, index: gate.index };
    }


    /**
     * The call that puts what the sequence collected into DataGerry.
     *
     * Its body is the mapping: one entry per field of the object type the user filled in, each
     * either a value read from an earlier answer or one typed in. The object type itself is the
     * automation's own choice and goes in as a literal.
     */
    private appendDataGerryWrite(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        container: { id: string; index: string },
        out: Omit<BranchBuildContext, 'container'>
    ): void {
        const { palette, methods, bindings, graph, warnings } = out;
        const operation = this.catalog.resolveOperation(context.internalConnector?.invoker, 'create');

        if (!operation) {
            warnings.push(
                'DataGerry offers no operation for creating an object, so the collected data is not '
                + 'written anywhere.'
            );

            return;
        }

        const written = definition.mapping.filter(entry => entry.target && entry.sources.length > 0);

        if (written.length === 0) {
            return;
        }

        const method = this.buildMethod(
            operation,
            context.internalConnector,
            ocMethodNodeId(methods.length),
            this.nextFreePosition(container.index, container.index.split('_').length + 1, out),
            palette[methods.length % palette.length],
            null
        );

        this.setBodyField(method.request, 'type_id', String(definition.objectType.typeId ?? ''));

        // DataGerry takes an object's fields as an array of name/value pairs, which setBodyField
        // cannot address - it walks dotted keys and would turn the array into an object.
        method.request.body.fields.fields = written.map(entry => ({
            name: entry.target,
            value: sourceValueOf(entry.sources[0])
        }));

        methods.push(method);
        graph.push({ id: method.id, kind: 'method', parent: container.id, method, below: true });

        written.forEach((entry, position) => {
            const binding = this.bindDataGerryField(entry, position, method, warnings);

            if (binding) {
                bindings.push(binding);
            }
        });
    }


    /**
     * Wires one field of the written object to the answer it comes from.
     *
     * A value that was typed in needs no binding - it already stands in the body. One that came
     * from an earlier call does, and unlike everywhere else the reference is stored whole, so it
     * is taken apart again into the colour and the path a binding names separately.
     */
    private bindDataGerryField(
        entry: AutomationMappingEntry,
        position: number,
        method: OcMethod,
        warnings: string[]
    ): OcFieldBinding | null {
        const references = entry.sources
            .map(source => ocParseReference(source.reference ?? ''))
            .filter((parsed): parsed is { color: string; section: 'request' | 'response'; field: string } => !!parsed);
        const script = entry.transform?.enabled ? entry.transform.script.trim() : '';

        if (entry.transform?.enabled && !script) {
            warnings.push(
                `The value adjustment for "${entry.target}" has no content, so the value is `
                + 'transferred unchanged.'
            );
        }

        if (references.length === 0) {
            return null;
        }

        const targetPath = `body.$.fields[${position}].value`;
        const sources: SourceValue[] = references.map(reference => ({ kind: 'path', path: reference.field }));

        return {
            from: references.map(reference => ({
                color: reference.color,
                field: reference.field,
                type: 'response' as const
            })),
            to: [{ color: method.color, field: targetPath, type: 'request' as const }],
            enhancement: this.buildEnhancement(
                references[0].field,
                targetPath,
                method.color,
                sources,
                script
            )
        };
    }


    /**
     * The calls an automation from before the sequence step carried implicitly.
     *
     * Such a definition names an action and how to match, and nothing in it lists the calls - so
     * they are still derived, or reopening one would show an automation that writes nothing. A
     * definition written since then lists its calls and comes through here untouched.
     */
    private seedCalls(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        sides: ResolvedSides,
        container: { id: string; index: string },
        out: Omit<BranchBuildContext, 'container'>
    ): void {
        const { palette, methods, bindings, graph, warnings } = out;
        const plan = this.planBranches(definition);

        if (plan.length > 0) {
            this.buildMatchedBranches(definition, context, sides, plan, { ...out, container });

            return;
        }

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
        const entry = definition.mapping.find(
            pair => pair.sources.some(source => source.field === definition.matching.identifyBy)
        );
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
                [{ kind: 'path', path: elementId }],
                ''
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
            if (!entry.target || entry.sources.length === 0) {
                continue;
            }

            const resolved = entry.sources
                .map(source => this.resolveSourceValue(definition, context, source.field, warnings))
                .filter((value): value is SourceValue => !!value);

            if (resolved.length === 0) {
                continue;
            }

            const binding = this.bindTarget(entry, resolved, arrayPath, sides, targetMethod, warnings);

            if (binding) {
                bindings.push(binding);
            }
        }

        return bindings;
    }


    /**
     * Wires everything that feeds one field of the target system.
     *
     * A field binding names one target and carries a list of sources, which the script sees as
     * VAR_0, VAR_1 and so on - so several fields combining into one is the shape the transport
     * already has rather than something layered on top.
     *
     * Three cases produce different payloads. A single source read from the response with no script
     * is the plain copy the reference payloads carry, and is emitted exactly as they do. Sources
     * that are all fixed values with no script need no binding at all: the literal goes into the
     * body. Everything else becomes a script that assembles the value from its parts.
     */
    private bindTarget(
        entry: AutomationMappingEntry,
        sources: SourceValue[],
        arrayPath: string,
        sides: ResolvedSides,
        targetMethod: OcMethod,
        warnings: string[]
    ): OcFieldBinding | null {
        const script = entry.transform?.enabled ? entry.transform.script.trim() : '';
        const paths = sources.filter(source => source.kind === 'path');
        const targetPath = `body.$.${entry.target}`;

        if (entry.transform?.enabled && !script) {
            warnings.push(
                `The value adjustment for "${entry.target}" has no content, so the value is `
                + 'transferred unchanged.'
            );
        }

        if (paths.length === 0 && !script) {
            // Nothing to read and nothing to compute: the literal is the value.
            this.setBodyField(targetMethod.request, entry.target, sources[0].kind === 'constant' ? sources[0].value : '');

            return null;
        }

        // A script with no source to read still needs a binding, and a binding needs an origin.
        // Any field the read operation returns will do; the script never looks at it.
        const readable = paths.length > 0
            ? paths.map(source => (source as { path: string }).path)
            : [this.borrowedSourcePath(sides)].filter(Boolean);

        if (readable.length === 0) {
            warnings.push(
                `The value adjustment for "${entry.target}" needs a field the read operation returns, `
                + 'and this operation describes none, so the value is sent unchanged.'
            );
            this.setBodyField(targetMethod.request, entry.target, sources[0].kind === 'constant' ? sources[0].value : '');

            return null;
        }

        const elementPaths = readable.map(path => ocCollectionElementPath(arrayPath, path));

        // The body holds the reference of the first source; the script's result replaces it.
        this.setBodyField(
            targetMethod.request,
            entry.target,
            ocFieldReference(AutomationCompilerService.SOURCE_COLOR, 'response', elementPaths[0])
        );

        return {
            from: elementPaths.map(path => ({
                color: AutomationCompilerService.SOURCE_COLOR,
                field: `body.$.${path}`,
                type: 'response' as const
            })),
            to: [{ color: targetMethod.color, field: targetPath, type: 'request' as const }],
            enhancement: this.buildEnhancement(
                `body.$.${elementPaths[0]}`,
                targetPath,
                targetMethod.color,
                sources,
                script
            )
        };
    }


    /**
     * A response field of the read operation, used as the formal origin of a binding that reads
     * nothing. See bindTarget.
     */
    private borrowedSourcePath(sides: ResolvedSides): string {
        return this.catalog.sourceItemFields(sides.source)[0]?.path ?? '';
    }


    /**
     * The script OpenCelium runs for one field.
     *
     * The plain copy is emitted verbatim as the reference payloads carry it. Anything else is
     * wrapped so the user's statements work on names rather than on VAR_0: a single source is
     * `value`, several are `value1`, `value2` in the order they were added, and `value` is what
     * gets written. A fixed value among them is seeded as a literal, because it has no VAR to read.
     */
    private buildEnhancement(
        sourcePath: string,
        targetPath: string,
        targetColor: string,
        sources: SourceValue[],
        script: string
    ): OcEnhancement {
        const single = sources.length === 1;
        let readIndex = 0;

        const seeds = sources.map(source => source.kind === 'constant'
            ? JSON.stringify(source.value)
            : `VAR_${readIndex++}`);

        const plainCopy = !script && single && sources[0].kind === 'path';
        const names = single ? ['value'] : sources.map((_source, index) => `value${index + 1}`);

        const body = plainCopy
            ? 'RESULT_VAR = VAR_0;'
            : [
                ...names.map((name, index) => `var ${name} = ${seeds[index]};`),
                ...(single ? [] : ['var value = value1;']),
                ...(script ? [script] : []),
                'RESULT_VAR = value;'
            ].join('\n');

        return {
            name: '',
            description: '',
            language: 'js',
            simpleCode: null,
            expertVar: `//var RESULT_VAR = ${targetColor}.(request).${targetPath};\n`
                + `//var VAR_0 = ${AutomationCompilerService.SOURCE_COLOR}.(response).${sourcePath};`,
            expertCode: body
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
        sourceMethod: OcMethod,
        warnings: string[]
    ): void {
        const placement = findAdapter(sides.sourceConnector?.invoker?.name)?.listLimit;
        const batchSize = definition.advanced.batchSize;

        if (!placement || !batchSize || batchSize <= 0) {
            return;
        }

        // An operation that pages sets its own page size, and writing ours over it would either
        // fight the engine for the same parameter or cut the run short at one page. Where paging is
        // declared the ceiling is not needed, so the setting is ignored and said to be ignored.
        //
        // Read from the operation's type rather than from its pagination block: the block lives in
        // the invoker file and no endpoint exposes it - FunctionDTO carries name, type, request and
        // response and nothing else - so a check on the block itself would never fire. The type is
        // also what the engine keys off, so the two agree by construction.
        if (this.pagesByItself(sides.source)) {
            warnings.push(
                `The read operation "${sides.source.name}" fetches every page by itself, so the limit `
                + 'on objects per run does not apply and the whole object type is processed.'
            );

            return;
        }

        if (placement.endpointQuery) {
            this.appendEndpointQuery(sourceMethod.request, placement.endpointQuery, String(batchSize));

            return;
        }

        this.setBodyField(sourceMethod.request, placement.bodyPath!, String(batchSize));
    }


    /** Whether the read operation fetches every page by itself. See applyListLimit. */
    private pagesByItself(operation: ResolvedOperation | null): boolean {
        return operation?.definition?.type === OC_PAGING_OPERATION;
    }


    /** Appends a query parameter to an operation endpoint, preserving any it already has. */
    private appendEndpointQuery(request: any, key: string, value: string): void {
        const endpoint: string = request.endpoint ?? '';
        const separator = endpoint.includes('?') ? '&' : '?';

        request.endpoint = `${endpoint}${separator}${key}=${encodeURIComponent(value)}`;
    }


    /** Writes a value into the request body's field tree, creating intermediate objects as needed. */
    /**
     * One segment of a body path: a key, and the array position when the key names an array.
     *
     * `fields[0].value` is three segments to a reader and two to a walker, and the difference is
     * where an object stops and a list begins - which is exactly what DataGerry's own object body
     * is made of, so it cannot be left out.
     */
    private pathSegments(dottedPath: string): Array<{ key: string; at: number | null }> {
        return dottedPath.split('.').map(segment => {
            const match = /^(.*?)\[(\d+)\]$/.exec(segment);

            return match ? { key: match[1], at: Number(match[2]) } : { key: segment, at: null };
        });
    }


    /**
     * Walks to the container a path's last segment lives in, making what is missing on the way.
     *
     * Returns null when the walk cannot be made without destroying something - which only happens
     * while reading, where inventing a node would report a value that is not there.
     */
    private containerFor(
        fields: any,
        segments: Array<{ key: string; at: number | null }>,
        create: boolean
    ): any {
        let node = fields;

        for (const segment of segments.slice(0, -1)) {
            let next = node?.[segment.key];

            if (segment.at === null) {
                if (typeof next !== 'object' || next === null || Array.isArray(next)) {
                    if (!create) {
                        return null;
                    }

                    next = {};
                    node[segment.key] = next;
                }

                node = next;
                continue;
            }

            if (!Array.isArray(next)) {
                if (!create) {
                    return null;
                }

                next = [];
                node[segment.key] = next;
            }

            if (typeof next[segment.at] !== 'object' || next[segment.at] === null) {
                if (!create) {
                    return null;
                }

                next[segment.at] = {};
            }

            node = next[segment.at];
        }

        return node;
    }


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

        const segments = this.pathSegments(dottedPath);
        const node = this.containerFor(request.body.fields, segments, true);
        const leaf = segments[segments.length - 1];

        if (pruneSiblings) {
            // The invoker template carries every filter key it supports; the reference keeps only
            // the one actually used, so unused keys are dropped rather than sent empty.
            Object.keys(node).forEach(key => {
                if (key !== leaf.key) {
                    delete node[key];
                }
            });
        }

        if (leaf.at === null) {
            node[leaf.key] = value;

            return;
        }

        if (!Array.isArray(node[leaf.key])) {
            node[leaf.key] = [];
        }

        node[leaf.key][leaf.at] = value;
    }


    /**
     * Takes a value the operation offers back out of the request.
     *
     * An invoker describes everything its operation accepts, and an automation rarely wants to send
     * all of it - an empty key is not the same as an absent one to every API. Removing leaves no
     * trace beyond its absence; the field is put back by adding it again under its own name.
     */
    private removeBodyField(request: any, dottedPath: string): void {
        const fields = request?.body?.fields;

        if (!fields) {
            return;
        }

        const segments = this.pathSegments(dottedPath);
        const node = this.containerFor(fields, segments, false);
        const leaf = segments[segments.length - 1];

        if (!node) {
            return;
        }

        if (leaf.at === null) {
            delete node[leaf.key];

            return;
        }

        if (Array.isArray(node[leaf.key])) {
            node[leaf.key].splice(leaf.at, 1);
        }
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
    private buildCondition(
        definition: AutomationDefinition,
        context: AutomationCompileContext,
        arrayPath: string,
        uiId: string,
        warnings: string[]
    ): { expression: string; tree: OcUiGroup } {
        const group = definition.conditions;
        const conjunction = group.combinator === 'and' ? '&&' : '||';
        const rendered: RenderedRule[] = [];

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

            const reference = ocFieldReference(
                AutomationCompilerService.SOURCE_COLOR,
                'response',
                ocCollectionElementPath(arrayPath, value.path)
            );
            const term = this.renderRule(reference, rule.operator, rule.value);

            if (!term) {
                warnings.push(
                    `The condition on "${rule.field}" compares against a value holding both kinds of `
                    + 'quote, which the expression language cannot write, so it was left out.'
                );

                continue;
            }

            rendered.push(term);
        }

        if (rendered.length === 0) {
            return { expression: '', tree: this.emptyConditionTree() };
        }

        const body = rendered.map(entry => entry.term).join(` ${conjunction} `);

        return {
            expression: group.negate ? `!(${body})` : `(${body})`,
            tree: {
                id: `${uiId}-group`,
                type: 'group',
                properties: rendered.length > 1
                    ? { not: group.negate, conjunction }
                    : { not: group.negate },
                items: rendered.map((entry, position) => ({
                    id: `${uiId}-rule-${position}`,
                    type: 'rule' as const,
                    properties: entry.rule
                }))
            }
        };
    }


    /**
     * One rule, in both the forms a condition is stored in.
     *
     * The expression is what the engine evaluates; the rule tree beside it is what the editor draws
     * and what it regenerates the expression from if someone opens the connection there. They have
     * to say the same thing, which is why one method produces both - and why the tree carries the
     * resolved reference rather than the field name the user picked, as the capture does.
     *
     * Two of the mappings are worth knowing about. A "contains" on text becomes `Like %v%` rather
     * than `Contains`, because the engine's Contains works on a list and would throw on a string.
     * And "is empty" becomes two terms, because a field can be empty by being absent or by holding
     * an empty string, and the engine treats those as different things - the tree keeps the null
     * half of that, which is as much as a single rule can say.
     *
     * Null when the value cannot be written down at all; the caller reports it.
     */
    private renderRule(
        reference: string,
        operator: AutomationRuleOperator,
        value: string
    ): RenderedRule | null {
        const left = `{%${reference}%}`;
        const number = Number(value);
        const numeric = Number.isFinite(number) ? String(number) : '0';
        const rule = (name: string, right?: string) => right === undefined
            ? { leftField: reference, operator: name }
            : { leftField: reference, operator: name, rightField: right };

        const compare = (name: string, right: string): RenderedRule | null => {
            const literal = quoteLiteral(right);

            return literal === null ? null : { term: `${left} ${name} ${literal}`, rule: rule(name, right) };
        };

        switch (operator) {
            case 'equals':
                return compare('=', value);
            case 'not_equals':
                return compare('!=', value);
            case 'contains':
                return compare('Like', `%${value}%`);
            case 'not_contains':
                return compare('NotLike', `%${value}%`);
            case 'starts_with':
                return compare('Like', `${value}%`);
            case 'ends_with':
                return compare('Like', `%${value}`);
            case 'is_empty':
                return { term: `(${left} IsNull || ${left} = '')`, rule: rule('IsNull') };
            case 'is_not_empty':
                return { term: `(${left} NotNull && ${left} != '')`, rule: rule('NotNull') };
            case 'greater_than':
                return { term: `${left} > ${numeric}`, rule: rule('>', numeric) };
            case 'less_than':
                return { term: `${left} < ${numeric}`, rule: rule('<', numeric) };
            default:
                return compare('=', value);
        }
    }


    /** An untouched condition tree - what the loop node carries when nothing restricts it. */
    private emptyConditionTree(): OcUiGroup {
        return { id: '0-group', type: 'group', properties: { not: false }, items: [] };
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
            return this.connectorNode(node.method!, position);
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
                // No right-hand side: a presence check compares against nothing, and the capture
                // leaves the key off such a rule rather than carrying it empty.
                properties: { leftField: reference, operator: presence }
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


    /**
     * The node the editor draws for a call.
     *
     * A request with no connector behind it is a different kind of node, not a connector node with
     * the connector left out: the editor types it 'system', titles it after the request rather than
     * after a system that does not exist, and carries no connector on it at all.
     */
    private connectorNode(method: OcMethod, position: { x: number; y: number }): OcWorkflowNode {
        const free = method.methodType === OC_FREE_REQUEST;

        return {
            id: method.id,
            type: free ? 'system' : 'connector',
            position,
            index: method.index,
            data: free
                ? {
                    title: OC_FREE_REQUEST_TITLE,
                    subtitle: method.name,
                    kind: 'system',
                    methodConfig: this.methodConfig(method)
                }
                : {
                    title: method.connector!.title,
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

        // Recognising an object is a lookup in the sequence now, not a marker on a step, so this
        // is only worth saying where the compiler still derives the calls - anywhere else it would
        // name a control that is not on any screen.
        if (seedsItsOwnCalls(definition) && !definition.matching.identifyBy) {
            warnings.push(
                'Nothing identifies the object in the target system, so this automation cannot tell '
                + 'a new object from one it already wrote and creates again on every run.'
            );
        }

        // The foreign system numbers its types itself, so DataGerry's id in its type field is a
        // number from the wrong side - it looks right and points at some other type.
        const remoteTypeTarget = definition.mapping.find(
            entry => entry.target.endsWith('type') || entry.target.endsWith('type_id')
        );

        if (definition.direction === 'outgoing'
            && remoteTypeTarget?.sources.some(source => source.field === '$type_id')) {
            warnings.push(
                `"${remoteTypeTarget.target}" is fed from DataGerry's own object type id. The target `
                + 'system numbers its types itself - use "Target system object type" instead, which '
                + 'sends the identifier given on the connection step.'
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


/** How a node hangs into the drawn graph: what it is drawn from, and through which exit. */
interface Attachment {
    /** Ui id of the node the edge leaves. */
    parent: string;

    /** True when the node runs inside that one and is drawn a row below it. */
    below: boolean;

    /** Which exit of an `if` leads here. */
    branch?: 'true' | 'false';
}


/**
 * A step an added one hangs off, and how it hangs off it.
 *
 * `contains` is set when the anchor is a condition or a loop: what follows one of those runs
 * inside it, one level further into the execution tree - and out of a condition down the exit that
 * was taken, out of a loop along its body.
 */
interface Anchor {
    id: string;
    index: string;
    method?: OcMethod;

    /** Set when the anchor is a container: what follows it runs inside it rather than beside it. */
    contains?: 'if' | 'loop';
}


/** One condition rule, said twice: once for the engine, once for the editor's rule builder. */
interface RenderedRule {
    term: string;
    rule: OcUiRule['properties'];
}


/**
 * A value as the expression language writes it.
 *
 * The engine's tokenizer takes either quote and knows no escape character, so the quote the value
 * does not itself contain is the one that works. A value holding both cannot be written at all -
 * null then, rather than a string that would tokenize into something else entirely.
 */
function quoteLiteral(value: string): string | null {
    const text = value ?? '';

    if (!text.includes('\'')) {
        return `'${text}'`;
    }

    return text.includes('"') ? null : `"${text}"`;
}


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
