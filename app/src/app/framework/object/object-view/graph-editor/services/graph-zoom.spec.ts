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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GraphViewportService } from './graph-viewport.service';

/** Stands in for the shell: an OnPush view whose only zoom source is the service. */
@Component({
    selector: 'cmdb-zoom-host',
    template: '<span class="zoom-level">{{ zoomPercent }}</span>',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
class ZoomHostComponent implements OnInit {
    constructor(private cdr: ChangeDetectorRef, private viewport: GraphViewportService) { }

    get zoomPercent(): string {
        return `${(this.viewport.getZoom() * 100).toFixed(0)}%`;
    }

    ngOnInit(): void {
        // This is the wiring the shell sets up in ngOnInit.
        this.viewport.setFrameCallback(() => this.cdr.markForCheck());
    }
}

/**
 * A zoom step eases on a frame loop inside the service, so nothing about it marks the view
 * dirty on its own. This drives the real service through a real OnPush view and checks the
 * rendered zoom moves without any further interaction.
 */
describe('Zooming an OnPush graph view (in-browser)', () => {
    let fixture: ComponentFixture<ZoomHostComponent>;
    let viewport: GraphViewportService;

    /** One eased step is 200ms of real frames. */
    const settle = () => new Promise<void>(resolve => setTimeout(resolve, 400));
    const rendered = () => fixture.nativeElement.querySelector('.zoom-level').textContent;

    beforeEach(() => {
        TestBed.configureTestingModule({
            declarations: [ZoomHostComponent],
            providers: [GraphViewportService]
        });

        viewport = TestBed.inject(GraphViewportService);
        fixture = TestBed.createComponent(ZoomHostComponent);
        fixture.autoDetectChanges();
    });

    it('renders the default zoom', () => {
        expect(rendered()).toBe('65%');
    });

    it('renders the new zoom after zooming in', async () => {
        viewport.zoomIn();
        await settle();

        expect(viewport.getZoom()).toBeCloseTo(0.78, 5);
        expect(rendered()).toBe('78%');
    });

    it('renders the new zoom after zooming out', async () => {
        viewport.zoomOut();
        await settle();

        expect(rendered()).toBe('54%');
    });

    it('keeps stepping on repeated zooms', async () => {
        viewport.zoomIn();
        await settle();
        viewport.zoomIn();
        await settle();

        expect(rendered()).toBe('94%');
    });
});
