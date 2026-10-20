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
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CablingCanvasStore } from '../services/cabling-canvas.store';
import { CablingGesturesDirective } from './cabling-gestures.directive';

@Component({
    standalone: true,
    imports: [CablingGesturesDirective],
    providers: [CablingCanvasStore],
    template: `
        <div class="frame" cmdbCablingGestures style="position: fixed; top: 0; left: 0; width: 400px; height: 300px;">
            <div class="card" data-object-id="7" style="width: 50px; height: 50px;"></div>
            <button type="button">Expand</button>
        </div>
    `
})
class GesturesHostComponent {}


describe('CablingGesturesDirective', () => {
    let fixture: ComponentFixture<GesturesHostComponent>;
    let canvas: CablingCanvasStore;

    const find = (selector: string): HTMLElement => fixture.nativeElement.querySelector(selector);

    const pointer = (target: Element, type: string, clientX: number, clientY: number) => {
        target.dispatchEvent(new PointerEvent(type, { pointerId: 1, button: 0, clientX, clientY, bubbles: true }));
        fixture.detectChanges();
    };

    beforeEach(() => {
        fixture = TestBed.createComponent(GesturesHostComponent);
        canvas = fixture.debugElement.injector.get(CablingCanvasStore);
        fixture.detectChanges();
    });

    it('pans the canvas by as far as the pointer moved, marked as panning until release', () => {
        pointer(find('.frame'), 'pointerdown', 100, 100);
        pointer(find('.frame'), 'pointermove', 160, 130);

        expect(canvas.viewport()).toEqual({ x: 60, y: 30, zoom: 1 });
        expect(find('.frame').classList).toContain('is-panning');

        pointer(find('.frame'), 'pointerup', 160, 130);

        expect(find('.frame').classList).not.toContain('is-panning');
        expect(canvas.dragged).toBeTrue();
    });

    it('drags a card in canvas units, scaled back by the zoom', () => {
        canvas.zoomAt(2, { x: 0, y: 0 });

        pointer(find('.card'), 'pointerdown', 10, 10);
        pointer(find('.card'), 'pointermove', 50, 30);

        expect(canvas.offsets().get(7)).toEqual({ x: 20, y: 10 });
        expect(canvas.viewport()).toEqual({ x: 0, y: 0, zoom: 2 });
    });

    it('treats a press that barely moves as a click', () => {
        pointer(find('.frame'), 'pointerdown', 100, 100);
        pointer(find('.frame'), 'pointermove', 102, 101);
        pointer(find('.frame'), 'pointerup', 102, 101);

        expect(canvas.viewport()).toEqual({ x: 0, y: 0, zoom: 1 });
        expect(canvas.dragged).toBeFalse();
    });

    it('leaves a press on a control to the control', () => {
        pointer(find('button'), 'pointerdown', 10, 10);
        pointer(find('button'), 'pointermove', 80, 80);

        expect(canvas.viewport()).toEqual({ x: 0, y: 0, zoom: 1 });
    });

    it('zooms around the pointer only while Ctrl or Cmd is held', () => {
        const wheel = (ctrlKey: boolean) => {
            const event = new WheelEvent('wheel', {
                deltaY: -100, clientX: 200, clientY: 150, ctrlKey, cancelable: true
            });

            find('.frame').dispatchEvent(event);

            return event;
        };

        expect(wheel(false).defaultPrevented).toBeFalse();
        expect(canvas.viewport().zoom).toBe(1);

        expect(wheel(true).defaultPrevented).toBeTrue();
        expect(canvas.viewport().zoom).toBeGreaterThan(1);
    });
});
