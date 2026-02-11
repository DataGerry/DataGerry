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

import { Injectable } from '@angular/core';
import { KEYBOARD_SHORTCUTS } from '../constants/graph.constants';

@Injectable({ providedIn: 'root' })
export class GraphKeyboardService {

  /**
   * Handles keyboard shortcuts for graph interactions
   */
  handleKeyboard(
    event: KeyboardEvent,
    getKeyCombo: (event: KeyboardEvent) => string,
    keyboardShortcuts: any,
    componentMethods: any
  ): void {
    const key = getKeyCombo(event);

    const handlerName = keyboardShortcuts[key as keyof typeof KEYBOARD_SHORTCUTS];
    if (handlerName && typeof componentMethods[handlerName] === 'function') {
      event.preventDefault();
      componentMethods[handlerName]();
    }
  }

  /**
   * Generates a key combination string from the keyboard event
   */
  getKeyCombo(event: KeyboardEvent): string {
    const parts = [];
    if (event.ctrlKey || event.metaKey) parts.push('Ctrl');
    if (event.shiftKey) parts.push('Shift');
    if (event.altKey) parts.push('Alt');
    const keyName = event.key === '+' ? 'Plus' : event.key === '-' ? 'Minus' : event.key;
    parts.push(keyName);
    return parts.join('+');
  }
}
