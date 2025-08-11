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
    selector: 'cmdb-input-appends',
    templateUrl: './input-appends.component.html',
    styleUrls: ['./input-appends.component.scss'],
    standalone: false
})
export class InputAppendsComponent extends RenderFieldComponent {

  constructor() {
    super();
  }

  public changeValueToDefault() {
    if (this.data.default && this.data.type === 'date' && !this.data.default.hasOwnProperty('$date')) {
      const d = new Date(this.data.default);
      d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      this.controller.setValue({$date: d.getTime()});
    } else {
      this.controller.setValue(this.data.default ? this.data.default : null);
    }
    this.controller.markAsDirty({onlySelf: true});
    this.controller.markAsTouched({onlySelf: true});
    this.parentFormGroup.markAsTouched({onlySelf: true});
    this.parentFormGroup.markAsDirty({onlySelf: true});
  }
}
