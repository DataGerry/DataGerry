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
 * The technical OpenCelium connection payload.
 *
 * Every shape and constant in this file is taken from the two reference payloads captured from a
 * running installation (OpenCelium_Connection_Create_Request.json and
 * OpenCelium_Connection_Update_Request.json). This is the only place in the wizard that knows about
 * OpenCelium's data model - the compiler produces it, the JSON preview renders it, nothing else
 * touches it.
 *
 * Both endpoints send the same connection; only the wrapping differs:
 *   POST /rest/open_celium/schedulers      -> { connection, scheduler }
 *   PUT  /rest/open_celium/connections/:id -> the flat connection, plus `connectionId`
 *
 * The connection itself no longer carries the connectors' invoker definitions. Methods name their
 * connector, OpenCelium resolves the rest, and both systems' methods live in one list under
 * `fromConnector` while `toConnector` stays null. That is why a payload that used to weigh 300 KB
 * now weighs 20 KB.
 */

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     CONSTANTS                                                      */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Colours OpenCelium assigns to methods. A colour is the handle by which one method references
 * another method's data, so the order must stay stable: the reference payloads use #FFCFB5 for the
 * source method and #C77E7E for the target method.
 */
export const OC_METHOD_COLORS: ReadonlyArray<string> = [
    '#FFCFB5',
    '#C77E7E',
    '#B5D8FF',
    '#A5E1AD',
    '#F6C6EA',
    '#FFE7A0',
    '#C3B1E1',
    '#9AD0C2'
];

/**
 * Geometry of the workflow graph, mirroring the reference payloads exactly.
 *
 * The nodes sit on one row a fixed step apart; a method that runs inside a loop drops below the
 * loop rather than continuing the row. OpenCelium lets the user rearrange this afterwards, so the
 * numbers only have to produce a readable starting point.
 */
export const OC_UI_LAYOUT = {
    viewport: { x: 80, y: -80, zoom: 1 },
    startX: 120,
    stepX: 165,
    rowY: 220,
    branchDy: 128
} as const;

/**
 * The single connector slot that now carries every method.
 *
 * OpenCelium stopped splitting a connection into a reading and a writing connector; the methods
 * name their own connector instead, and this placeholder holds them all.
 */
export const OC_DEFAULT_CONNECTOR_ID = -1;
export const OC_DEFAULT_CONNECTOR_TITLE = 'DEFAULT';

/** Execution-tree positions: the source runs first, the loop wraps the target method. */
export const OC_SOURCE_INDEX = '0';
export const OC_LOOP_INDEX = '1';
export const OC_TARGET_INDEX = '1_0';

/** Name the loop operator gives the element it is currently on. */
export const OC_LOOP_ITERATOR = 'i';

/** Scheduler status values OpenCelium expects (1 = active). */
export const OC_SCHEDULER_ACTIVE = 1;
export const OC_SCHEDULER_INACTIVE = 0;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       SHAPES                                                       */
/* ------------------------------------------------------------------------------------------------------------------ */

/** How a method names the connector it runs against, in place of the old embedded invoker. */
export interface OcConnectorRef {
    connectorId: number;
    title: string;
    icon: string | null;
    invokerName: string;

    /** Present on connectors OpenCelium has tested; passed through when it is. */
    lastTestPassed?: boolean;
}


export interface OcMethod {
    /** Node identity, shared with the ui block: 'method-0', 'method-1'. */
    id: string;
    name: string;

    /** Omitted rather than sent as null when the method has no label, as the captures show. */
    label?: string;

    /** Position in the execution tree: '0' for the source, '1_0' for a method inside the loop. */
    index: string;
    methodType: 'CONNECTOR';
    dataAggregator: null;
    color: string;
    connector: OcConnectorRef;
    request: any;
    response: any;
}


export interface OcOperator {
    /** Node identity, shared with the ui block: 'loop-0'. */
    id: string;
    index: string;
    type: 'loop' | 'if';
    dataAggregator: null;

    /** e.g. for {%#FFCFB5.(response).body.$.results[*]%} */
    expression: string;
    iterator: string;

    /** Only sent when the automation restricts which objects take part. */
    condition?: string;
}


export interface OcConnectorSide {
    connectorId: number;
    title: string;
    methods: OcMethod[];
    operators: OcOperator[];
}


export interface OcFieldBindingSide {
    color: string;
    field: string;
    type: 'request' | 'response';
}


export interface OcEnhancement {
    name: string;
    description: string;
    language: string;
    simpleCode: string | null;

    /** Comment lines declaring the referenced fields. */
    expertVar: string;

