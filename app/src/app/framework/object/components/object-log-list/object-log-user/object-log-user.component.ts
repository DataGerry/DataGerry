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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, inject, Input, OnChanges, SimpleChanges } from '@angular/core';
import { User } from '../../../../../management/models/user';
import { UserService } from '../../../../../management/services/user.service';

@Component({
    selector: 'cmdb-object-log-user',
    templateUrl: './object-log-user.component.html',
    styleUrls: ['./object-log-user.component.scss'],
    standalone: false
})
export class ObjectLogUserComponent implements OnChanges {

  @Input() userID: number = 0;
  @Input() userName: string = '';

  public logUser: User;
  public userExists: boolean = false;

  private readonly userService = inject(UserService);

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes.userID !== undefined && changes.userID.isFirstChange()) {
      this.userService.getUser(this.userID)
        .subscribe({
          next: (possibleUser: User) => {
            this.logUser = possibleUser;
            this.userExists = true;
          },
          error: () => {
            this.userExists = false;
          }
        }
        );
    }
  }


}
