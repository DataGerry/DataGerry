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

import { Component, Input, OnInit } from '@angular/core';
import { CmdbType } from '../../../framework/models/cmdb-type';

@Component({
    selector: 'cmdb-type-label',
    templateUrl: './type-label.component.html',
    styleUrls: ['./type-label.component.scss'],
    standalone: false
})
export class TypeLabelComponent {

  public label: string;
  public icon: string;

  @Input() public description: string;
  @Input() public publicID: number;
  @Input() useURL: boolean = false;

  @Input()
  public set title(value: string) {
    this.label = value === undefined ? '' : value;
  }

  public get title(): string {
    return this.label;
  }

  @Input()
  public set faIcon(value: string) {
    this.icon = value === undefined ? 'cube' : value;
  }

  public get faIcon(): string {
    return this.icon;
  }


}
