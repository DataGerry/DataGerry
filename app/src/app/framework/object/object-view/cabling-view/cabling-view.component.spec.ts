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
import { PP_01, mockupRing } from './testing/cabling-fixtures';

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
        const cablingService = jasmine.createSpyObj<CablingService>('CablingService', ['getObjectCabling', 'getPortCabling']);
        cablingService.getObjectCabling.and.returnValue(of(mockupRing()));

        await TestBed.configureTestingModule({
            imports: [CablingViewComponent],
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: CablingService, useValue: cablingService },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['error', 'info']) }
            ]
        }).compileComponents();

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
        fixture.componentInstance.zoomIn();
        fixture.detectChanges();

        expect(tooltip()).toBeNull();

        point('pointermove', onCable(0.5));

        expect(tooltip()).not.toBeNull();
    });

    it('tells what a click on the cable does', () => {
        point('pointerenter', onCable(0.5));

        expect(tooltip().textContent).toContain('Click to bring to front');

        cable().dispatchEvent(new MouseEvent('click', { bubbles: true }));
        fixture.detectChanges();

        expect(tooltip().textContent).toContain('Click to put back');
    });
});
