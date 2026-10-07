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
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { CablingGraph } from '../models/cabling.types';
import { mockupRing } from '../testing/cabling-fixtures';
import { EMPTY_CABLING_GRAPH, graphFromRing } from '../utils/cabling-graph.util';
import { CablingSpotlightStore } from './cabling-spotlight.store';
import { CablingViewStore } from './cabling-view.store';

describe('CablingSpotlightStore', () => {
    let spotlightStore: CablingSpotlightStore;

    const graph = signal<CablingGraph>(graphFromRing(mockupRing()));
    const loadFailed = signal(false);

    beforeEach(() => {
        graph.set(graphFromRing(mockupRing()));
        loadFailed.set(false);

        TestBed.configureTestingModule({
            providers: [CablingSpotlightStore, { provide: CablingViewStore, useValue: { graph, loadFailed } }]
        });
        spotlightStore = TestBed.inject(CablingSpotlightStore);
    });

    it('is off until toggled, and goes off on the next toggle or when turned off', () => {
        expect(spotlightStore.active()).toBeFalse();

        spotlightStore.toggle();

        expect(spotlightStore.active()).toBeTrue();

        spotlightStore.toggle();

        expect(spotlightStore.active()).toBeFalse();

        spotlightStore.toggle();
        spotlightStore.turnOff();

        expect(spotlightStore.active()).toBeFalse();
    });

    it('cannot go on without cables, or once the cabling failed to load', () => {
        graph.set(EMPTY_CABLING_GRAPH);
        spotlightStore.toggle();

        expect(spotlightStore.active()).toBeFalse();

        graph.set(graphFromRing(mockupRing()));
        loadFailed.set(true);

        expect(spotlightStore.canLight()).toBeFalse();
    });
});