    /** The assignment that moves the value across, e.g. RESULT_VAR = VAR_0; */
    expertCode: string;
}


export interface OcFieldBinding {
    from: OcFieldBindingSide[];
    to: OcFieldBindingSide[];
    enhancement: OcEnhancement;
}


export interface OcUiRule {
    id: string;
    type: 'rule';
    properties: {
        operator: string;
        leftField: string;
        rightField: string;
    };
}


export interface OcUiGroup {
    id: string;
    type: 'group';
    properties: { not: boolean };
    items: OcUiRule[];
}


export interface OcWorkflowNode {
    id: string;
    type: 'start' | 'connector' | 'loop';
    position: { x: number; y: number };

    /** Mirrors the method's or operator's execution index; absent on the start node. */
    index?: string;
    data: any;
    draggable?: boolean;
    deletable?: boolean;
}


export interface OcWorkflowEdge {
    id: string;
    source: string;
    target: string;

    /** Absent when the edge leaves the node's default side. */
    sourceHandle?: string;
    targetHandle: string;
    type: 'workflow-edge';

    /** The create capture carries an empty object here, the update capture omits the key. */
    data?: Record<string, never>;
}


export interface OcFlowchart {
    flowId: string;
    x: number;
    y: number;
}


export type OcFlowchartEdge = Omit<OcWorkflowEdge, 'type' | 'data'>;


/**
 * The workflow graph.
 *
 * `workflowNodes`/`workflowEdges` drive the editor; `flowcharts`/`flowchartEdges` repeat the same
 * graph reduced to positions and links. Both are sent, as the captures show.
 */
export interface OcUi {
    viewport: { x: number; y: number; zoom: number };
    workflowNodes: OcWorkflowNode[];
    workflowEdges: OcWorkflowEdge[];
    flowcharts: OcFlowchart[];
    flowchartEdges: OcFlowchartEdge[];
}


export interface OcConnection {
    title: string;

    /** Repeats the title. OpenCelium sends both and rejects a connection that carries only one. */
    name: string;
    description: string;
    fieldBinding: OcFieldBinding[];
    fromConnector: OcConnectorSide;

    /** Always null: a connection no longer has a second connector side. */
    toConnector: null;
    ui: OcUi;

    /** Only present on the PUT /connections payload. */
    connectionId?: number;
}


export interface OcSchedulerPayload {
    title: string;
    debugMode: boolean;
    status: number;
    cronExp: string;
}


/** Body of POST /rest/open_celium/schedulers. */
export interface OcCreateAutomationRequest {
    connection: OcConnection;
    scheduler: OcSchedulerPayload;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                  FIELD REFERENCES                                                  */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Builds the reference string one method uses to read another method's field.
 *
 * Format: #COLOR.(response|request).body.$.path - the colour already carries its own '#'.
 */
export function ocFieldReference(color: string, side: 'request' | 'response', path: string): string {
    return `${color}.(${side}).body.$.${path}`;
}


/**
 * Builds the loop expression that iterates a source response collection.
 *
 * Format: for {%#COLOR.(response).body.$.path[*]%}
 */
export function ocLoopExpression(color: string, arrayPath: string): string {
    return `for {%${color}.(response).body.$.${arrayPath}[*]%}`;
}


/**
 * Which element of a collection a reference points at.
 *
 * A collection the loop iterates is addressed by the loop's iterator - `results[i]` - so every pass
 * reads its own object. `results[0]` would read the first object on every pass, which is the shape
 * the earliest captures carried and the reason an automation appeared to work on a single test
 * object and repeat itself on real data. A collection nobody iterates, such as the answer to a
 * lookup, is addressed by position instead: `result[0]` is the match that was found.
 */
export function ocCollectionElementPath(
    arrayPath: string,
    field: string,
    element: string = OC_LOOP_ITERATOR
): string {
    if (!arrayPath) {
        return field;
    }

    return `${arrayPath}[${element}].${field}`;
}


/** Node and edge identities, shared between the connection body and its ui block. */
export function ocMethodNodeId(position: number): string {
    return `method-${position}`;
}


export function ocLoopNodeId(position: number): string {
    return `loop-${position}`;
}


/**
 * Edge identity, built from what the edge connects.
 *
 * The captures spell out the handles in the id - 'default' standing in for a source handle that is
 * not set - so the same edge always gets the same id.
 */
export function ocEdgeId(edge: { source: string; target: string; sourceHandle?: string; targetHandle: string }): string {
    return `edge-${edge.source}-${edge.target}-${edge.sourceHandle ?? 'default'}-${edge.targetHandle}`;
}
