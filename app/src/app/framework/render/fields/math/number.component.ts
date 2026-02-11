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

import { Component } from '@angular/core';
import { RenderFieldComponent } from '../components.fields';

@Component({
    selector: 'cmdb-number',
    templateUrl: './number.component.html',
    styleUrls: ['./number.component.scss'],
    standalone: false
})
export class NumberComponent extends RenderFieldComponent {

  public constructor() {
    super();
  }

  public numberChange(event): any {
    this.value = +event.target.value;
  }

  public set value(valueList: any) {
    this.innerValue = +valueList;
  }

}

export { NumberComponent as default };