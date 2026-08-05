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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';

@Injectable()
export class ValidatorService {

  private static readonly regex = new RegExp('[.*+\\-?^${}()|[\\]\\\\]');

  public static getRegex() {
    return this.regex;
  }

  public static replaceTextWithRegex(value: string) {
    return value.replace(/[.*+\-?^${}()|[\]\\]/g, '\\$&');
  }

  public static validateRegex(input: string) {
    let regexObj;
    // check, if RegExp is valid JavaScript
    try {
        regexObj = new RegExp(input);
    } catch (e) {
        regexObj = new RegExp(input.replace(/[.*+\-?^${}()|[\]\\]/g, '\\$&'));
    }
    // replace '#', as they need to be escaped in MongoDB regex
    if (regexObj.source.includes('#')) {
        regexObj = new RegExp(regexObj.source.replace('#', '\\#'));
    }
    // replace '[]', as they need to be escaped in MongoDB regex
    if (regexObj.source.includes('[]')) {
        regexObj = new RegExp(regexObj.source.replace('[]', '\\[\\]'));
    }
    return regexObj.source;
  }
}
