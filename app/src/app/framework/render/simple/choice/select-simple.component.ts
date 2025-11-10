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
import { RenderFieldComponent } from '../../fields/components.fields';

@Component({
    templateUrl: './select-simple.component.html',
    styleUrls: ['./select-simple.component.scss'],
    standalone: false
})
export class SelectSimpleComponent extends RenderFieldComponent {

  constructor() {
    super();
  }

  /**
   * Retrieves the label corresponding to a given value from the options array.
   * 
   * @param value - The value for which to find the corresponding label.
   * @returns The label of the option with the matching value, or an empty string if no match is found.
   */
  getLabelForValue(value: string): string {

    // Find the option in the options array where the name property matches the given value
    const matchingOption = this.data.options.find(option => option.name === value);

    // If a matching option is found, return its label; otherwise, return an empty string
    return matchingOption ? matchingOption.label : '';
  }

}
