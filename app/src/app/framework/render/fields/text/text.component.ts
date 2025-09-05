/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component } from '@angular/core';
import { RenderFieldComponent } from '../components.fields';

@Component({
  templateUrl: './text.component.html',
  styleUrls: ['./text.component.scss']
})
export class TextComponent extends RenderFieldComponent {

  public constructor() {
    super();
  }

  /**
   * Returns true if the provided value is exactly an anchor tag like
   * <a href="https://...">Label</a>
   */
  public isAnchorValue(value: any): boolean {
    if (typeof value !== 'string') return false;
    const trimmed = value.trim();
    const anchorPattern = /^<a\s+[^>]*href="([^"]+)"[^>]*>\s*([\s\S]*?)\s*<\/a>$/i;
    return anchorPattern.test(trimmed);
  }

  /** Extracts the href from an anchor string */
  public getAnchorHref(value: string): string | null {
    const match = value?.trim().match(/^<a\s+[^>]*href="([^"]+)"[^>]*>\s*([\s\S]*?)\s*<\/a>$/i);
    return match ? match[1] : null;
  }

  /** Extracts the label text from an anchor string */
  public getAnchorText(value: string): string | null {
    const match = value?.trim().match(/^<a\s+[^>]*href="([^"]+)"[^>]*>\s*([\s\S]*?)\s*<\/a>$/i);
    return match ? match[2] : null;
  }
}
