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
import { DEFAULT_CABLE_STROKE, DEFAULT_NODE_ICON } from '../constants/cabling.constants';
import {
    NAS_01,
    cabledPort,
    overviewPort,
    ppNode,
    resolvedCable,
    restrictedNode,
    webNode
} from '../testing/cabling-fixtures';
import {
    cableLabel,
    cableStroke,
    farEndLabel,
    nodeAccent,
    nodeIcon,
    nodeTitle,
    paintableCableColor,
    portView
} from './cabling-format.util';

describe('cabling-format.util', () => {

    describe('nodeTitle', () => {
        it('uses the label field the type names', () => {
            expect(nodeTitle(webNode())).toBe('WEB-01');
        });

        it('falls back to the type and id when the type names no label field', () => {
            expect(nodeTitle({ ...webNode(), title: null })).toBe('Device #8703');
            expect(nodeTitle({ ...webNode(), title: '  ' })).toBe('Device #8703');
        });

        it('reads a numeric label as text', () => {
            expect(nodeTitle({ ...webNode(), title: 42 })).toBe('42');
        });

        it('never names a restricted object by its id', () => {
            expect(nodeTitle(restrictedNode(8705))).toBe('Restricted object');
        });
    });

    describe('nodeIcon', () => {
        it('keeps a complete icon class and completes a bare one', () => {
            expect(nodeIcon(webNode())).toBe('fas fa-server');
            expect(nodeIcon(ppNode())).toBe('fas fa-grip');
        });

        it('falls back for a missing or malformed icon', () => {
            expect(nodeIcon({ ...webNode(), type_info: null })).toBe(DEFAULT_NODE_ICON);
            expect(nodeIcon({ ...webNode(), type_info: { ...webNode().type_info, icon: 'fa-x" onclick="' } }))
                .toBe(DEFAULT_NODE_ICON);
        });

        it('shows a lock for a restricted object', () => {
            expect(nodeIcon(restrictedNode(8705))).toBe('fas fa-lock');
        });
    });

    describe('nodeAccent', () => {
        it('takes the type colour and ignores one that is not a hex colour', () => {
            expect(nodeAccent(webNode())).toBe('#1f77b4');
            expect(nodeAccent({ ...webNode(), type_info: { ...webNode().type_info, type_color: 'red;' } })).toBe('#64748b');
        });
    });

    describe('cableLabel', () => {
        it('reads name and length, then the type, then a plain word', () => {
            expect(cableLabel(resolvedCable({ name: 'CAT6-001', length: '15 m' }))).toBe('CAT6-001 · 15 m');
            expect(cableLabel(resolvedCable({ type: 'CAT6' }))).toBe('CAT6');
            expect(cableLabel(resolvedCable({ type: ' ' }))).toBe('Cable');
            expect(cableLabel(null)).toBe('Cable');
        });
    });

    describe('paintableCableColor', () => {
        it('paints a CSS colour name or a hex literal', () => {
            expect(paintableCableColor(resolvedCable({ color: 'blue' }))).toBe('blue');
            expect(paintableCableColor(resolvedCable({ color: '#00ff00' }))).toBe('#00ff00');
        });

        it('refuses a word no browser knows as a colour, and anything that is not a plain value', () => {
            expect(paintableCableColor(resolvedCable({ color: 'grau' }))).toBeNull();
            expect(paintableCableColor(resolvedCable({ color: 'url(#x)' }))).toBeNull();
            expect(cableStroke(resolvedCable({ color: 'grau' }))).toBe(DEFAULT_CABLE_STROKE);
        });
    });

    describe('portView', () => {
        const cabled = () => cabledPort(8809, 'Gi1/0/24', {
            objectId: NAS_01, label: 'Device #8704 - NAS-01', portId: 8812, portName: 'e0a'
        }, 8903, resolvedCable(), {
            port_type: { id: 1, label: 'RJ45' },
            speed: { id: 2, label: '1 GbE' },
            status: { id: null, label: null }
        });

        it('names the far end and the port details', () => {
            const view = portView(cabled(), new Set());

            expect(view.cabled).toBeTrue();
            expect(view.farEnd).toBe('Device #8704 - NAS-01 · e0a');
            expect(view.meta).toBe('RJ45 · 1 GbE');
            expect(view.expandable).toBeTrue();
        });

        it('stops offering to follow a cable once its far end is drawn', () => {
            expect(portView(cabled(), new Set([NAS_01])).expandable).toBeFalse();
        });

        it('treats a port without a cable as free, whatever its connected flag says', () => {
            const view = portView(overviewPort(8813, 'e0b', { connected: true }), new Set());

            expect(view.cabled).toBeFalse();
            expect(view.farEnd).toBeNull();
            expect(view.expandable).toBeFalse();
        });

        it('masks a restricted far end', () => {
            const port = cabled();
            port.connected_object = { object_id: 8705, label: null, restricted: true };

            expect(farEndLabel(port)).toBe('Restricted object');
            expect(portView(port, new Set()).expandLabel).not.toContain('8705');
        });
    });
});
