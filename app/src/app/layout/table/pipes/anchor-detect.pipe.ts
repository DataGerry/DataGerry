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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'anchorDetect' })
export class AnchorDetectPipe implements PipeTransform {
  private readonly pattern = /^<a\s+[^>]*href="([^"]+)"[^>]*>\s*([\s\S]*?)\s*<\/a>$/i;

  transform(value: any, mode: 'href' | 'text'): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    const match = trimmed.match(this.pattern);
    if (!match) return null;
    if (mode === 'href') return match[1];
    if (mode === 'text') return match[2];
    return null;
  }
}


