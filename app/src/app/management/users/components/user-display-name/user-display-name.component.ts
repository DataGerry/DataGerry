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

import { Component, Input } from '@angular/core';
import { User } from '../../../models/user';

@Component({
    selector: 'cmdb-user-display-name',
    templateUrl: './user-display-name.component.html',
    styleUrls: ['./user-display-name.component.scss'],
    standalone: false
})
export class UserDisplayNameComponent {

  @Input() public user: User;

  public displayName(): string {
    if (this.user.first_name && this.user.last_name) {
      return `${ this.user.first_name } ${ this.user.last_name }`;
    } else {
      return this.user.user_name;
    }
  }

}
