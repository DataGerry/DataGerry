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
import { CABLING_GEOMETRY, CABLING_ROUTING } from '../constants/cabling.constants';
import {
    CablingEdgeEnd,
    CablingEdgePlan,
    CablingExit,
    CablingHook,
    CablingRoute,
    CablingTurn
} from '../models/cabling-routing.types';
import { CablingNodeLayout, CablingPoint } from '../models/cabling.types';
import { direction, facesAway, passesWrap } from './cabling-edge-plan.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const { nodeGap, curveMin } = CABLING_GEOMETRY;

/** Room kept between a routed cable and a card it passes. */
const CLEARANCE = 8;


export function routeEdge(
    plan: CablingEdgePlan,
    cards: CablingNodeLayout[],
    reaches: ReadonlyMap<number, number>,
    hooks: ReadonlyMap<string, CablingHook>
): CablingRoute {
    switch (plan.kind) {
        case 'bracket':
            return curveRoute(plan.from, plan.to, reaches.get(plan.edge.connection_id));
        case 'passage':
            return passageRoute(plan, cards);
        case 'hook':
            return hookRoute(plan, hooks);
        default:
            return curveRoute(plan.from, plan.to);
    }
}


/** Cables between two cards of one column loop out on the same side; the longer the loop, the wider it bows. */
export function bracketReaches(plans: CablingEdgePlan[]): Map<number, number> {
    const groups = new Map<string, CablingEdgePlan[]>();

    plans.filter((plan) => plan.kind === 'bracket').forEach((plan) => {
        const key = `${ plan.from.node.column }:${ plan.from.node.wrapped }:${ plan.from.side }`;
        groups.set(key, [...(groups.get(key) ?? []), plan]);
    });

    const reaches = new Map<number, number>();

    groups.forEach((group) => group
        .sort((first, second) => span(first) - span(second))
        .forEach((plan, index) => reaches.set(
            plan.edge.connection_id,
            CABLING_ROUTING.bracketReach + index * CABLING_ROUTING.bracketStep
        )));

    return reaches;
}


