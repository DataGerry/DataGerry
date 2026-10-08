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
 * What a run writes about itself, as OpenCelium stores it.
 *
 * Every shape here is the shape the four log routes under `/open_celium/connections/logs` return -
 * they proxy OpenCelium's `/execution/log/element` endpoints unchanged, so this file is the only
 * place in the log view that knows OpenCelium's vocabulary.
 *
 * One join carries the whole view: a trace's `indexPath` is the `index` of the method or operator
 * that produced it. That is how a line in the log finds the step in the connection it came from,
 * and with it the name and the rule the user actually built.
 */

/** A step in a run is a call, a condition or a loop - nothing else reaches the viewer. */
export type OcTraceType = 'OPERATION' | 'IF' | 'LOOP';

/** How a trace ended. Derived rather than read: OpenCelium reports the pieces, not the verdict. */
export type RunStepState = 'ok' | 'error' | 'skipped' | 'running';


export interface OcTraceRequest {
    http_method?: string;
    url?: string;

    /** A JSON document in a string, or absent. Parsed for display, never trusted to parse. */
    header?: string;
    payload?: unknown;
}


export interface OcTraceResponse {
    status?: string | number;
    duration?: string;
    header?: string;
    payload?: unknown;
}


/**
 * The part of a trace that only arrives when its detail is asked for.
 *
 * For a call that is request and response; for an operator it is `result`, the string 'true' or
 * 'false'. Anything else OpenCelium puts in here is kept, because the operator's own segment is
 * where the resolved sides of a condition would appear if it reports them - and the raw tab shows
 * whatever is there either way.
 */
export interface OcTraceSegment {
    request?: OcTraceRequest;
    response?: OcTraceResponse;
    result?: string;
    [key: string]: unknown;
}


export interface OcTraceProperties {
    /** The step's name, when the connection gave the method one. */
    name?: string;

    /** Loops only: how many entries the loop walked. A string in some payloads. */
    size?: number | string;

    /** Loops only: the name the loop gives the entry it is on. */
    iterator?: string;

    /** Loops only: which entry the trace belongs to. */
    loopIndex?: string;
    [key: string]: unknown;
}


export interface OcTrace {
    id: string;
    type: OcTraceType;

    /** Position in the execution tree: '0', '1_0'. Also the `index` of the step behind it. */
    indexPath: string;

    isCompleted?: boolean;
    hasError?: boolean;
    error?: { message?: string } | null;
    properties?: OcTraceProperties;
    segment?: OcTraceSegment;
    children?: OcTrace[];
}


/** One connector's branch of a run. `flowId` addresses it, `id` fetches its first level. */
export interface RunFlowchart {
    id: string | number;
    flowId: string | number;
    connectorName?: string;
}


/** An entry of the run list, as `/open_celium/schedulers/logs` returns it. */
export interface AutomationRunEntry {
    execution_id: number;
    connection_id?: number;
    status?: 's' | 'f';
    log_date?: string | { $date?: number };
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     VIEW MODEL                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * A condition in the form it is worth reading.
 *
 * `left`, `operator` and `right` come out of the connection's own rule tree, which is where the
 * wizard stored what the user picked - so a condition reads as the user wrote it rather than as the
 * expression OpenCelium executes. The expression is kept beside it for the people who want it.
 *
 * `leftValue` and `rightValue` are the resolved sides. They are filled only when the run actually
 * reports them; `resolved` says which of the two cases the panel is in, so it can be honest about
 * the difference instead of printing an empty field.
 */
export interface RunConditionRule {
    left: string;
    operator: string;
    right: string;
    expression: string;
    leftValue?: string;
    rightValue?: string;
    resolved: boolean;
}


/**
 * One line of the tree, with everything the template needs to draw it.
 *
 * The node is mutable on purpose: expanding a line loads its detail into the same object, and the
 * template re-reads it. `key` is the identity the view keeps its own state under - it has to stay
 * stable across a reload of the node's children, which rules out the array index.
 */
export interface RunLogNode {
    key: string;
    flowId: string | number;
    trace: OcTrace;
    depth: number;
    parent: RunLogNode | null;

    /** Which entry of each enclosing loop this node sits in, outermost first. */
    loopPath: number[];

    children: RunLogNode[];
    childrenLoaded: boolean;
    expanded: boolean;
    loading: boolean;
    detailLoaded: boolean;

    /** Loops only: the entry the view is showing. */
    iteration: number;

    /** Which detail tab is open on this node. */
    tab: string;

    /**
     * Conditions only: the rule, worked out once.
     *
     * Reading it is a template expression, so it is asked for on every change-detection pass -
     * building it each time would allocate a new object per pass. Cleared when the node's detail
     * arrives, which is the only thing that can change the answer.
     */
    rule?: RunConditionRule;
}


/** What the header says about the run as a whole. */
export interface RunSummary {
    total: number;
    ok: number;
    errors: number;
    skipped: number;
    complete: boolean;
}


/** A connector's branch, once it is a tree of nodes. */
export interface RunLogBranch {
    flowId: string | number;
    name: string;
    nodes: RunLogNode[];
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                      HELPERS                                                       */
/* ------------------------------------------------------------------------------------------------------------------ */

/** True when the trace itself failed - not when something inside it did. */
export function traceFailed(trace: OcTrace): boolean {
    return !!trace.error?.message || trace.hasError === true;
}


/**
 * Whether a condition came out true.
 *
 * OpenCelium writes the verdict as the string 'true', so anything else - 'false', an empty string,
 * a segment that has not been loaded yet - is not a yes. The caller decides what to do about the
 * difference between 'no' and 'not known yet'.
 */
export function conditionHolds(trace: OcTrace): boolean {
    return trace.segment?.result === 'true';
}


/** How many entries a loop walked. Absent and unparsable both mean none. */
export function loopSize(trace: OcTrace): number {
    const size = Number(trace.properties?.size ?? 0);

    return Number.isFinite(size) && size > 0 ? size : 0;
}


/** How a trace ended, in the terms the view colours by. */
export function stepState(trace: OcTrace): RunStepState {
    if (traceFailed(trace)) {
        return 'error';
    }

    if (trace.isCompleted === false) {
        return 'running';
    }

    if (trace.type === 'IF' && trace.segment?.result !== undefined && !conditionHolds(trace)) {
        return 'skipped';
    }

    if (trace.type === 'LOOP' && loopSize(trace) === 0) {
        return 'skipped';
    }

    return 'ok';
}


/**
 * The HTTP status as a number, for deciding whether a call was answered well.
 *
 * OpenCelium sends it as a string in some payloads and a number in others, and an unfinished call
 * sends nothing at all - which is why a missing status is not an error here.
 */
export function responseStatus(trace: OcTrace): number | null {
    const raw = trace.segment?.response?.status;

    if (raw === undefined || raw === null || raw === '') {
        return null;
    }

    const status = Number(raw);

    return Number.isFinite(status) ? status : null;
}


/** Pretty-prints a payload or a header string, leaving anything unparsable as it came. */
export function formatPayload(value: unknown): string {
    if (value === undefined || value === null || value === '') {
        return '';
    }

    if (typeof value !== 'string') {
        try {
            return JSON.stringify(value, null, 2);
        } catch {
            return String(value);
        }
    }

    try {
        return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
        return value;
    }
}
