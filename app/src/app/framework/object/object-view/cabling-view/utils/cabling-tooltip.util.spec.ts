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
import { PortSide } from '../../ports-overview/models/ports-overview.types';
import { CABLING_TOOLTIP, DEFAULT_CABLE_STROKE, DEFAULT_DISPLAY_OPTIONS } from '../constants/cabling.constants';
import { CablingEdge, CablingNodeLayout, CablingResponse } from '../models/cabling.types';
import {
    CABLE_FRONT,
    FRONT_12,
    NAS_01,
    PP_01,
    WEB_01,
    WEB_ETH0,
    cablingEdge,
    cablingEnd,
    frontEdge,
    mockupRing,
    nasEdge,
    ppNode,
    rearEdge,
    resolvedCable,
    restrictedNode,
    switchNode
} from '../testing/cabling-fixtures';
import { graphFromRing } from './cabling-graph.util';
import { layoutCablingNodes } from './cabling-layout.util';
import { cableTooltip, placeCableTooltip } from './cabling-tooltip.util';

describe('cabling-tooltip.util', () => {

    const layouts = (response: CablingResponse = mockupRing()): Map<number, CablingNodeLayout> =>
        layoutCablingNodes(graphFromRing(response), DEFAULT_DISPLAY_OPTIONS, new Set());

    const withCable = (edge: CablingEdge, cable: CablingEdge['cable']): CablingEdge => ({ ...edge, cable });

    describe('cableTooltip', () => {
        it('titles the cable by its name and puts the details it has on one line', () => {
            const tooltip = cableTooltip(frontEdge(), layouts());

            expect(tooltip.connectionId).toBe(CABLE_FRONT);
            expect(tooltip.title).toBe('CAT6-001');
            expect(tooltip.stroke).toBe('blue');
            expect(tooltip.details).toBe('2 m · blue');
            expect(tooltip.description).toBeNull();
        });

        it('lists the type next to a name, and titles by the type when there is no name', () => {
            const om4 = resolvedCable({ name: 'OM4-001', type: 'OM4', length: '35 m' });

            expect(cableTooltip(withCable(frontEdge(), om4), layouts()).details).toBe('OM4 · 35 m');

            const typeOnly = cableTooltip(withCable(frontEdge(), resolvedCable({ name: '  ', type: 'OM4' })), layouts());

            expect(typeOnly.title).toBe('OM4');
            expect(typeOnly.details).toBeNull();
        });

        it('names a cable without details and keeps the default colour', () => {
            const tooltip = cableTooltip(withCable(frontEdge(), null), layouts());

            expect(tooltip.title).toBe('Unnamed cable');
            expect(tooltip.details).toBeNull();
            expect(tooltip.stroke).toBe(DEFAULT_CABLE_STROKE);
        });

        it('trims the description and drops an empty one', () => {
            const described = resolvedCable({ name: 'CAT6-001', description: '  Uplink to core  ' });

            expect(cableTooltip(withCable(frontEdge(), described), layouts()).description).toBe('Uplink to core');
            expect(cableTooltip(withCable(frontEdge(), resolvedCable({ description: ' ' })), layouts()).description)
                .toBeNull();
        });

        it('reads the ends left to right, whatever order the cable stores them in', () => {
            const nodes = layouts();
            const reversed = cablingEdge(
                CABLE_FRONT,
                cablingEnd(WEB_01, WEB_ETH0, 'eth0', PortSide.SINGLE),
                cablingEnd(PP_01, FRONT_12, 'Front 12', PortSide.FRONT)
            );

            expect(nodes.get(WEB_01).x).toBeLessThan(nodes.get(PP_01).x);
            expect(cableTooltip(reversed, nodes).ends.map((end) => end.title)).toEqual(['WEB-01', 'PP-01']);
            expect(cableTooltip(frontEdge(), nodes).ends.map((end) => end.title)).toEqual(['WEB-01', 'PP-01']);
        });

        it('adds the panel face only when the port name does not say it', () => {
            const nodes = layouts();
            const numbered = cablingEdge(
                CABLE_FRONT,
                cablingEnd(PP_01, FRONT_12, '12', PortSide.FRONT),
                cablingEnd(WEB_01, WEB_ETH0, 'eth0', PortSide.SINGLE)
            );

            expect(cableTooltip(frontEdge(), nodes).ends[1]).toEqual(
                { title: 'PP-01', port: 'Front 12', side: null, restricted: false });
            expect(cableTooltip(numbered, nodes).ends[1].side).toBe('Front');
            expect(cableTooltip(numbered, nodes).ends[0].side).toBeNull();
        });

        it('names a restricted end without a port', () => {
            const masked = cablingEdge(
                CABLE_FRONT,
                cablingEnd(PP_01, FRONT_12, 'Front 12', PortSide.FRONT),
                cablingEnd(WEB_01, WEB_ETH0, null, null)
            );
            const nodes = layouts({
                focal_object_id: PP_01,
                nodes: [ppNode(), restrictedNode(WEB_01), switchNode()],
                edges: [masked, rearEdge()]
            });

            expect(cableTooltip(masked, nodes).ends[0]).toEqual(
                { title: 'Restricted object', port: null, side: null, restricted: true });
        });

        it('is null while either end is off the canvas', () => {
            const nodes = layouts();

            expect(nodes.has(NAS_01)).toBeFalse();
            expect(cableTooltip(nasEdge(), nodes)).toBeNull();
        });
    });

    describe('placeCableTooltip', () => {
        const { width, gap, margin, arrowInset } = CABLING_TOOLTIP;
        const frame = { width: 1000, height: 600 };

        it('sits centred above the spot, its arrow straight over it', () => {
            expect(placeCableTooltip({ x: 500, y: 300 }, frame))
                .toEqual({ x: 500, y: 300, offset: -width / 2, arrow: width / 2, below: false });
        });

        it('stays inside the frame and moves its arrow to keep pointing at the spot', () => {
            const nearLeft = placeCableTooltip({ x: 60, y: 300 }, frame);
            const nearRight = placeCableTooltip({ x: 900, y: 300 }, frame);

            expect(60 + nearLeft.offset).toBe(margin);
            expect(nearLeft.arrow).toBe(60 - margin);
            expect(900 + nearRight.offset + width).toBe(frame.width - margin);
            expect(nearRight.offset + nearRight.arrow).toBe(0);
        });

        it('keeps the arrow off the corners at the very edge', () => {
            expect(placeCableTooltip({ x: 2, y: 300 }, frame).arrow).toBe(arrowInset);
            expect(placeCableTooltip({ x: 998, y: 300 }, frame).arrow).toBe(width - arrowInset);
        });

        it('drops below the spot when the room above runs out', () => {
            expect(placeCableTooltip({ x: 500, y: gap + margin + 40 }, frame).below).toBeTrue();
        });

        it('stays above when the room below is no bigger', () => {
            expect(placeCableTooltip({ x: 500, y: 100 }, { width: 1000, height: 150 }).below).toBeFalse();
        });

        it('keeps its left edge in a frame narrower than itself', () => {
            expect(100 + placeCableTooltip({ x: 100, y: 300 }, { width: 200, height: 600 }).offset).toBe(margin);
        });
    });
});