/** Hooks running along one card edge nest: the row nearest the turn takes the tightest. */
export function hookShapes(plans: CablingEdgePlan[]): Map<string, CablingHook> {
    const groups = new Map<string, CablingTurn[]>();

    plans
        .filter((plan) => plan.kind === 'hook')
        .flatMap((plan): CablingTurn[] => [
            { key: `${ plan.edge.connection_id }:from`, end: plan.from, other: plan.to, below: false },
            { key: `${ plan.edge.connection_id }:to`, end: plan.to, other: plan.from, below: false }
        ])
        .filter((turn) => facesAway(turn.end, turn.other))
        .forEach((turn) => {
            const below = turnsBelow(turn.end, turn.other);
            const group = `${ turn.end.node.objectId }:${ below }`;

            groups.set(group, [...(groups.get(group) ?? []), { ...turn, below }]);
        });

    const hooks = new Map<string, CablingHook>();

    groups.forEach((group) => group
        .sort((first, second) => (first.below ? second.end.point.y - first.end.point.y : first.end.point.y - second.end.point.y))
        .forEach((turn, index) => {
            const { node } = turn.end;
            const clearance = nodeGap / 2 + index * CABLING_ROUTING.hookStep;

            hooks.set(turn.key, {
                bulge: CABLING_ROUTING.hookReach + index * CABLING_ROUTING.hookStep,
                level: turn.below ? node.y + node.height + clearance : node.y - clearance
            });
        }));

    return hooks;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function span(plan: CablingEdgePlan): number {
    return Math.abs(plan.from.point.y - plan.to.point.y);
}


function curveRoute(from: CablingEdgeEnd, to: CablingEdgeEnd, reach?: number): CablingRoute {
    const pull = reach ?? Math.max(curveMin, Math.abs(to.point.x - from.point.x) / 2);
    const fromControl = { x: from.point.x + direction(from.side) * pull, y: from.point.y };
    const toControl = { x: to.point.x + direction(to.side) * pull, y: to.point.y };

    return {
        path: `M ${ from.point.x } ${ from.point.y } C ${ fromControl.x } ${ fromControl.y }, `
            + `${ toControl.x } ${ toControl.y }, ${ to.point.x } ${ to.point.y }`,
        labelAt: curveMiddle(from.point, fromControl, toControl, to.point)
    };
}


function curveMiddle(start: CablingPoint, startControl: CablingPoint, endControl: CablingPoint, end: CablingPoint): CablingPoint {
    return {
        x: (start.x + 3 * startControl.x + 3 * endControl.x + end.x) / 8,
        y: (start.y + 3 * startControl.y + 3 * endControl.y + end.y) / 8
    };
}


/** From the focal object to the second sub-column: level through a gap of the first, then into the port. */
function passageRoute(plan: CablingEdgePlan, cards: CablingNodeLayout[]): CablingRoute {
    const [near, far] = passesWrap(plan.from, plan.to) ? [plan.from, plan.to] : [plan.to, plan.from];
    const inner = cards
        .filter((card) => card.column === far.node.column && !card.wrapped)
        .sort((first, second) => first.y - second.y);

    if (!inner.length) {
        return curveRoute(plan.from, plan.to);
    }

    const left = Math.min(...inner.map((card) => card.x));
    const right = Math.max(...inner.map((card) => card.x + card.width));
    const level = passageLevel(inner, far.point.y);
    const pull = Math.max(curveMin, (left - near.point.x) / 2);
    const bend = (far.point.x - right) / 2;

    return {
        path: `M ${ near.point.x } ${ near.point.y } C ${ near.point.x + pull } ${ near.point.y }, ${ left - pull } ${ level }, `
            + `${ left } ${ level } L ${ right } ${ level } C ${ right + bend } ${ level }, `
            + `${ far.point.x - bend } ${ far.point.y }, ${ far.point.x } ${ far.point.y }`,
        labelAt: { x: (near.point.x + left) / 2, y: (near.point.y + level) / 2 }
    };
}


/** The height nearest to `y` at which a cable clears every card of the first sub-column. */
function passageLevel(inner: CablingNodeLayout[], y: number): number {
    const gaps: Array<[number, number]> = [[-Infinity, inner[0].y - CLEARANCE]];

    inner.forEach((card, index) => gaps.push([
        card.y + card.height + CLEARANCE,
        index + 1 < inner.length ? inner[index + 1].y - CLEARANCE : Infinity
    ]));

    return gaps
        .filter(([top, bottom]) => top <= bottom)
        .map(([top, bottom]) => Math.min(Math.max(y, top), bottom))
        .reduce((best, level) => (Math.abs(level - y) < Math.abs(best - y) ? level : best));
}


/** Under the card when that is the shorter way round to the far end. */
function turnsBelow(end: CablingEdgeEnd, other: CablingEdgeEnd): boolean {
    const bottom = end.node.y + end.node.height;
    const top = end.node.y;

    return Math.abs(end.point.y - bottom) + Math.abs(other.point.y - bottom)
        <= Math.abs(end.point.y - top) + Math.abs(other.point.y - top);
}


/** Turns back around the card of a port facing away, then curves to the far end like any other cable. */
function hookRoute(plan: CablingEdgePlan, hooks: ReadonlyMap<string, CablingHook>): CablingRoute {
    const start = exitFrom(plan.from, hooks.get(`${ plan.edge.connection_id }:from`));
    const end = exitFrom(plan.to, hooks.get(`${ plan.edge.connection_id }:to`));
    const pull = Math.max(curveMin, Math.abs(end.point.x - start.point.x) / 2);
    const startControl = { x: start.point.x + start.heading * pull, y: start.point.y };
    const endControl = { x: end.point.x + end.heading * pull, y: end.point.y };

    return {
        path: `M ${ plan.from.point.x } ${ plan.from.point.y } ${ start.out }`
            + `C ${ startControl.x } ${ startControl.y }, ${ endControl.x } ${ endControl.y }, ${ end.point.x } ${ end.point.y }`
            + end.back,
        labelAt: curveMiddle(start.point, startControl, endControl, end.point)
    };
}


/** Straight out of the port, or past the hook that turns back and runs under or over its card. */
function exitFrom(end: CablingEdgeEnd, hook: CablingHook | undefined): CablingExit {
    const outwards = direction(end.side);

    if (!hook) {
        return { point: end.point, heading: outwards, out: '', back: '' };
    }

    const { x, y } = end.point;
    const bow = x + outwards * hook.bulge;
    const farEdge = x - outwards * end.node.width;

    return {
        point: { x: farEdge, y: hook.level },
        heading: -outwards,
        out: `C ${ bow } ${ y }, ${ bow } ${ hook.level }, ${ x } ${ hook.level } L ${ farEdge } ${ hook.level } `,
        back: ` L ${ x } ${ hook.level } C ${ bow } ${ hook.level }, ${ bow } ${ y }, ${ x } ${ y }`
    };
}
