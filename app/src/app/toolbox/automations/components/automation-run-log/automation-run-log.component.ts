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
import { Component, inject, EventEmitter, Input, Output, OnChanges, SimpleChanges } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import {
    OcTrace,
    RunConditionRule,
    RunLogBranch,
    RunLogNode,
    RunStepState,
    RunSummary,
    conditionHolds,
    formatPayload,
    loopSize,
    responseStatus,
    stepState,
    traceFailed
} from '../../models/automation-run-log.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Tabs a call offers; a condition has its own set. */
const CALL_TABS = ['exchange', 'headers'] as const;
const CONDITION_TABS = ['condition', 'values', 'raw'] as const;

/** How deep the view will follow an error flag on its own before handing over to the reader. */
const REVEAL_DEPTH_LIMIT = 12;


/**
 * What one run did, as the sequence the user built rather than as the requests it sent.
 *
 * The log OpenCelium keeps is a tree of traces addressed by `indexPath`, and `indexPath` is also
 * the `index` of the step in the connection that produced it. Joining the two is what lets a line
 * carry the step's name and a condition carry the rule the user wrote - the log alone knows neither.
 *
 * Two things are loaded lazily, because they are too heavy to send for a whole run: a step's
 * request and response, and what ran inside a condition or a loop. Both land on the node that
 * asked for them, so a line keeps what it fetched when it is collapsed and opened again.
 *
 * On "otherwise": in the execution tree a condition's children are the steps that run when it
 * holds. What runs when it does not hold is the condition's next sibling, not a child of it - the
 * compiler wires that step to the `false` exit and gives it the next index on the same level. The
 * panel therefore names the sibling rather than inventing a second branch underneath.
 */
@Component({
    selector: 'app-automation-run-log',
    templateUrl: './automation-run-log.component.html',
    styleUrls: ['./automation-run-log.component.scss'],
    standalone: false
})
export class AutomationRunLogComponent implements OnChanges {

    @Input() public executionId: number | null = null;

    /**
     * The connection the run belongs to, when the caller knows it.
     *
     * Only an enrichment: it supplies step names and the rules behind the conditions. Without it
     * the view still works, it just falls back to what the log itself carries.
     */
    @Input() public connectionId: number | null = null;

    /** What the run list said about the run, which is the only verdict on the run as a whole. */
    @Input() public runStatus: 's' | 'f' | null = null;
    @Input() public runDate: string | { $date?: number } | null = null;

    @Output() public loaded = new EventEmitter<void>();

    public branches: RunLogBranch[] = [];
    public summary: RunSummary = { total: 0, ok: 0, errors: 0, skipped: 0, complete: true };
    public loading = false;
    public loadError = '';

    public query = '';
    public onlyErrors = false;
    public onlyConditions = false;
    public allExpanded = false;

    /** Keys of the nodes that pass filter and search. Recomputed whenever either changes. */
    private visibleKeys = new Set<string>();

    /** Step name by execution index, from the connection. Empty when no connection was given. */
    private stepNames = new Map<string, string>();

    /** Condition rules by execution index, from the connection's own rule tree. */
    private stepRules = new Map<string, { left: string; operator: string; right: string; expression: string }>();

    /**
     * Step name by the colour it is referenced under.
     *
     * A reference into another step's answer names that step by its colour, not by its name -
     * '#FFCFB5.(response).body.$.results[i].public_id' reads the method whose colour is #FFCFB5.
     * This is what turns such a reference back into something a person can read.
     */
    private stepColours = new Map<string, string>();

    /** True once a connection was asked for and answered, which decides what a missing rule means. */
    private connectionRead = false;

    private readonly automationsService = inject(AutomationsService);
    private readonly toast = inject(ToastService);

