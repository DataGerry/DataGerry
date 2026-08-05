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
 * Note the two endpoints differ in shape:
 *   POST /rest/open_celium/schedulers      -> { connection, scheduler }, connectors carry no title
 *   PUT  /rest/open_celium/connections/:id -> the flat connection, connectors carry a title
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

/** Geometry of the connection graph, mirroring the reference payloads exactly. */
export const OC_LAYOUT = {
    methodWidth: 130,
    methodHeight: 80,
    operatorWidth: 60,
    operatorHeight: 60,
    sourceMethodX: 0,
    sourceMethodY: 0,
    targetOperatorX: 515,
    targetOperatorY: 10,
    targetMethodX: 480,
    targetMethodY: 150
} as const;

/** Connector side identifiers used in svgItem ids and connectorType. */
export const OC_FROM_CONNECTOR = 'fromConnector';
export const OC_TO_CONNECTOR = 'toConnector';

/** The wizard always emits expert-mode connections; it does not use OpenCelium templates. */
export const OC_EXPERT_TEMPLATE = { mode: 'expert', templateId: -1, label: '' } as const;

/** Scheduler status values OpenCelium expects (1 = active). */
export const OC_SCHEDULER_ACTIVE = 1;
export const OC_SCHEDULER_INACTIVE = 0;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                       SHAPES                                                       */
/* ------------------------------------------------------------------------------------------------------------------ */

export interface OcError {
    hasError: boolean;
    messages: string[];
}


export interface OcMethod {
    name: string;
    request: any;
    response: any;
    dataAggregator: null;

    /** Position in the execution tree: '0' for the source, '0_0' for a target method in a loop. */
    index: string;
    label: string | null;
    color: string;
    error: OcError;
}


export interface OcOperator {
    index: string;
    type: 'loop' | 'if';
    condition: string | null;

    /** e.g. for {%#FFCFB5.(response).body.$.result[*]%} */
    expression: string;
    uiId: string;
    dataAggregator: null;
    iterator: string;
    error: OcError;
}


export interface OcSvgItem {
    id: string;
    name?: string;
    type?: string;
    label?: string;
    x: number;
    y: number;
    width: number;
    height: number;
    isDragged: boolean;
    isDraggedForCopy: boolean;
    isAvailableForDragging: boolean;
    isSelectedAll: boolean;
    connectorType: string;
    invoker: null;
    entity: any;
    items?: OcSvgItem[];
    arrows?: OcArrow[];
}


export interface OcArrow {
    from: string;
    to: string;
}


export interface OcConnectorSide {
    invoker: any;
    connectorId: number;
    methods: OcMethod[];
    icon: string;
    operators: OcOperator[];

    /** Only present on the PUT /connections payload, omitted on POST /schedulers. */
    title?: string;
    currentItemIndex: string;
    svgItems: OcSvgItem[];
    arrows: OcArrow[];
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


export interface OcConnection {
    title: string;
    description: string;
    fromConnector: OcConnectorSide;
    toConnector: OcConnectorSide;
    fieldBinding: OcFieldBinding[];
    categoryId: number | null;
    ui: { operators: OcUiGroup[] };
    id: number;
    template: typeof OC_EXPERT_TEMPLATE;
    readOnly: boolean;

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
 * Format: #COLOR.(response|request).body.$.path
 */
export function ocFieldReference(color: string, side: 'request' | 'response', path: string): string {
    return `#${color}.(${side}).body.$.${path}`;
}


/**
 * Builds the loop expression that iterates a source response collection.
 *
 * Format: for {%#COLOR.(response).body.$.path[*]%}
 */
export function ocLoopExpression(color: string, arrayPath: string): string {
    return `for {%#${color}.(response).body.$.${arrayPath}[*]%}`;
}


/**
 * The element path a field binding uses inside a looped collection.
 *
 * The reference payloads address the element as `path[0]` in fieldBinding while the surrounding
 * loop iterates `path[*]`; OpenCelium substitutes the iterator at runtime. That asymmetry is
 * deliberate and reproduced here - keep it in this one function should it turn out to be
 * version dependent.
 */
export function ocCollectionElementPath(arrayPath: string, field: string): string {
    if (!arrayPath) {
        return field;
    }

    return `${arrayPath}[0].${field}`;
}


export function ocEmptyError(): OcError {
    return { hasError: false, messages: [] };
}
