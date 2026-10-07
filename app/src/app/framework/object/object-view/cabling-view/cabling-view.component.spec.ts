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
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { CablingViewComponent } from './cabling-view.component';
import { CablingService } from './services/cabling.service';
import {
    CABLE_REAR,
    NAS_01,
    PP_01,
    SW_01,
    WEB_01,
    frontEdge,
    mockupRing,
    nasEdge,
    nasExpansion,
    nasNode,
    ppNode,
    rearEdge,
    standardNode,
    switchNode,
    webNode
} from './testing/cabling-fixtures';

/** Answers with the mockup ring until a test says otherwise. */
const cablingServiceSpy = (): jasmine.SpyObj<CablingService> => {
    const service = jasmine.createSpyObj<CablingService>('CablingService', ['getObjectCabling', 'getPortCabling']);
    service.getObjectCabling.and.returnValue(of(mockupRing()));

    return service;
};

const configureTestBed = (cablingService: CablingService): Promise<unknown> => TestBed.configureTestingModule({
    imports: [CablingViewComponent],
    providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: CablingService, useValue: cablingService },
        { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error', 'info']) }
    ]
}).compileComponents();

describe('CablingViewComponent cable tooltip', () => {
    let fixture: ComponentFixture<CablingViewComponent>;

    const element = (): HTMLElement => fixture.nativeElement;
    const cable = (): SVGPathElement => element().querySelector('.cabling-edge__hit');
    const tooltip = (): HTMLElement | null => element().querySelector('cmdb-cabling-cable-tooltip');

    const point = (type: string, client: DOMPoint, pointerType = 'mouse') => {
        const init = { clientX: client.x, clientY: client.y, pointerType, bubbles: type === 'pointermove' };
        cable().dispatchEvent(new PointerEvent(type, init));
        fixture.detectChanges();
    };

    /** A point `at` of the way along the first cable, pushed `off` canvas pixels across it, on screen. */
    const onCable = (at: number, off = 0): DOMPoint => {
        const length = cable().getTotalLength() * at;
        const before = cable().getPointAtLength(length - 1);
        const after = cable().getPointAtLength(length + 1);
        const centre = cable().getPointAtLength(length);
        const run = Math.hypot(after.x - before.x, after.y - before.y);
        const normal = { x: -(after.y - before.y) / run, y: (after.x - before.x) / run };

        return new DOMPoint(centre.x + normal.x * off, centre.y + normal.y * off).matrixTransform(cable().getScreenCTM());
    };

    /** Where the tooltip points, in client pixels. */
    const spot = (): DOMPoint => {
        const frame = element().querySelector('.cabling-view__viewport').getBoundingClientRect();
        const [, x, y] = tooltip().style.transform.match(/translate3d\((-?[\d.]+)px, (-?[\d.]+)px/).map(Number);

        return new DOMPoint(frame.left + x, frame.top + y);
    };

    const distance = (first: DOMPoint, second: DOMPoint) => Math.hypot(first.x - second.x, first.y - second.y);

    beforeEach(async () => {
        await configureTestBed(cablingServiceSpy());

        fixture = TestBed.createComponent(CablingViewComponent);
        fixture.componentRef.setInput('objectId', PP_01);
        fixture.detectChanges();
    });

    it('shows the cable the moment the pointer enters it', () => {
        expect(tooltip()).toBeNull();

        point('pointerenter', onCable(0.5));

        expect(tooltip()).not.toBeNull();
        expect(tooltip().getAttribute('aria-hidden')).toBe('true');
        expect(tooltip().textContent).toContain('CAT6-001');
        expect(tooltip().textContent).toContain('PP-01');
        expect(tooltip().textContent).toContain('WEB-01');
        expect(tooltip().textContent).toContain('2 m');
        expect(cable().querySelector('title')).toBeNull();
    });

    it('points at the spot on the cable nearest the pointer', () => {
        point('pointerenter', onCable(0.4, 5));

        expect(distance(spot(), onCable(0.4))).toBeLessThan(1);
    });

    it('follows the pointer along the cable and leaves with it', () => {
        point('pointerenter', onCable(0.3));
        point('pointermove', onCable(0.6));

        expect(distance(spot(), onCable(0.6))).toBeLessThan(1);

        point('pointerleave', onCable(0.6));

        expect(tooltip()).toBeNull();
    });

    it('highlights on a touch without showing a tooltip', () => {
        point('pointerenter', onCable(0.5), 'touch');

        expect(tooltip()).toBeNull();
        expect(fixture.componentInstance.highlightedConnectionId()).not.toBeNull();
    });

    it('hides once the canvas moves under the pointer', () => {
        point('pointerenter', onCable(0.5));
        element().querySelector('.cabling-view__viewport').dispatchEvent(new KeyboardEvent('keydown', { key: '+' }));
        fixture.detectChanges();

        expect(tooltip()).toBeNull();

        point('pointermove', onCable(0.5));

        expect(tooltip()).not.toBeNull();
    });

    it('brings a clicked cable to the front, and puts it back on a second click', () => {
        const raised = () => element().querySelector('.cabling-view__edges--raised');

        cable().dispatchEvent(new MouseEvent('click', { bubbles: true }));
        fixture.detectChanges();

        expect(raised()).not.toBeNull();

        cable().dispatchEvent(new MouseEvent('click', { bubbles: true }));
        fixture.detectChanges();

        expect(raised()).toBeNull();
    });
});


describe('CablingViewComponent spotlight', () => {
    let fixture: ComponentFixture<CablingViewComponent>;
    let cablingService: jasmine.SpyObj<CablingService>;

    const element = (): HTMLElement => fixture.nativeElement;
    const viewport = (): HTMLElement => element().querySelector('.cabling-view__viewport');
    const shade = (): HTMLElement | null => element().querySelector('.cabling-view__shade');
    const card = (objectId: number): HTMLElement => element().querySelector(`[data-object-id="${ objectId }"]`);
    const raisedCables = (): number => element().querySelectorAll('.cabling-view__edges--raised .cabling-edge').length;
    const selected = (): number | null => fixture.componentInstance.selectedConnectionId();
    const toolbarButton = (label: string): HTMLButtonElement =>
        element().querySelector(`.cabling-view__toolbar button[aria-label="${ label }"]`);

    const press = (key: string) => {
        viewport().dispatchEvent(new KeyboardEvent('keydown', { key }));
        fixture.detectChanges();
    };

    const click = (target: Element) => {
        target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        fixture.detectChanges();
    };

    const show = (objectId: number) => {
        fixture.componentRef.setInput('objectId', objectId);
        fixture.detectChanges();
    };

    const portOn = (objectId: number, portName: string): HTMLElement => Array.from(
        card(objectId).querySelectorAll<HTMLElement>('.cabling-port')
    ).find((port) => port.querySelector('.cabling-port__name').textContent.trim() === portName);

    const rowOf = (objectId: number, portName: string): HTMLElement =>
        portOn(objectId, portName).closest('.cabling-row');

    const faceOf = (objectId: number, portName: string): HTMLElement =>
        portOn(objectId, portName).closest('.cabling-row__face');

    const markedInCards = (): number => element().querySelectorAll('cmdb-cabling-node .is-highlighted').length;

    /** Follows the cable of the port with this name, on the card of this object. */
    const expand = (objectId: number, portName: string) => {
        click(portOn(objectId, portName).querySelector('.cabling-port__expand button'));
    };

    beforeEach(async () => {
        cablingService = cablingServiceSpy();
        await configureTestBed(cablingService);

        fixture = TestBed.createComponent(CablingViewComponent);
    });

    it('shows the free ports while their toolbar toggle is pressed', () => {
        show(PP_01);

        expect(toolbarButton('Show free ports').getAttribute('aria-pressed')).toBe('false');
        expect(fixture.componentInstance.options().onlyConnected).toBeTrue();

        click(toolbarButton('Show free ports'));

        expect(toolbarButton('Show free ports').getAttribute('aria-pressed')).toBe('true');
        expect(fixture.componentInstance.options().onlyConnected).toBeFalse();
    });

    it('is off until asked for, and a picked port then only brings its cable to the front', () => {
        show(PP_01);

        expect(toolbarButton('Spotlight').getAttribute('aria-pressed')).toBe('false');

        click(portOn(WEB_01, 'eth0'));

        expect(raisedCables()).toBe(1);
        expect(shade()).toBeNull();
        expect(card(WEB_01).classList).not.toContain('cabling-node--shaded');
        expect(rowOf(WEB_01, 'eth0').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Front 12').classList).toContain('is-highlighted');
    });

    it('puts every card under the shade until a port is picked', () => {
        show(PP_01);
        press('s');

        expect(toolbarButton('Spotlight').getAttribute('aria-pressed')).toBe('true');
        expect(shade()).not.toBeNull();
        [PP_01, WEB_01, SW_01].forEach((objectId) => {
            expect(card(objectId).classList).toContain('cabling-node--shaded');
        });
        expect(raisedCables()).toBe(0);
    });

    it('adds no scroll range to the canvas frame, so nothing can scroll the drawing away', () => {
        show(PP_01);
        const { scrollWidth, scrollHeight } = viewport();

        press('s');

        expect(viewport().scrollWidth).toBe(scrollWidth);
        expect(viewport().scrollHeight).toBe(scrollHeight);
    });

    it('leaves even the picked card dark and marks only the ports on the route back to this object', () => {
        cablingService.getPortCabling.and.returnValue(of(nasExpansion()));
        show(PP_01);
        expand(SW_01, 'Gi1/0/24');
        press('s');
        click(portOn(NAS_01, 'e0a'));

        [NAS_01, SW_01, PP_01, WEB_01].forEach((objectId) => {
            expect(card(objectId).classList).toContain('cabling-node--shaded');
        });
        expect(rowOf(NAS_01, 'e0a').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/24').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Front 12').classList).not.toContain('is-highlighted');
        expect(card(WEB_01).querySelector('.is-highlighted')).toBeNull();
        expect(raisedCables()).toBe(2);
    });

    it('lights the same route when the nearer end of the cable is picked', () => {
        cablingService.getPortCabling.and.returnValue(of(nasExpansion()));
        show(PP_01);
        expand(SW_01, 'Gi1/0/24');
        press('s');
        click(portOn(SW_01, 'Gi1/0/24'));

        expect(card(SW_01).classList).toContain('cabling-node--shaded');
        expect(rowOf(SW_01, 'Gi1/0/24').classList).toContain('is-highlighted');
        expect(rowOf(NAS_01, 'e0a').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(raisedCables()).toBe(2);
    });

    it('stops at this object, so its cable on the other face stays dark', () => {
        show(PP_01);
        press('s');
        click(portOn(SW_01, 'Gi1/0/12'));

        expect(card(SW_01).classList).toContain('cabling-node--shaded');
        expect(rowOf(SW_01, 'Gi1/0/12').classList).toContain('is-highlighted');
        expect(card(PP_01).classList).toContain('cabling-node--shaded');
        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Front 12').classList).not.toContain('is-highlighted');
        expect(card(PP_01).querySelector('.cabling-pair.is-highlighted')).toBeNull();
        expect(card(WEB_01).querySelector('.is-highlighted')).toBeNull();
        expect(selected()).toBe(CABLE_REAR);
        expect(raisedCables()).toBe(1);
    });

    it('runs the route through a patch panel\'s internal link', () => {
        cablingService.getObjectCabling.and.returnValue(of({
            focal_object_id: SW_01,
            nodes: [switchNode(), ppNode(), nasNode()],
            edges: [rearEdge(), nasEdge()]
        }));
        cablingService.getPortCabling.and.returnValue(of({
            focal_object_id: PP_01,
            nodes: [webNode()],
            edges: [frontEdge()]
        }));
        show(SW_01);
        expand(PP_01, 'Front 12');
        press('s');
        click(portOn(WEB_01, 'eth0'));

        expect(card(WEB_01).classList).toContain('cabling-node--shaded');
        expect(rowOf(WEB_01, 'eth0').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Front 12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(card(PP_01).querySelector('.cabling-pair').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/12').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/24').classList).not.toContain('is-highlighted');
        expect(raisedCables()).toBe(2);
    });

    it('keeps the cable lit when its other end is picked', () => {
        show(PP_01);
        press('s');
        click(portOn(SW_01, 'Gi1/0/12'));
        click(portOn(PP_01, 'Rear 12'));

        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(rowOf(SW_01, 'Gi1/0/12').classList).toContain('is-highlighted');
        expect(raisedCables()).toBe(1);
        expect(selected()).toBe(CABLE_REAR);
    });

    it('marks the picked face of a patch panel pair, not the whole row', () => {
        show(PP_01);
        press('s');
        click(portOn(PP_01, 'Rear 12'));

        expect(faceOf(PP_01, 'Rear 12').classList).toContain('is-highlighted');
        expect(faceOf(PP_01, 'Front 12').classList).not.toContain('is-highlighted');
        expect(rowOf(PP_01, 'Rear 12').classList).not.toContain('is-highlighted');
    });

    it('marks no port while one is only pointed at', () => {
        show(PP_01);
        press('s');
        portOn(WEB_01, 'eth0').dispatchEvent(new MouseEvent('mouseenter'));
        fixture.detectChanges();

        expect(markedInCards()).toBe(0);
    });

    it('lights only the cable when the cable itself is clicked', () => {
        show(PP_01);
        press('s');
        click(element().querySelector('.cabling-edge__hit'));

        expect(raisedCables()).toBe(1);
        expect(markedInCards()).toBe(0);
    });

    it('puts the cable back on a second pick, on Escape or on a background click, and stays on', () => {
        show(PP_01);
        press('s');
        click(portOn(WEB_01, 'eth0'));
        click(portOn(WEB_01, 'eth0'));

        expect(selected()).toBeNull();
        expect(shade()).not.toBeNull();

        click(portOn(WEB_01, 'eth0'));
        press('Escape');

        expect(selected()).toBeNull();
        expect(shade()).not.toBeNull();

        click(portOn(WEB_01, 'eth0'));
        click(viewport());

        expect(selected()).toBeNull();
        expect(shade()).not.toBeNull();
    });

    it('stays on through background clicks and Escape until the toolbar turns it off', () => {
        show(PP_01);
        press('s');
        click(viewport());
        click(viewport());
        press('Escape');
        press('Escape');

        expect(toolbarButton('Spotlight').getAttribute('aria-pressed')).toBe('true');
        expect(shade()).not.toBeNull();

        click(toolbarButton('Spotlight'));

        expect(toolbarButton('Spotlight').getAttribute('aria-pressed')).toBe('false');
        expect(shade()).toBeNull();
    });

    it('turns off when another object is opened', () => {
        show(PP_01);
        press('s');
        show(WEB_01);

        expect(toolbarButton('Spotlight').getAttribute('aria-pressed')).toBe('false');
        expect(shade()).toBeNull();
    });

    it('cannot be turned on while the object has no cables', () => {
        cablingService.getObjectCabling.and.returnValue(of({
            focal_object_id: PP_01,
            nodes: [standardNode(PP_01, 'PP-01', [])],
            edges: []
        }));
        show(PP_01);
        press('s');

        expect(toolbarButton('Spotlight').disabled).toBeTrue();
        expect(shade()).toBeNull();
    });
});
