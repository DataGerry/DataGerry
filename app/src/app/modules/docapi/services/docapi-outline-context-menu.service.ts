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

import { Injectable } from '@angular/core';

import { OutlineContextMenuState } from '../models/docapi-outline.model';

@Injectable({
    providedIn: 'root'
})
export class DocapiOutlineContextMenuService {
    private readonly menuWidthPx = 180;
    private readonly menuHeightPx = 88;
    private readonly viewportPaddingPx = 8;
    private readonly keyboardOffsetXPx = 160;
    private readonly keyboardOffsetYPx = 8;
    private readonly keyboardFallbackXPx = 80;
    private readonly keyboardFallbackYPx = 80;

    public createClosedState(): OutlineContextMenuState {
        return {
            visible: false,
            x: 0,
            y: 0,
            headingId: null
        };
    }

    public createOpenedStateFromPointer(clientX: number, clientY: number, headingId: string): OutlineContextMenuState {
        return {
            visible: true,
            x: this.clampX(clientX),
            y: this.clampY(clientY),
            headingId
        };
    }

    public tryCreateOpenedStateFromKeyboard(event: KeyboardEvent, headingId: string): OutlineContextMenuState | null {
        if (!this.isKeyboardContextMenuTrigger(event)) {
            return null;
        }

        event.preventDefault();
        event.stopPropagation();

        const triggerElement = event.currentTarget as HTMLElement | null;
        const triggerRect = triggerElement?.getBoundingClientRect();
        const pointerX = triggerRect
            ? triggerRect.left + Math.min(triggerRect.width, this.keyboardOffsetXPx)
            : this.keyboardFallbackXPx;
        const pointerY = triggerRect
            ? triggerRect.top + this.keyboardOffsetYPx
            : this.keyboardFallbackYPx;

        return this.createOpenedStateFromPointer(pointerX, pointerY, headingId);
    }

    public closeIfOpen(currentState: OutlineContextMenuState): OutlineContextMenuState {
        if (!currentState.visible) {
            return currentState;
        }

        return this.createClosedState();
    }

    private isKeyboardContextMenuTrigger(event: KeyboardEvent): boolean {
        return event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10');
    }

    private clampX(pointerX: number): number {
        const maxX = window.innerWidth - this.menuWidthPx;
        return Math.max(this.viewportPaddingPx, Math.min(pointerX, maxX));
    }

    private clampY(pointerY: number): number {
        const maxY = window.innerHeight - this.menuHeightPx;
        return Math.max(this.viewportPaddingPx, Math.min(pointerY, maxY));
    }
}
