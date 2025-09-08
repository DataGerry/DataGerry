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
   * Checks if the given value is a valid anchor tag string.
   * Example: <a href="https://example.com">Example</a>
   * @param value - The value to check, expected to be a string.
   * @returns True if the value matches the anchor tag pattern, otherwise false.
   */
  public isAnchorValue(value: any): boolean {
    if (typeof value !== 'string') return false;
    return /^<a\s+[^>]*href\s*=\s*(['"])(.*?)\1[^>]*>\s*([\s\S]*?)\s*<\/a>$/i.test(value.trim());
  }
  
  
  /**
   * Extracts the href (link URL) from a valid anchor tag string.
   * Example: from `<a href="https://example.com">Example</a>` it extracts "https://example.com".
   * @param value - The anchor tag string to parse.
   * @returns The href value as a string, or null if no match is found.
   */
  public getAnchorHref(value: string): string | null {
    const match = value?.trim().match(/^<a\s+[^>]*href\s*=\s*(['"])(.*?)\1[^>]*>\s*([\s\S]*?)\s*<\/a>$/i);
    return match ? match[2] : null;
  }
  

  /**
   * Extracts the link text (label) from a valid anchor tag string.
   * Example: from `<a href="https://example.com">Example</a>` it extracts "Example".
   * @param value - The anchor tag string to parse.
   * @returns The text inside the anchor tag, or null if no match is found.
   */
  public getAnchorText(value: string): string | null {
    const match = value?.trim().match(/^<a\s+[^>]*href\s*=\s*(['"])(.*?)\1[^>]*>\s*([\s\S]*?)\s*<\/a>$/i);
    return match ? match[3] : null;
  }
  
}
