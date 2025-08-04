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

import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { User } from '../../../models/user';
import { UserService } from '../../../services/user.service';
import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'cmdb-user-compact',
  templateUrl: './user-compact.component.html',
  styleUrls: ['./user-compact.component.scss']
})
export class UserCompactComponent implements OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  @Input() public user: User;

  public userID: number;

  @Input('userID')
  public set UserID(id: number) {
    this.userID = id;
    if (this.userID) {
      this.userService.getUser(this.userID).pipe(takeUntil(this.subscriber)).subscribe((user: User) => {
        this.user = user;
      });
    }
  }

  public constructor(private userService: UserService) {

  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

}
