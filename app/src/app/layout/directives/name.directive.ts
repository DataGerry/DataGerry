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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Directive, HostListener } from '@angular/core';

/**
 * Converts a string to the name convention.
 * @param input string which will be converted.
 */
export function nameConvention(input: string): string {
  return input.toLowerCase().replace(/ /g, '-');
}

@Directive({
    selector: '[name-guideline]',
    standalone: false
})
export class NameDirective {

  /**
   * Converts input values into our name guidelines.
   * Letters will be transformed to lowercase and spaces replaced with hyphen.
   * @param $event HTML input value - which includes the name-guideline as directive
   */
  @HostListener('input', ['$event']) onInputChange($event) {
    $event.target.value = nameConvention($event.target.value);
  }

}