    /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['executionId'] || changes['connectionId']) {
            this.load();
        }
    }

    /* ------------------------------------------------- DATA LOADING ------------------------------------------------- */

    /**
     * Fetches the run: its connector branches, and the top level of each.
     *
     * The connection is fetched alongside when one was named, and a failure to fetch it is not a
     * failure to show the run - the names and rules are simply missing then.
     */
    public load(): void {
        this.branches = [];
        this.loadError = '';
        this.visibleKeys = new Set<string>();
        this.stepNames = new Map<string, string>();
        this.stepRules = new Map<string, { left: string; operator: string; right: string; expression: string }>();
        this.stepColours = new Map<string, string>();
        this.connectionRead = false;

        const executionId = this.executionId;

        if (!executionId) {
            return;
        }

        this.loading = true;

        const connection$ = this.connectionId
            ? this.automationsService.getConnection(this.connectionId).pipe(catchError(() => of(null)))
            : of(null);

        connection$
            .pipe(
                tap(connection => this.readConnection(connection)),
                switchMap(() => this.automationsService.getRunFlowcharts(executionId)),
                switchMap(flowcharts => {
                    const list = Array.isArray(flowcharts) ? flowcharts : [];

                    if (!list.length) {
                        return of([] as RunLogBranch[]);
                    }

                    return forkJoin(list.map(flowchart =>
                        this.automationsService.getRunFirstLevel(flowchart.id).pipe(
                            catchError(() => of([] as OcTrace[])),
                            map(traces => ({
                                flowId: flowchart.flowId,
                                name: flowchart.connectorName || 'Connector',
                                nodes: (Array.isArray(traces) ? traces : []).map((trace, position) =>
                                    this.toNode(trace, flowchart.flowId, `${flowchart.flowId}.${position}`, 0, null, [])
                                )
                            } as RunLogBranch))
                        )
                    ));
                }),
                finalize(() => {
                    this.loading = false;
                    this.loaded.emit();
                })
            )
            .subscribe({
                next: branches => {
                    this.branches = branches;
                    this.recomputeSummary();
                    this.recomputeVisibility();
                    this.revealFirstError();
                },
                error: err => {
                    this.loadError = err?.error?.message || 'The log for this run could not be loaded.';
                }
            });
    }


    /**
     * Reads step names and condition rules out of the connection.
     *
     * Methods carry a label only where the compiler had one to give, so the name falls back through
     * the method's own name. The rule comes from the workflow node's `conditionConfig`, which is
     * where the wizard stored what the user picked in the rule builder.
     */
    private readConnection(connection: any): void {
        if (!connection) {
            return;
        }

        this.connectionRead = true;

        const methods = connection?.fromConnector?.methods ?? [];

        for (const method of methods) {
            const name = method?.label || method?.name || '';

            if (method?.index) {
                this.stepNames.set(`${method.index}`, name);
            }

            if (method?.color) {
                this.stepColours.set(
                    `${method.color}`.replace('#', '').toUpperCase(),
                    name || `step ${method.index}`
                );
            }
        }

        const nodes = connection?.ui?.workflowNodes ?? [];

        for (const node of nodes) {
            if (!node?.index) {
                continue;
            }

            const config = node?.data?.conditionConfig;
            const rule = config?.tree?.items?.[0]?.properties;

            if (!rule) {
                continue;
            }

            this.stepRules.set(`${node.index}`, {
                left: `${rule.leftField ?? ''}`,
                operator: `${rule.operator ?? ''}`,
                right: rule.rightField === undefined ? '' : `${rule.rightField}`,
                expression: `${config?.expression ?? ''}`
            });
        }
    }


    /** Wraps a trace in the state the view keeps beside it. */
    private toNode(
        trace: OcTrace,
        flowId: string | number,
        key: string,
        depth: number,
        parent: RunLogNode | null,
        loopPath: number[]
    ): RunLogNode {
        return {
            key,
            flowId,
            trace,
            depth,
            parent,
            loopPath,
            children: [],
            childrenLoaded: false,
            expanded: false,
            loading: false,

            // Never true to begin with, however much the trace already carries. The tree arrives
            // with a segment that holds the method, the URL, the status and the duration - but not
            // the headers and not the bodies. Those only come with the step's own detail, so
            // treating a present segment as a loaded one leaves every body empty.
            detailLoaded: false,
            iteration: 0,
            tab: trace.type === 'OPERATION' ? CALL_TABS[0] : CONDITION_TABS[0]
        };
    }

    /* --------------------------------------------------- EVENTS ----------------------------------------------------- */

    /**
     * Opens or closes a line, fetching what it needs the first time it is opened.
     *
     * A condition that did not hold is opened like any other: its detail is the rule and the reason
     * nothing below it ran, which is exactly what the reader came for.
     */
    public toggle(node: RunLogNode): void {
        if (node.expanded) {
            node.expanded = false;
            this.recomputeVisibility();

            return;
        }

        node.expanded = true;
        this.recomputeVisibility();
        this.fill(node);
    }


    /** Fetches a node's detail and, for an operator, its children - each at most once. */
    private fill(node: RunLogNode, onDone?: () => void): void {
        const needsDetail = !node.detailLoaded;
        const needsChildren = node.trace.type !== 'OPERATION' && !node.childrenLoaded;

        if (!needsDetail && !needsChildren) {
            onDone?.();

            return;
        }

        node.loading = true;

        const detail$ = needsDetail
            ? this.automationsService.getRunStepDetails(node.trace.id).pipe(catchError(() => of(null)))
            : of(null);

        const children$ = needsChildren
            ? this.automationsService
                .getRunStepChildren(node.trace.id, this.innermostIteration(node))
                .pipe(catchError(() => of(null)))
            : of(null);

        forkJoin([detail$, children$])
            .pipe(finalize(() => {
                node.loading = false;
            }))
            .subscribe(([detail, children]) => {
                if (detail?.segment) {
                    // Merged, not replaced: a condition's verdict arrives with the tree, and the
                    // detail of an operator does not always carry it back. Replacing would throw
                    // away the one thing the line already knew.
                    node.trace.segment = { ...node.trace.segment, ...detail.segment };
                    node.detailLoaded = true;

                    // The verdict and any resolved sides arrive with the segment, so the rule that
                    // was worked out before it has to be worked out again.
                    node.rule = undefined;
                }

                if (children !== null) {
                    node.children = (Array.isArray(children) ? children : []).map((trace, position) =>
                        this.toNode(
                            trace,
                            node.flowId,
                            `${node.key}.${node.iteration}.${position}`,
                            node.depth + 1,
                            node,
                            node.trace.type === 'LOOP' ? [...node.loopPath, node.iteration] : node.loopPath
                        )
                    );
                    node.childrenLoaded = true;
                }

                this.recomputeSummary();
                this.recomputeVisibility();
                onDone?.();
            });
    }


    /**
     * Moves a loop to another entry.
     *
     * Each entry is its own fetch - OpenCelium answers for one entry at a time - so the children
     * are dropped and asked for again rather than kept per entry, which would hold a whole run in
     * memory for a loop of any size.
     */
    public setIteration(node: RunLogNode, iteration: number): void {
        const size = this.size(node);
        const next = Math.min(Math.max(iteration, 0), Math.max(size - 1, 0));

        if (next === node.iteration && node.childrenLoaded) {
            return;
        }

        node.iteration = next;
        node.children = [];
        node.childrenLoaded = false;
        node.expanded = true;
        this.fill(node);
    }


    public onIterationInput(node: RunLogNode, value: string): void {
        const entry = Number(value);

        if (Number.isFinite(entry)) {
            this.setIteration(node, Math.round(entry) - 1);
        }
    }


    public setTab(node: RunLogNode, tab: string): void {
        node.tab = tab;
    }


    public onQueryChanged(value: string): void {
        this.query = value;
        this.recomputeVisibility();
    }


    public toggleOnlyErrors(): void {
        this.onlyErrors = !this.onlyErrors;
        this.recomputeVisibility();
    }


    public toggleOnlyConditions(): void {
        this.onlyConditions = !this.onlyConditions;
        this.recomputeVisibility();
    }


    /** Opens or closes every line that is already loaded. Nothing is fetched by this. */
    public toggleExpandAll(): void {
        this.allExpanded = !this.allExpanded;
        this.eachNode(node => {
            node.expanded = this.allExpanded;
        });
        this.recomputeVisibility();
    }


    /**
     * Scrolls to the first failed step that is loaded, opening the lines above it.
     *
     * Only what is loaded can be found: a step inside a loop entry nobody has opened has not been
     * fetched, so the view says it found nothing rather than implying there is nothing.
     */
    public jumpToError(): void {
        const failed = this.findNode(node => traceFailed(node.trace));

        if (!failed) {
            this.toast.info('No failed step among the steps loaded so far. Open the loops and conditions to load more.');

            return;
        }

        for (let parent = failed.parent; parent; parent = parent.parent) {
            parent.expanded = true;
        }

        this.recomputeVisibility();

        setTimeout(() => {
            const row = document.getElementById(this.rowId(failed));

            row?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            row?.classList.add('run-log__row--flash');
            setTimeout(() => row?.classList.remove('run-log__row--flash'), 1800);
        });
    }


    /**
     * Follows the error flags the run already carries, so a failed run opens where it failed.
     *
     * OpenCelium marks the ancestors of a failure only on some payloads. Where it does, this walks
     * straight to the step; where it does not, nothing is expanded and the reader is no worse off.
     */
    private revealFirstError(): void {
        if (this.runStatus !== 'f') {
            return;
        }

        const follow = (nodes: RunLogNode[], depth: number): void => {
            if (depth > REVEAL_DEPTH_LIMIT) {
                return;
            }

            const marked = nodes.find(node => node.trace.hasError === true && node.trace.type !== 'OPERATION');

            if (!marked) {
                return;
            }

            marked.expanded = true;
            this.fill(marked, () => follow(marked.children, depth + 1));
        };

        for (const branch of this.branches) {
            follow(branch.nodes, 0);
        }
    }

    /* --------------------------------------------------- GETTERS ---------------------------------------------------- */

    public get hasRun(): boolean {
        return !!this.executionId;
    }


    public get isEmpty(): boolean {
        return !this.loading && !this.loadError && this.branches.every(branch => !branch.nodes.length);
    }


    /** False when the filters have hidden everything, which needs saying rather than showing blank. */
    public get hasVisibleSteps(): boolean {
        return this.visibleKeys.size > 0;
    }


    /**
     * Whether this run has a failure to jump to at all.
     *
     * The run list's verdict counts as well as a step the view has already loaded: a failed run has
     * somewhere to jump to even before the failing step has been fetched. With neither, there is
     * nothing to offer and the control does not belong on screen.
     */
    public get hasFailure(): boolean {
        return this.runStatus === 'f' || this.summary.errors > 0;
    }


    /**
     * Why a condition's rule is not on screen - or nothing when it is.
     *
     * Two different cases, and telling them apart is the difference between a dead end and a next
     * step: the view was opened without a connection, or the connection has nothing at this
     * step's position.
     */
    public missingRuleReason(node: RunLogNode): string {
        if (this.rule(node).left || this.rule(node).expression) {
            return '';
        }

        if (!this.connectionId) {
            return 'The rule is stored with the connection, and this view was opened without one. '
                + 'Open the run from the automation itself to see what the condition compared.';
        }

        if (!this.connectionRead) {
            return 'The connection behind this run could not be read, so the rule is unavailable.';
        }

        return 'The connection holds no rule at this step\'s position. That happens when the '
            + 'automation was changed after this run, since the log keeps the old positions.';
    }


    public get callTabs(): ReadonlyArray<string> {
        return CALL_TABS;
    }


    public get conditionTabs(): ReadonlyArray<string> {
        return CONDITION_TABS;
    }


    public isVisible(node: RunLogNode): boolean {
        return this.visibleKeys.has(node.key);
    }


    public rowId(node: RunLogNode): string {
        return `run-step-${node.key.replace(/[^\w-]/g, '_')}`;
    }


    public state(node: RunLogNode): RunStepState {
        return stepState(node.trace);
    }


    public size(node: RunLogNode): number {
        return loopSize(node.trace);
    }


    public status(node: RunLogNode): number | null {
        return responseStatus(node.trace);
    }


    public holds(node: RunLogNode): boolean {
        return conditionHolds(node.trace);
    }


    /** Whether the condition has been answered at all - its detail may simply not be loaded yet. */
    public hasVerdict(node: RunLogNode): boolean {
        return node.trace.segment?.result !== undefined;
    }


    /**
     * The step's position in the sequence, read off its place in the execution tree.
     *
     * '0' is the first step, '1_0' the first step inside the second. Counting the lines instead
     * would renumber everything as soon as a loop entry is opened.
     */
    public position(node: RunLogNode): string {
        return `${node.trace.indexPath ?? ''}`
            .split('_')
            .map(part => {
                const value = Number(part);

                return Number.isFinite(value) ? `${value + 1}` : part;
            })
            .join('.');
    }


    /**
     * What to call the step.
     *
     * The connection's name for it comes first, because that is the name the user gave it; the log
     * carries one only for some steps, and a URL is the last resort rather than the headline.
     */
    public title(node: RunLogNode): string {
        const named = this.stepNames.get(`${node.trace.indexPath}`);

        if (named) {
            return named;
        }

        if (node.trace.properties?.name) {
            return `${node.trace.properties.name}`;
        }

        if (node.trace.type === 'IF') {
            return 'Condition';
        }

        if (node.trace.type === 'LOOP') {
            return `For each entry${node.trace.properties?.iterator ? ` (${node.trace.properties.iterator})` : ''}`;
        }

        return this.url(node) || 'Call';
    }


    public url(node: RunLogNode): string {
        return `${node.trace.segment?.request?.url ?? ''}`;
    }


    public method(node: RunLogNode): string {
        return `${node.trace.segment?.request?.http_method ?? ''}`.toUpperCase();
    }


    public duration(node: RunLogNode): string {
        return `${node.trace.segment?.response?.duration ?? ''}`;
    }


    public errorMessage(node: RunLogNode): string {
        return `${node.trace.error?.message ?? ''}`;
    }


    /**
     * The condition in the form the panel reads it out.
     *
     * The rule is the connection's; the verdict is the run's. The resolved sides are only reported
     * when OpenCelium puts them in the operator's segment, and `resolved` carries that difference
     * so the panel can say "not reported" instead of showing an empty value as if it were one.
     */
    public rule(node: RunLogNode): RunConditionRule {
        if (!node.rule) {
            node.rule = this.buildRule(node);
        }

        return node.rule;
    }


    private buildRule(node: RunLogNode): RunConditionRule {
        const stored = this.stepRules.get(`${node.trace.indexPath}`);
        const segment = node.trace.segment ?? {};
        const leftValue = this.reportedSide(segment, ['leftValue', 'left', 'leftResult', 'leftOperand']);
        const rightValue = this.reportedSide(segment, ['rightValue', 'right', 'rightResult', 'rightOperand']);

        // The run may carry the expression itself; the connection is only the better source.
        const expression = stored?.expression
            || this.reportedSide(segment, ['expression', 'condition'])
            || '';

        return {
            left: this.readableReference(stored?.left ?? ''),
            leftRaw: stored?.left ?? '',
            operator: stored?.operator ?? '',
            right: this.readableReference(stored?.right ?? ''),
            rightRaw: stored?.right ?? '',
            expression,
            leftValue,
            rightValue,
            resolved: leftValue !== undefined || rightValue !== undefined
        };
    }


    /**
     * Turns a reference into something a person can read.
     *
     * A reference names the step it reads by colour and then walks that step's answer:
     * '#FFCFB5.(response).body.$.results[i].public_id'. The colour becomes the step's name and the
     * envelope in the middle - which is the same on every reference and so says nothing - is
     * dropped. A value that is not a reference is returned untouched.
     */
    private readableReference(value: string): string {
        if (!value || !value.startsWith('#')) {
            return value;
        }

        const colour = value.slice(1, 7).toUpperCase();
        const named = this.stepColours.get(colour);

        if (!named) {
            return value;
        }

        const path = value
            .slice(7)
            .replace(/^\.\((?:response|request)\)\.body\.\$\./, '')
            .replace(/^\./, '');

        return path ? `${named} · ${path}` : named;
    }


    /** Reads a resolved side out of the segment under any of the names it might carry. */
    private reportedSide(segment: Record<string, unknown>, keys: string[]): string | undefined {
        for (const key of keys) {
            const value = segment[key];

            if (value !== undefined && value !== null && value !== '') {
                return typeof value === 'string' ? value : JSON.stringify(value);
            }
        }

        return undefined;
    }


    /**
     * The step the run continues at when a condition does not hold.
     *
     * In the execution tree that is the condition's next sibling: the compiler gives a step placed
     * after a condition the next index on the same level and wires it to the `false` exit. There is
     * no second list of children to show, and pretending there is would misread the tree.
     */
    public otherwise(node: RunLogNode): RunLogNode | null {
        const siblings = node.parent
            ? node.parent.children
            : this.branches.find(branch => branch.flowId === node.flowId)?.nodes ?? [];
        const position = siblings.indexOf(node);

        return position >= 0 && position + 1 < siblings.length ? siblings[position + 1] : null;
    }


    public requestHeaders(node: RunLogNode): string {
        return formatPayload(node.trace.segment?.request?.header);
    }


    public requestBody(node: RunLogNode): string {
        return formatPayload(node.trace.segment?.request?.payload);
    }


    public responseHeaders(node: RunLogNode): string {
        return formatPayload(node.trace.segment?.response?.header);
    }


    public responseBody(node: RunLogNode): string {
        return formatPayload(node.trace.segment?.response?.payload);
    }


    public rawSegment(node: RunLogNode): string {
        return formatPayload(node.trace.segment ?? {});
    }


    public copy(value: string): void {
        if (!value || !navigator.clipboard) {
            return;
        }

        navigator.clipboard.writeText(value).then(
            () => this.toast.success('Copied'),
            () => this.toast.error('Could not copy to the clipboard')
        );
    }


    public tabLabel(tab: string): string {
        return {
            exchange: 'Sent / received',
            headers: 'Headers',
            condition: 'Condition',
            values: 'Values',
            raw: 'Raw'
        }[tab] ?? tab;
    }


    public formatRunDate(): string {
        const value = this.runDate;

        if (!value) {
            return '';
        }

        const raw = typeof value === 'string' ? value : value?.$date;

        if (raw === undefined || raw === null) {
            return '';
        }

        const date = new Date(raw);

        return isNaN(date.getTime()) ? `${raw}` : date.toLocaleString();
    }


    public trackByKey(index: number, node: RunLogNode): string {
        return node.key;
    }


    public trackByFlow(index: number, branch: RunLogBranch): string {
        return `${branch.flowId}`;
    }

    /* ------------------------------------------------- COMPUTATION --------------------------------------------------- */

    /** The innermost loop entry a node sits in. Steps outside any loop pass 0, which the route needs. */
    private innermostIteration(node: RunLogNode): number {
        if (node.trace.type === 'LOOP') {
            return node.iteration;
        }

        return node.loopPath.length ? node.loopPath[node.loopPath.length - 1] : 0;
    }


    /**
     * Counts the steps the view holds.
     *
     * Deliberately over what is loaded rather than over the run: nothing short of fetching every
     * loop entry would give the real totals, and the header says which of the two it is showing.
     */
    private recomputeSummary(): void {
        const summary: RunSummary = { total: 0, ok: 0, errors: 0, skipped: 0, complete: true };

        this.eachNode(node => {
            summary.total += 1;

            switch (stepState(node.trace)) {
                case 'error':
                    summary.errors += 1;
                    break;
                case 'skipped':
                    summary.skipped += 1;
                    break;
                case 'running':
                    summary.complete = false;
                    break;
                default:
                    summary.ok += 1;
            }
        });

        this.summary = summary;
    }


    /**
     * Works out which lines the filters leave standing.
     *
     * A line stays when it matches, and also when something below it matches - otherwise filtering
     * would cut the path to the match and leave it unreachable. The search reads the step's name,
     * its URL and whatever of its payloads has been loaded.
     */
    private recomputeVisibility(): void {
        const visible = new Set<string>();
        const query = this.query.trim().toLowerCase();

        const walk = (nodes: RunLogNode[]): boolean => {
            let anyVisible = false;

            for (const node of nodes) {
                const childVisible = walk(node.children);
                const self = this.passesFilters(node, query);

                if (self || childVisible) {
                    visible.add(node.key);
                    anyVisible = true;
                }
            }

            return anyVisible;
        };

        for (const branch of this.branches) {
            walk(branch.nodes);
        }

        this.visibleKeys = visible;
    }


    private passesFilters(node: RunLogNode, query: string): boolean {
        if (this.onlyErrors && !traceFailed(node.trace)) {
            return false;
        }

        if (this.onlyConditions && node.trace.type !== 'IF') {
            return false;
        }

        if (!query) {
            return true;
        }

        const rule = this.stepRules.get(`${node.trace.indexPath}`);
        const haystack = [
            this.title(node),
            this.url(node),
            this.method(node),
            this.errorMessage(node),
            rule?.left,
            rule?.right,
            rule?.expression,
            formatPayload(node.trace.segment?.request?.payload),
            formatPayload(node.trace.segment?.response?.payload)
        ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase();

        return haystack.includes(query);
    }


    private eachNode(visit: (node: RunLogNode) => void): void {
        const walk = (nodes: RunLogNode[]): void => {
            for (const node of nodes) {
                visit(node);
                walk(node.children);
            }
        };

        for (const branch of this.branches) {
            walk(branch.nodes);
        }
    }


    private findNode(predicate: (node: RunLogNode) => boolean): RunLogNode | null {
        const walk = (nodes: RunLogNode[]): RunLogNode | null => {
            for (const node of nodes) {
                if (predicate(node)) {
                    return node;
                }

                const found = walk(node.children);

                if (found) {
                    return found;
                }
            }

            return null;
        };

        for (const branch of this.branches) {
            const found = walk(branch.nodes);

            if (found) {
                return found;
            }
        }

        return null;
    }
}
