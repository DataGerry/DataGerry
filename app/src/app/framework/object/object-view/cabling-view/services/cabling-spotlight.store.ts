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
import { Injectable, computed, inject, signal } from '@angular/core';

import { CablingViewStore } from './cabling-view.store';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Whether the spotlight is on. Provided per view, beside the graph it needs cables in. */
@Injectable()
export class CablingSpotlightStore {

    private readonly viewStore = inject(CablingViewStore);
    private readonly on = signal(false);

    /** An object without cables, or cabling that failed to load, has nothing to light. */
    public readonly canLight = computed(() => !this.viewStore.loadFailed() && this.viewStore.graph().edges.size > 0);

    public readonly active = computed(() => this.on() && this.canLight());

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public toggle(): void {
        this.on.set(!this.active() && this.canLight());
    }


    public turnOff(): void {
        this.on.set(false);
    }
}
